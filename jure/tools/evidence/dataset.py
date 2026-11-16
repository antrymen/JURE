"""Dataset-facing acquisition interface, independent of the dataset implementation."""
from abc import abstractmethod
from collections.abc import Mapping
import math

from .base import EvidenceTool


class DatasetEvidenceTool(EvidenceTool):
    @abstractmethod
    def joint_frequency(self, pattern, **kwargs): ...

    @abstractmethod
    def conditional_frequency(self, target_gene=None, target_state=1, conditions=None, **kwargs): ...

    @abstractmethod
    def compare_conditional_frequency(self, target_gene=None, conditioning_gene=None,
                                      target_state=1, **kwargs): ...

    @abstractmethod
    def compare_pattern_between_conditions(self, pattern, **kwargs): ...

    @abstractmethod
    def get_support(self, pattern=None, **kwargs): ...

    def validate_payload(self, operation, payload):
        super().validate_payload(operation, payload)
        for field in ("dataset_id", "dataset_version", "cell_context", "cell_subset",
                      "query_specification", "statistical_method", "code_version", "n_cells",
                      "support_quality", "warnings", "limitations"):
            if field not in payload:
                raise ValueError(f"dataset response missing {field}")
        if payload["support_quality"] not in ("sufficient", "limited", "insufficient", "unknown"):
            raise ValueError("invalid support_quality")
        if type(payload["n_cells"]) is not int or payload["n_cells"] < 0:
            raise ValueError("n_cells must be a nonnegative count")
        for field in ("dataset_id", "dataset_version", "statistical_method", "code_version"):
            if not isinstance(payload[field], str) or not payload[field].strip():
                raise ValueError(f"{field} must be nonempty text")
        groups = (payload["group_positive"], payload["group_negative"]) if (
            operation == "compare_conditional_frequency") else (
                (payload["control"], payload["perturbation"]) if (
                    operation == "compare_pattern_between_conditions") else (payload,))
        for group in groups:
            if not isinstance(group, Mapping):
                raise ValueError("frequency group must be an object")
            for field in ("numerator", "denominator", "probability", "support", "uncertainty"):
                if field not in group:
                    raise ValueError(f"frequency response missing {field}")
            count, total = group["numerator"], group["denominator"]
            if type(count) is not int or type(total) is not int or not 0 <= count <= total:
                raise ValueError("invalid empirical counts")
            if group["support"] != total:
                raise ValueError("support must equal the conditional denominator")
            expected = count / total if total else None
            probability = group["probability"]
            if ((expected is None and probability is not None)
                    or (expected is not None and (not isinstance(probability, (float, int))
                                                 or not math.isclose(probability, expected)))):
                raise ValueError("probability does not match empirical counts")
            uncertainty = group["uncertainty"]
            if not isinstance(uncertainty, Mapping) or not all(
                key in uncertainty for key in ("method", "confidence_level", "lower", "upper")
            ):
                raise ValueError("uncertainty must include method, confidence level and bounds")
            confidence = uncertainty["confidence_level"]
            if not isinstance(confidence, (float, int)) or not 0 < confidence < 1:
                raise ValueError("invalid uncertainty confidence level")
            lower, upper = uncertainty["lower"], uncertainty["upper"]
            if total and (not isinstance(lower, (float, int)) or not isinstance(upper, (float, int))
                          or not 0 <= lower <= upper <= 1):
                raise ValueError("invalid binomial uncertainty interval")
