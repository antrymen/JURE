"""Portable schema export; cross-reference checks also require validate_case."""

from typing import Any

from .models import CaseFile


def case_json_schema() -> dict[str, Any]:
    """Return a fresh JSON Schema for Shared Case File v0.1."""
    schema = CaseFile.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:jure:shared-case-file:0.1.1"
    schema["description"] = (
        "Shared structured investigation state. Use validate_case in addition "
        "to this schema to check references, revision chains, and audit sequences."
    )
    return schema
