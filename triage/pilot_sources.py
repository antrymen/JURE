"""Read-only verification of the accepted Day6 TriageInput pool."""
from __future__ import annotations

import json
from pathlib import Path

from clue_discovery.integration.io import sha256
from clue_discovery.schemas import TriageInput, StructuredClueLandscape, ReferenceCatalogue
from clue_discovery.v03.artifacts import digest
from jure.casefile.models import MatchedControlShiftEvidence


def require_equal(actual, expected, label):
    if actual != expected:
        raise ValueError(f"source mismatch: {label}")


def shift_from_source(case: TriageInput, raw: dict) -> MatchedControlShiftEvidence:
    """Copy estimands; arithmetic below only verifies the frozen counts."""
    for field, key in {"candidate_id": "clue_id", "condition_id": "target", "reference_id": "reference_id",
                       "genes": "genes", "states": "states", "order": "order", "matched_effect": "delta"}.items():
        require_equal(getattr(case, field), raw[key], field)
    for part in case.support.values():
        for key, value in part.items():
            require_equal(value, raw[key], key)
    required_evidence = ("p_value", "selected_family_holm_exploratory", "family_size",
        "nominal_pointwise_delta_ci_low", "nominal_pointwise_delta_ci_high", "nt_selection_adjusted",
        "status", "statistical_method", "inference_scope", "ci_method",
        "effect_is_not_change_in_higher_order_interaction_strength")
    require_equal(case.association_evidence, {key: raw[key] for key in required_evidence}, "association evidence")
    require_equal(case.external_validation_status, raw["external_validation_status"].upper(), "Day8 status")
    require_equal(raw["support_and_effect_gates_passed"], True, "upstream gates")
    require_equal(raw["biological_replicate_validated"], False, "replication")
    require_equal(raw["eligible_as_confirmed_clue"], False, "confirmation")
    require_equal(case.provenance["association"]["source_clue_id"], case.candidate_id, "candidate provenance")
    if not -1 <= case.matched_effect <= 1 or case.matched_effect == 0:
        raise ValueError("nonzero finite matched effect required")
    direction = "enrichment" if case.matched_effect > 0 else "depletion"
    if direction not in case.strata or ({"enrichment", "depletion"} - {direction}) & set(case.strata):
        raise ValueError("direction/strata conflict")
    if case.sample_size_context["target_cell_count"] != raw["perturbation_n"]:
        raise ValueError("sample-size context disagrees with counts")
    batches = raw["batch_support"]
    n = raw["perturbation_n"]
    # Counts are validated before division, including exact integer types.
    for b in batches:
        for prefix in ("nt", "perturbation"):
            hits, cells = b[prefix + "_hits"], b[prefix + "_n"]
            if type(hits) is not int or type(cells) is not int or not 0 <= hits <= cells or cells <= 0:
                raise ValueError("invalid batch counts")
    if type(n) is not int or n <= 0:
        raise ValueError("invalid condition denominator")
    return MatchedControlShiftEvidence(
        control_frequency=raw["matched_nt_frequency"], perturb_frequency=raw["perturbation_frequency"],
        delta_frequency=raw["delta"], control_count=raw["pooled_nt_hits"], perturb_count=raw["perturbation_hits"],
        p_value_shift=raw["p_value"], status=raw["status"],
        control_frequency_definition="perturbation_batch_weighted_nt_frequency",
        control_count_scope="pooled_nt_descriptive_not_matched_frequency_numerator",
        perturbation_n=n, pooled_nt_n=raw["pooled_nt_n"],
        matched_nt_cells_pooled=sum(b["nt_n"] for b in batches),
        matched_nt_effective_n=1 / sum((b["perturbation_n"] / n) ** 2 / b["nt_n"] for b in batches),
        batch_support=tuple(batches), **{key: raw[key] for key in (
            "selected_family_holm_exploratory", "family_size", "nominal_pointwise_delta_ci_low",
            "nominal_pointwise_delta_ci_high", "ci_method", "statistical_method", "inference_scope",
            "nt_selection_adjusted")})


class VerifiedPilotSource:
    """Verify hashes and every candidate before any ranking; fail on corruption."""

    def __init__(self, run_root):
        self.root = Path(run_root).resolve()
        self.checked = {}
        self.manifest = json.loads((self.root / "run_manifest.json").read_text())
        if self.manifest["status"] != "COMPLETE":
            raise ValueError("source run is incomplete")
        self.triage_path = self.root / "landscape/triage_inputs.jsonl"
        for rel in ("landscape/triage_inputs.jsonl", "landscape/structured_clue_landscape.json",
                    "reference/reference_catalogue.json", "RUN_FROZEN_CONFIG.json"):
            self.check_file(self.root / rel, self.manifest["outputs"][rel])
        self.checked[str(self.root / "run_manifest.json")] = sha256(self.root / "run_manifest.json")
        self.cases = [TriageInput.model_validate_json(line) for line in self.triage_path.read_text().splitlines()]
        self.landscape = StructuredClueLandscape.model_validate_json(
            (self.root / "landscape/structured_clue_landscape.json").read_text())
        require_equal([c.model_dump() for c in self.cases],
                      [c.model_dump() for c in self.landscape.triage_inputs], "landscape/pool")
        if len({c.case_id for c in self.cases}) != len(self.cases) or len(
            {(c.condition_id, c.reference_id) for c in self.cases}
        ) != len(self.cases):
            raise ValueError("duplicate candidate identity")
        cat = ReferenceCatalogue.model_validate_json((self.root / "reference/reference_catalogue.json").read_text())
        self.references = {r.reference_id: r for r in cat.records}
        self.groups = {g.group_id: g for g in self.landscape.response_groups}
        self.relations = {r.relation_id: r for r in self.landscape.coresponse_relations + self.landscape.signed_state_contrasts}
        self._documents = {}
        self.raw_records, self.shifts = {}, {}
        if not self.cases:
            raise ValueError("empty pilot source")
        broad = self.cases[0].provenance["matrix_and_cell_sources"]["broad_manifest"]
        self._check_links(broad)
        broad_manifest = self.document(broad["path"])
        for path, checksum in broad_manifest["input_sha256"].items():
            self.check_file(path, checksum)
        for rel, checksum in broad_manifest["artifacts_sha256"].items():
            self.check_file(Path(broad["path"]).parent.parent / rel, checksum)
        scan_root = Path(self.cases[0].provenance["association"]["path"]).parent.parent
        identities_path = scan_root / "counts/identities.json"
        if str(identities_path.resolve()) not in self.checked:
            raise ValueError("scan identities not covered by source manifest")
        self.scan_identities = self.document(identities_path)
        scan_catalogue_digest = digest(self.scan_identities["patterns"])
        self._catalogue_checks = set()
        legacy_path = Path(broad["path"]).parent.parent / "agent_inputs/deep_case_pool.jsonl"
        self.legacy = {c["case_id"]: c for c in self.document(legacy_path, jsonl=True)}
        for case in self.cases:
            self._check_links(case.provenance)
            require_equal(case.dataset_id, self.manifest["dataset_id"], "dataset")
            source = case.provenance["association"]
            lines = self.document(source["path"], jsonl=True)
            line = source["line"]
            if type(line) is not int or not 1 <= line <= len(lines):
                raise ValueError("invalid 1-based source line")
            raw = lines[line - 1]
            self.shifts[case.case_id] = shift_from_source(case, raw)
            self.raw_records[case.case_id] = raw
            r = self.references[case.reference_id]
            require_equal((case.genes, case.states, case.order), (r.genes, r.states, r.order), "signed state")
            require_equal(case.reference_evidence, dict(reference_dataset_id=r.dataset_id,
                reference_id=r.reference_id, qualification=r.qualification, mfi=r.mfi_evidence,
                gain=r.gain_evidence, provenance=r.provenance), "reference evidence")
            envelope = self.document(case.provenance["reference"]["path"])
            require_equal(raw["catalogue_digest"], scan_catalogue_digest, "scan patterns digest")
            if envelope["sha256"] not in self._catalogue_checks:
                require_equal(self.scan_identities["patterns"], envelope["payload"]["records"], "scan/catalogue records")
                self._catalogue_checks.add(envelope["sha256"])
            group = self.groups[case.group_context["group_id"]]
            if case.reference_id not in group.reference_ids:
                raise ValueError("reference missing from group")
            require_equal(case.stable_core_context["members"], group.stable_core, "stable core members")
            legacy = self.legacy[case.case_id]
            require_equal(case.stable_core_context["status"], legacy["core_or_boundary"], "core status")
            require_equal(case.stable_core_context["status"] == "stable_core",
                          case.reference_id in group.stable_core, "core membership")
            require_equal(case.strata, legacy["strata"], "source strata")
            require_equal(case.sampling_block_id, legacy["redundancy_group_id"], "sampling block")
            for relation_id in case.coresponse_context + case.signed_state_contrast_context:
                rel = self.relations[relation_id]
                if case.reference_id not in (rel.reference_a, rel.reference_b):
                    raise ValueError("relation does not involve reference")

    def check_file(self, path, expected):
        path = str(Path(path).resolve())
        actual = self.checked.get(path)
        if actual is None:
            actual = sha256(path)
        require_equal(actual, expected, f"SHA256 {path}")
        self.checked[path] = actual

    def _check_links(self, obj):
        if isinstance(obj, dict):
            if "path" in obj and "sha256" in obj:
                self.check_file(obj["path"], obj["sha256"])
            for value in obj.values():
                self._check_links(value)
        elif isinstance(obj, list):
            for value in obj:
                self._check_links(value)

    def document(self, path, *, jsonl=False):
        path = str(path)
        if path not in self._documents:
            text = Path(path).read_text()
            obj = [json.loads(line) for line in text.splitlines()] if jsonl else json.loads(text)
            if isinstance(obj, dict) and "payload" in obj and "sha256" in obj:
                require_equal(digest(obj["payload"]), obj["sha256"], "catalogue payload checksum")
            self._documents[path] = obj
        return self._documents[path]

    def case_relations(self, case):
        # Triage relation lists are reference-wide. Qualifying structural relations
        # must also have this condition among their shared candidate conditions.
        return [self.relations[key] for key in case.coresponse_context + case.signed_state_contrast_context
                if case.condition_id in self.relations[key].shared_candidate_conditions]

    def assert_unchanged(self):
        for path, checksum in self.checked.items():
            require_equal(sha256(path), checksum, f"source changed during preparation: {path}")
