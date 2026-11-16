"""GLM transport for existing JSON backends. No case analysis or tool routing."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import partial
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import signal
import threading
from contextlib import contextmanager
import time
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from typing import Literal


class GLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider: Literal["bigmodel"] = "bigmodel"
    model: Literal["glm-4.6v-flash", "glm-4.7-flash", "glm-5", "glm-5.3", "glm-5.3-flash"] = "glm-4.6v-flash"
    endpoint: Literal["https://open.bigmodel.cn/api/paas/v4/chat/completions"] = (
        "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    api_key_env: str = "JURE_GLM_API_KEY"
    temperature: float = Field(default=0.2, ge=0, le=1)
    max_tokens: int = Field(default=8192, ge=1, le=131072)
    thinking: Literal["enabled", "disabled"] = "disabled"
    response_format: Literal['text', 'json_object'] = 'text'
    reasoning_effort: Literal['low', 'high', 'max'] | None = None
    timeout_seconds: float = Field(default=180, gt=0, le=600)
    max_calls: int = Field(default=80, ge=1, le=1000)
    automatic_provider_retries: Literal[0] = 0

    @model_validator(mode='after')
    def model_capabilities(self):
        glm53_family = self.model in ('glm-5.3', 'glm-5.3-flash')
        if glm53_family and (self.thinking != 'enabled' or self.reasoning_effort is None):
            raise ValueError(f'{self.model} requires thinking enabled and an explicit reasoning_effort')
        if not glm53_family and self.reasoning_effort is not None:
            raise ValueError('reasoning_effort is only configured for the glm-5.3 family')
        if self.model == 'glm-4.6v-flash' and self.max_tokens > 16384:
            raise ValueError('Flash output cap remains 16384')
        return self


class GLMTransportError(RuntimeError):
    """Provider failure without credentials or untrusted provider error bodies."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to an endpoint outside the configured provider.
        return None


def _post(request, timeout):
    context = ssl.create_default_context()
    # python.org macOS installs may lack their optional cert.pem symlink.
    # Add the OS public root bundle; certificate/hostname validation stays on.
    if ssl.get_default_verify_paths().cafile is None and Path("/etc/ssl/cert.pem").is_file():
        context.load_verify_locations(cafile="/etc/ssl/cert.pem")
    with urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context)).open(
        request, timeout=timeout
    ) as response:
        return response.read()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _write(path, value):
    # O_EXCL prevents silently replacing a previous trace.
    with Path(path).open("x") as stream:
        stream.write(_json(value) + "\n")


@contextmanager
def _request_deadline(seconds):
    """Bound total acquisition time, even if a peer keeps a socket alive."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal,'setitimer'):
        raise GLMTransportError('wall_deadline_requires_main_thread')
    previous_handler=signal.getsignal(signal.SIGALRM)
    previous_timer=signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0]:raise GLMTransportError('existing_wall_deadline_conflict')
    def expired(signum,frame):raise TimeoutError('provider wall deadline exceeded')
    signal.signal(signal.SIGALRM,expired)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    try:yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous_handler)


class GLMTransport:
    def __init__(self, *, config: GLMConfig, api_key: str, trace_dir, sender=None):
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("GLM API key is missing or contains whitespace")
        self.config = config
        self._api_key = SecretStr(api_key)
        self._sender = sender or _post
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=False)
        self.calls = 0
        self.records = []
        _write(self.trace_dir / "provider_config.json", config.model_dump())

    def for_role(self, role):
        if role not in ("explorer", "investigator", "critic", "smoke"):
            raise ValueError("unknown reasoning role")
        return partial(self.__call__, role=role)

    def __call__(self, request, *, role):
        if self.calls >= self.config.max_calls:
            raise GLMTransportError("provider_call_budget_exhausted")
        if role not in ("explorer", "investigator", "critic", "smoke"):
            raise ValueError("unknown reasoning role")
        instructions = request["system_instructions"]
        data = {key: value for key, value in request.items() if key != "system_instructions"}
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": _json(data)},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "thinking": {"type": self.config.thinking},
            "stream": False,
        }
        if self.config.response_format == 'json_object':
            body['response_format'] = {'type': 'json_object'}
        if self.config.reasoning_effort is not None:
            body['reasoning_effort'] = self.config.reasoning_effort
        encoded = _json(body).encode()
        # The key belongs only to the Authorization header, never model context.
        if self._api_key.get_secret_value() in encoded.decode():
            raise ValueError("credential found in model input")
        self.calls += 1
        call_id = f"call_{self.calls:04d}_{role}"
        directory = self.trace_dir / call_id
        directory.mkdir()
        _write(directory / "request.json", body)
        record = {"call_id": call_id, "role": role,
                  "operation": request.get("method", request.get("mode", "smoke")),
                  "requested_model": self.config.model,
                  "started_at": datetime.now(timezone.utc).isoformat(),
                  "request_sha256": hashlib.sha256(encoded).hexdigest(),
                  "status": "started", "usage": None}
        started = time.monotonic()
        req = urllib.request.Request(self.config.endpoint, data=encoded, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self._api_key.get_secret_value(),
        })
        try:
            with _request_deadline(self.config.timeout_seconds):
                raw = self._sender(req, self.config.timeout_seconds)
            payload = json.loads(raw)
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise GLMTransportError("provider_response_has_no_choices")
            choice = choices[0]
            content = choice.get("message", {}).get("content")
            record.update(response_id=payload.get("id"), returned_model=payload.get("model"),
                          usage=payload.get("usage"), finish_reason=choice.get("finish_reason"))
            if not isinstance(content, str) or not content.strip():
                raise GLMTransportError("provider_response_has_no_final_content")
            # Retain the actual final answer and usage, excluding private reasoning fields.
            safe_content = content.replace(self._api_key.get_secret_value(), "[REDACTED]")
            _write(directory / "response.json", {"id": payload.get("id"), "model": payload.get("model"),
                "finish_reason": choice.get("finish_reason"), "content": safe_content, "usage": payload.get("usage")})
            if safe_content != content:
                raise GLMTransportError("credential_in_provider_response")
            if choice.get("finish_reason") != "stop":
                raise GLMTransportError("provider_response_incomplete")
            from jure.protocol.normalization import decode_json
            try:
                array_item_model = None
                if role == 'investigator' and request.get('method') == 'select_tool':
                    from jure.agents.investigator.backend import ToolSelection
                    array_item_model = ToolSelection
                decoded, wrapper_changes = decode_json(content,array_item_model=array_item_model)
            except (TypeError, ValueError):
                raise GLMTransportError("provider_response_is_not_json") from None
            if not isinstance(decoded, dict):
                raise GLMTransportError("provider_response_is_not_json_object")
            record["status"] = "success"
            _write(directory / "structured_output.json", decoded)
            if wrapper_changes:
                _write(directory / 'representation_wrappers.json', {'raw_value':content,
                    'normalized_value':decoded,'changes':wrapper_changes})
                record['normalization']='representation_wrapper_only'
            return json.dumps(decoded,ensure_ascii=False) if wrapper_changes else content.strip()
        except KeyboardInterrupt:
            record.update(status="interrupted", error="host_interrupted")
            raise
        except urllib.error.HTTPError as exc:
            record.update(status="failed", http_status=exc.code, error="provider_http_error")
            # Redact credentials before retaining diagnostic provider text.
            try:
                error = json.loads(exc.read()).get("error", {})
                code = str(error.get("code", ""))
                if re.fullmatch(r"[A-Za-z0-9_-]{1,24}", code):
                    record["provider_error_code"] = code
                message = error.get("message")
                if isinstance(message, str):
                    record["provider_message"] = message.replace(self._api_key.get_secret_value(), "[REDACTED]")[:1000]
            except (ValueError, TypeError, AttributeError):
                pass
            raise GLMTransportError(f"provider_http_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            record.update(status="failed", error="provider_connection_error", error_type=type(exc).__name__)
            raise GLMTransportError("provider_connection_error") from None
        except (GLMTransportError, ValueError, TypeError, KeyError) as exc:
            record.update(status="failed", error=str(exc) if isinstance(exc, GLMTransportError)
                          else "provider_response_malformed")
            raise GLMTransportError(record["error"]) from None
        finally:
            record.update(completed_at=datetime.now(timezone.utc).isoformat(),
                          elapsed_seconds=round(time.monotonic() - started, 3))
            _write(directory / "call.json", record)
            self.records.append(record)

    def summary(self):
        usage = {key: sum(int((r.get("usage") or {}).get(key, 0)) for r in self.records)
                 for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
        return {"model": self.config.model, "calls": self.calls,
                "successful_calls": sum(r["status"] == "success" for r in self.records),
                "usage": usage, "usage_complete": all(r.get("usage") is not None for r in self.records),
                "roles": sorted({r["role"] for r in self.records}),
                "elapsed_seconds": sum(r["elapsed_seconds"] for r in self.records)}


def create_glm_backends(transport):
    """Inject one real provider into all three existing reasoning boundaries."""
    from jure.agents.explorer.backend import JSONExplorerBackend
    from jure.agents.investigator.backend import JSONInvestigatorBackend
    from jure.agents.critic.backend import JSONCriticBackend
    return {
        "explorer": JSONExplorerBackend(transport.for_role("explorer")),
        "investigator": JSONInvestigatorBackend(transport.for_role("investigator")),
        "critic": JSONCriticBackend(transport.for_role("critic")),
    }


def main():
    parser = argparse.ArgumentParser(description="Test GLM authentication and JSON output without opening a case")
    parser.add_argument("--config", default="configs/agent_runtime_glm46v_flash.json")
    parser.add_argument("--trace-dir", required=True)
    parser.add_argument("--prompt-key", action="store_true", help="Read credential from a terminal without echo")
    args = parser.parse_args()
    config = GLMConfig.model_validate_json(Path(args.config).read_text())
    key = getpass.getpass("GLM API key (hidden): ") if args.prompt_key else os.environ.get(config.api_key_env, "")
    transport = GLMTransport(config=config, api_key=key, trace_dir=args.trace_dir)
    del key
    response = json.loads(transport.for_role("smoke")({
        "method": "json_connectivity_check",
        "system_instructions": 'Return only a JSON object matching response_schema. Set ok to true. No other text.',
        "context": {"purpose": "API connectivity test; no case, genes, hypotheses or evidence supplied"},
        "response_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"], "additionalProperties": False}}))
    if response != {"ok": True}:
        raise GLMTransportError("smoke_response_failed_contract")
    result = dict(status="PASS", **transport.summary(), case_content_sent=False, agents_run=False)
    _write(Path(args.trace_dir) / "smoke_result.json", result)
    print(_json(result))


if __name__ == "__main__":
    main()
