"""SelectedCase → factual ClueRecord → revision-1 CaseFile. No Agent imports."""
import hashlib

from clue_discovery.schemas import SelectedCase
from .models import ClueRecord, PatternRecord


def clue_from_selected_case(selected, *, verified_source):
    selected = SelectedCase.model_validate(selected)
    case = selected.case
    source = verified_source
    if case not in source.cases:
        raise ValueError("SelectedCase differs from the verified source pool")
    if selected.selection_method not in {"rule", "human"}:
        raise ValueError("adapter requires rule selection or explicit human selection")
    if selected.selection_method == "human" and not selected.selection_provenance.get("user_authorization"):
        raise ValueError("human selection requires recorded user authorization")
    if selected.selection_provenance["triage_sha256"] != source.checked[str(source.triage_path)]:
        raise ValueError("selection used a different pool")
    ref = source.references[case.reference_id]
    group = source.groups[case.group_context["group_id"]]
    return ClueRecord(
        clue_id="CLUE_" + hashlib.sha256((case.dataset_id + ":" + case.candidate_id).encode()).hexdigest()[:24],
        perturbation=case.condition_id,
        pattern=PatternRecord(genes=tuple(case.genes), states=tuple(case.states), order=case.order,
                              pattern_string="".join(g + ("+" if s else "-") for g, s in zip(case.genes, case.states))),
        discovery_mode="reference_guided", source_schema_version=case.schema_version,
        source_run_id=source.root.name, source_artifact=str(source.triage_path),
        source_artifact_sha256=source.checked[str(source.triage_path)], reference_id=case.reference_id,
        catalogue_sha256=source.document(case.provenance["reference"]["path"])["sha256"],
        perturbation_shift=source.shifts[case.case_id], replication_status="NOT_PERFORMED",
        upstream_context={
            "evidence_level": case.evidence_level.value, "dataset_evidence_status": "DAY6_EXPLORATORY",
            "external_validation_status": case.external_validation_status, "day8_status": "NOT_PERFORMED",
            "reference_evidence": ref.model_dump(mode="json"),
            "group_context": case.group_context, "stable_core_context": case.stable_core_context,
            "group_representative_reference_id": group.representative_reference_id,
            "sample_size_context": case.sample_size_context, "sampling_block_id": case.sampling_block_id,
            "coresponse_context": case.coresponse_context,
            "signed_state_contrast_context": case.signed_state_contrast_context,
            "condition_specific_relations": [r.model_dump(mode="json") for r in source.case_relations(case)],
            "provenance": case.provenance,
        },
        source_payload={"selected_case": selected.model_dump(mode="json"),
                        "original_association": source.raw_records[case.case_id]},
    )


def initialize_selected_case(selected, *, verified_source, store):
    clue = clue_from_selected_case(selected, verified_source=verified_source)
    return store.create_case_from_clue(clue, case_id=selected.case.case_id, actor="controller",
                                      source_dataset=selected.case.dataset_id, cell_context="K562")
