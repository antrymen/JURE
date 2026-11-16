"""Typed tool contracts. Tool output is not a Case File EvidenceRecord."""
from __future__ import annotations

from abc import ABC
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from jure.casefile.models import FrozenJSON, FrozenModel, Text, utc_now


EvidenceType = Literal["dataset", "network", "literature", "other"]
ExecutionStatus = Literal["success", "no_result", "insufficient_data", "failed"]


class ToolMetadata(FrozenModel):
    tool_id: Text
    tool_type: EvidenceType
    version: Text = "0.1.0"
    capabilities: tuple[Text, ...]
    required_inputs: FrozenJSON = Field(default_factory=FrozenJSON)
    cost_class: Literal["low", "medium", "high"] = "low"
    availability: Literal["available", "unavailable"] = "available"

    @model_validator(mode="after")
    def unique_capabilities(self):
        if not self.capabilities or len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be nonempty and unique")
        if set(self.required_inputs) - set(self.capabilities):
            raise ValueError("required_inputs must describe advertised capabilities")
        for inputs in self.required_inputs.values():
            if not isinstance(inputs, list) or any(not isinstance(item, str) for item in inputs):
                raise ValueError("required_inputs maps operation names to lists of field names")
        return self

    @property
    def tool_version(self):
        return self.version


class ToolExecutionResult(FrozenModel):
    status: ExecutionStatus
    tool_id: Text
    tool_version: Text
    operation: Text
    parameters: FrozenJSON = Field(default_factory=FrozenJSON)
    payload: FrozenJSON = Field(default_factory=FrozenJSON)
    failure_reason: Text | None = None
    warnings: tuple[Text, ...] = ()
    started_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def consistent_execution(self):
        if self.completed_at < self.started_at:
            raise ValueError("completion cannot precede start")
        if self.status != "success" and self.failure_reason is None:
            raise ValueError("unsuccessful execution requires a failure_reason")
        return self


class EvidenceTool(ABC):
    metadata: ToolMetadata

    def execute(self, operation: str, inputs: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Dispatch only an advertised public capability."""
        if operation not in self.metadata.capabilities:
            raise ValueError(f"unsupported operation: {operation}")
        return getattr(self, operation)(**dict(inputs))

    def validate_payload(self, operation: str, payload: Mapping[str, Any]) -> None:
        """Real adapters must validate their response before its contents are used."""
        if not isinstance(payload, Mapping):
            raise ValueError("tool payload must be an object")
        FrozenJSON(payload)
        for key in ("warnings", "limitations"):
            if key in payload and (not isinstance(payload[key], (list, tuple)) or any(
                    not isinstance(value, str) or not value.strip() for value in payload[key])):
                raise ValueError(f"{key} must be a list of nonempty strings")
        if "has_results" in payload and type(payload["has_results"]) is not bool:
            raise ValueError("has_results must be a boolean")
