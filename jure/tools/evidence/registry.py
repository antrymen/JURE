"""Central dispatch and failure normalization for evidence acquisition."""
from __future__ import annotations

from collections.abc import Mapping

from jure.casefile.models import FrozenJSON, utc_now

from .base import EvidenceTool, ToolExecutionResult, ToolMetadata


class EvidenceToolRegistry:
    def __init__(self, tools=()):
        self._tools: dict[str, EvidenceTool] = {}
        for tool in tools:
            self.register_tool(tool)

    def register_tool(self, tool: EvidenceTool) -> None:
        if not isinstance(tool, EvidenceTool) or not isinstance(tool.metadata, ToolMetadata):
            raise TypeError("tools must implement EvidenceTool with validated ToolMetadata")
        if tool.metadata.tool_id in self._tools:
            raise ValueError(f"tool already registered: {tool.metadata.tool_id}")
        self._tools[tool.metadata.tool_id] = tool

    def get_tools_for_evidence_type(self, evidence_type: str) -> tuple[EvidenceTool, ...]:
        return tuple(tool for tool in self._tools.values()
                     if tool.metadata.tool_type == evidence_type)

    def metadata_snapshot(self) -> tuple[ToolMetadata, ...]:
        return tuple(tool.metadata for tool in self._tools.values())

    def get_tool(self, tool_id: str) -> EvidenceTool | None:
        return self._tools.get(tool_id)

    def execute(self, tool_id: str, operation: str, inputs: Mapping) -> ToolExecutionResult:
        started_at = utc_now()
        tool = self._tools.get(tool_id)
        version = tool.metadata.version if tool else "unknown"
        parameters = FrozenJSON()

        def result(status, payload=None, reason=None, warnings=()):
            return ToolExecutionResult(
                status=status, tool_id=tool_id, tool_version=version, operation=operation,
                parameters=parameters, payload=payload or {}, failure_reason=reason,
                warnings=warnings, started_at=started_at, completed_at=utc_now(),
            )

        try:
            parameters = FrozenJSON(inputs)
        except (ValueError, TypeError) as exc:
            return result("failed", reason=f"invalid_inputs: {exc}")
        if tool is None or tool.metadata.availability != "available":
            return result("failed", reason="source_unavailable")
        if operation not in tool.metadata.capabilities:
            return result("failed", reason=f"unsupported_operation: {operation}")
        missing = set(tool.metadata.required_inputs.get(operation, [])) - set(inputs)
        if missing:
            return result("failed", reason=f"missing_inputs: {', '.join(sorted(missing))}")
        try:
            raw = tool.execute(operation, parameters.to_dict())
        except TimeoutError as exc:
            return result("failed", reason="timeout")
        except (ConnectionError, OSError) as exc:
            return result("failed", reason=f"source_unavailable: {type(exc).__name__}")
        except (ValueError, TypeError, KeyError) as exc:
            return result("failed", reason=f"malformed_response_or_inputs: {type(exc).__name__}")
        except Exception as exc:
            return result("failed", reason=f"tool_error: {type(exc).__name__}")
        if raw is None:
            return result("no_result", reason="no_result", warnings=(
                "Absence of retrieved evidence is not evidence against a hypothesis.",))
        try:
            if isinstance(raw, ToolExecutionResult):
                if (raw.tool_id, raw.tool_version, raw.operation) != (tool_id, version, operation):
                    raise ValueError("response identity does not match executed tool")
                payload = raw.payload.to_dict()
                if raw.status in ("success", "insufficient_data"):
                    tool.validate_payload(operation, payload)
                return result(raw.status, payload, raw.failure_reason, raw.warnings)
            if not isinstance(raw, Mapping):
                raise ValueError("tool returned a non-object payload")
            tool.validate_payload(operation, raw)
            payload = FrozenJSON(raw)
            warnings = tuple(payload.get("warnings", ()))
            if any(not isinstance(item, str) or not item.strip() for item in warnings):
                raise ValueError("warnings must contain nonempty strings")
            if payload.get("support_quality") == "insufficient":
                return result("insufficient_data", payload,
                              "insufficient_support", warnings)
            if payload.get("has_results") is False:
                return result("no_result", payload, "no_result", warnings + (
                    "Absence of retrieved evidence is not evidence against a hypothesis.",))
            return result("success", payload, warnings=warnings)
        except Exception as exc:
            return result("failed", reason=f"malformed_response: {type(exc).__name__}")
