"""Content-addressed raw results; Case File stores references, never raw bodies."""
import hashlib
import json
from pathlib import Path

from jure.casefile.models import FrozenModel, Text
from jure.casefile.store import _atomic_write


class RawEvidenceArtifact(FrozenModel):
    raw_result_reference: Text
    sha256: Text
    run_id: Text
    tool_id: Text


def save_raw_result(result, directory, run_id):
    payload = result.model_dump(mode="json")
    content = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    path = Path(directory).resolve() / "raw_evidence" / f"{digest}.json"
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("raw evidence artifact digest mismatch")
    else:
        _atomic_write(path, content)
    return RawEvidenceArtifact(raw_result_reference=str(path), sha256=digest,
                               run_id=run_id, tool_id=result.tool_id)
