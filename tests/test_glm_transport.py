import io
import json
import urllib.error

import pytest

from jure.llm.glm import GLMConfig, GLMTransport, GLMTransportError, create_glm_backends

KEY = "unit-test-only-secret"


def reply(content='{"ok":true}', finish_reason="stop"):
    return json.dumps({"id": "test-response", "model": "glm-4.6v-flash", "usage": {
        "prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        "choices": [{"finish_reason": finish_reason, "message": {"content": content,
            "reasoning_content": "not part of the final scientific record"}}]}).encode()


def request():
    return {"system_instructions": "Only JSON", "method": "test", "context": {}, "response_schema": {}}


def test_credentials_only_in_header_and_role_backends_are_real_json_adapters(tmp_path):
    sent = []
    def sender(req, timeout):
        sent.append(req)
        return reply()
    transport = GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "trace", sender=sender)
    backends = create_glm_backends(transport)
    assert set(backends) == {"explorer", "investigator", "critic"}
    for role in backends:
        transport.for_role(role)(request())
    assert sent[0].get_header("Authorization") == "Bearer " + KEY
    assert KEY not in sent[0].data.decode()
    for path in (tmp_path / "trace").rglob("*.json"):
        assert KEY not in path.read_text()
        assert "not part of the final scientific record" not in path.read_text()
    assert transport.summary()["usage"]["total_tokens"] == 42
    assert transport.summary()["roles"] == ["critic", "explorer", "investigator"]


@pytest.mark.parametrize("content,finish", [('not-json', 'stop'), ('[]', 'stop'), ('{"ok":true}', 'length')])
def test_bad_or_truncated_output_fails_without_fallback(tmp_path, content, finish):
    transport = GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "trace",
                             sender=lambda *_: reply(content, finish))
    with pytest.raises(GLMTransportError):
        transport.for_role("explorer")(request())
    assert transport.calls == 1 and transport.records[0]["status"] == "failed"


def test_provider_error_does_not_echo_key_or_retry(tmp_path):
    def sender(*_):
        raise urllib.error.HTTPError("https://open.bigmodel.cn", 401, "message:" + KEY, {},
            io.BytesIO(json.dumps({"error": {"code": "1000", "message": KEY}}).encode()))
    transport = GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "trace", sender=sender)
    with pytest.raises(GLMTransportError, match="provider_http_401") as exc:
        transport.for_role("smoke")(request())
    assert KEY not in str(exc.value)
    assert transport.calls == 1
    assert transport.records[0]["provider_error_code"] == "1000"
    assert KEY not in (tmp_path / "trace/call_0001_smoke/call.json").read_text()


def test_budget_and_existing_trace_prevent_hidden_calls_and_overwrites(tmp_path):
    transport = GLMTransport(config=GLMConfig(max_calls=1), api_key=KEY, trace_dir=tmp_path / "trace",
                             sender=lambda *_: reply())
    transport.for_role("smoke")(request())
    with pytest.raises(GLMTransportError, match="budget"):
        transport.for_role("smoke")(request())
    with pytest.raises(FileExistsError):
        GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "trace")


def test_endpoint_cannot_redirect_credential_to_other_provider():
    with pytest.raises(ValueError):
        GLMConfig(endpoint="https://example.com/chat/completions")


def test_explicit_json_block_is_extracted_and_surrounding_prose_retained(tmp_path):
    content = '```json\n{"ok":true}\n```'
    transport = GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "trace",
                             sender=lambda *_: reply(content))
    assert json.loads(transport.for_role("smoke")(request())) == {"ok": True}
    assert transport.records[0]["normalization"] == "representation_wrapper_only"
    assert (tmp_path/'trace/call_0001_smoke/representation_wrappers.json').exists()
    assert json.loads((tmp_path / "trace/call_0001_smoke/response.json").read_text())["content"] == content
    transport = GLMTransport(config=GLMConfig(), api_key=KEY, trace_dir=tmp_path / "bad",
                             sender=lambda *_: reply("Explanation\n" + content))
    assert json.loads(transport.for_role("smoke")(request())) == {"ok": True}
    assert json.loads((tmp_path/'bad/call_0001_smoke/response.json').read_text())['content'] == "Explanation\n" + content


def test_investigator_select_tool_accepts_unique_typed_array_wrapper(tmp_path):
    content=json.dumps([{'tool_id':'data_experiment','reason':'Run the selected query.'},
                        {'answer':'tool selected'}])
    transport=GLMTransport(config=GLMConfig(),api_key=KEY,trace_dir=tmp_path/'array',
                           sender=lambda *_:reply(content))
    selected=json.loads(transport.for_role('investigator')({**request(),'method':'select_tool'}))
    assert selected=={'tool_id':'data_experiment','reason':'Run the selected query.'}
    record=json.loads((tmp_path/'array/call_0001_investigator/representation_wrappers.json').read_text())
    assert record['raw_value']==content
    assert record['normalized_value']==selected


def test_native_json_mode_is_sent_without_relaxing_response_validation(tmp_path):
    sent=[]
    def sender(req,timeout):sent.append(json.loads(req.data));return reply('Invalid JSON')
    transport=GLMTransport(config=GLMConfig(model='glm-5',response_format='json_object'),
                           api_key=KEY,trace_dir=tmp_path/'native',sender=sender)
    with pytest.raises(GLMTransportError,match='not_json'):transport.for_role('explorer')(request())
    assert sent[0]['response_format']=={'type':'json_object'}
    assert transport.records[0]['status']=='failed'
    assert json.loads((tmp_path/'native/call_0001_explorer/response.json').read_text())['content']=='Invalid JSON'


@pytest.mark.parametrize('model', ['glm-5.3', 'glm-5.3-flash'])
def test_glm53_requires_explicit_supported_thinking_and_sends_it(tmp_path, model):
    with pytest.raises(ValueError,match='requires thinking'):
        GLMConfig(model=model)
    sent=[]
    def sender(req,timeout):sent.append(json.loads(req.data));return reply()
    config=GLMConfig(model=model,thinking='enabled',reasoning_effort='low',
                     response_format='json_object',max_tokens=32768)
    transport=GLMTransport(config=config,api_key=KEY,trace_dir=tmp_path/'glm53',sender=sender)
    transport.for_role('smoke')(request())
    assert sent[0]['model']==model and sent[0]['thinking']=={'type':'enabled'}
    assert sent[0]['reasoning_effort']=='low' and sent[0]['max_tokens']==32768

def test_provider_total_deadline_interrupts_a_stalled_sender(tmp_path):
    import time,signal
    original=signal.getsignal(signal.SIGALRM)
    def stalled(*args):time.sleep(.4);return reply()
    transport=GLMTransport(config=GLMConfig(timeout_seconds=.05),api_key=KEY,trace_dir=tmp_path/'deadline',sender=stalled)
    started=time.monotonic()
    with pytest.raises(GLMTransportError,match='provider_connection_error'):transport.for_role('smoke')(request())
    assert time.monotonic()-started<.3
    assert transport.records[0]['error_type']=='TimeoutError'
    assert signal.getsignal(signal.SIGALRM)==original and signal.getitimer(signal.ITIMER_REAL)[0]==0
