"""Bounded reasoning, validation, and atomic writes to the existing CaseStore.

No evidence acquisition or verdict is performed here. The trusted execution
service records the one fixed handoff after successful validation; the model
never receives a store, tools, or routing capability.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from jure.casefile import (
    ActionState, CaseStore, EvidenceQuestion, MechanisticQuestion,
    ObjectReference, PredictionRecord, RevisionConflict, new_id,
)
from jure.casefile.store import _atomic_write
from jure.casefile.history import agent_round_counts

from .backend import ExplorerBackend
from .context import ContextLimitError, build_explorer_context, explorer_write_contract
from .models import ExplorerConfig, ExplorerOutput, ExplorerRunResult
from .validation import interpret_observation, validate_explorer_output


def _annotation(store, case, event, run_id, *, object_type="case", object_id=None, **metadata):
    return store.append_history_event(
        case.metadata.case_id, actor="explorer",
        expected_revision=case.metadata.case_revision, summary=event,
        object_type=object_type, object_id=object_id or case.metadata.case_id,
        metadata={"explorer_event": event, "run_id": run_id, **metadata},
    )


def _protected_state_unchanged(before, after):
    for field in ("clue", "evidence_records", "evidence_assessments", "evidence_gaps", "contradictions"):
        if getattr(before, field) != getattr(after, field):
            raise ValueError(f"Explorer changed protected Case File field: {field}")
    if after.investigation_history[:len(before.investigation_history)] != before.investigation_history:
        raise ValueError("Explorer rewrote investigation history")
    hypotheses = {h.hypothesis_id: h for h in after.hypotheses}
    for original in before.hypotheses:
        current = hypotheses.get(original.hypothesis_id)
        if current is None or current.revisions[:len(original.revisions)] != original.revisions:
            raise ValueError("Explorer deleted or rewrote an old hypothesis revision/verdict")
        if current.predictions[:len(original.predictions)] != original.predictions:
            raise ValueError("Explorer rewrote an existing prediction")
    if after.evidence_questions[:len(before.evidence_questions)] != before.evidence_questions:
        raise ValueError("Explorer rewrote an existing evidence question")
    old_revision_ids = {r.revision_id for h in before.hypotheses for r in h.revisions}
    if any(r.status != "proposed" for h in after.hypotheses for r in h.revisions
           if r.revision_id not in old_revision_ids):
        raise ValueError("Explorer generated a hypothesis verdict")


class MechanismExplorer:
    def __init__(self, backend: ExplorerBackend, config: ExplorerConfig | None = None):
        self.backend = backend
        self.config = ExplorerConfig.model_validate(
            (config or ExplorerConfig()).model_dump(mode="json"))

    def run(self, store: CaseStore, case_id: str, *, mode="initial",
            reframe_reason: str | None = None, artifact_dir=None, capability_summary=None) -> ExplorerRunResult:
        """Return an audited result; unsuccessful reasoning writes no proposals.

        A stale Case File causes failure, never automatic regeneration against
        a different case revision. Max attempts is ``1 + max_retries``. JSON run
        exports are optional; the full run result lives in the SQLite history.
        """
        if mode not in {"initial", "reframe"}:
            raise ValueError("mode must be 'initial' or 'reframe'")
        source = store.load_case(case_id)
        run_id = new_id("EXPLORER")
        path = str(Path(artifact_dir).resolve() / f"{run_id}.json") if artifact_dir is not None else None
        base = dict(run_id=run_id, case_id=case_id, mode=mode, success=False,
                    source_case_revision=source.metadata.case_revision,
                    artifact_path=path, observation_interpretation=interpret_observation(source))
        errors = []
        warnings = []
        attempts = 0
        admission_checks = []
        admission = None
        try:
            if source.action_state.current_phase == "stopped":
                raise ValueError("Explorer cannot reopen a stopped case")
            if mode == "reframe":
                budget = next((e.metadata.get("budget_state") for e in reversed(source.investigation_history)
                               if e.action == "FINAL_CRITIC_AUDIT_STARTED"), None)
                if budget:
                    limit = budget["explorer_reframes"] + budget["explorer_reframes_remaining"]
                    if self.config.protocol_v3:
                        from jure.protocol.contracts import accepted_revision_count
                        used=accepted_revision_count(source)
                    else:
                        used = agent_round_counts(source, 'explorer', mode='reframe')[self.config.round_budget_basis]
                    if used >= limit:
                        raise ValueError("Critic reframe budget exhausted; final audit is required")
            started = _annotation(store, source, "EXPLORER_STARTED", run_id,
                                  mode=mode, reframe_reason=reframe_reason,
                                  source_case_revision=source.metadata.case_revision)
            if mode == "initial" and (source.mechanistic_question is not None or source.hypotheses
                                      or source.evidence_questions or source.evidence_records):
                raise ValueError("initial mode requires an unexplored case; use reframe")
            if mode == "reframe" and (not reframe_reason or not reframe_reason.strip()):
                raise ValueError("reframe requires a nonempty reframe_reason")
            if mode == "reframe" and (not source.hypotheses or source.mechanistic_question is None):
                raise ValueError("reframe requires an existing mechanistic question and hypotheses")
            context = build_explorer_context(source, mode, reframe_reason=reframe_reason,
                                             max_chars=self.config.max_context_chars)
            context["schema_requirements"].update(
                min_hypotheses=self.config.min_hypotheses,
                max_hypotheses=self.config.max_hypotheses,
            )
            context['write_contract'] = explorer_write_contract(self.config)
            if self.config.protocol_v3:
                from jure.protocol.contracts import revision_defects, latest_revision_state
                if not capability_summary:raise ValueError('Protocol v3 requires a factual capability summary')
                context['capability_summary']=capability_summary
                request,checks=latest_revision_state(source)
                context['revision_defects']=revision_defects(request) if mode=='reframe' and request else []
                context['revision_acceptance_history']=checks
                context['discrimination_contract']='Each new question requires comparison targets, per-hypothesis expectations, observable capability IDs, possible outcomes (including non-discriminating), and limitations. Do not choose a tool.'
            if mode == "reframe":
                context["schema_requirements"]["max_changed_hypotheses"] = self.config.max_hypotheses
            if len(json.dumps(context, ensure_ascii=False)) > self.config.max_context_chars:
                raise ContextLimitError("configured Explorer context exceeds max_context_chars")
            feedback = ()
            output = None
            whole_retries = self.config.max_retries if getattr(self.backend, 'whole_proposal_retries', True) else 0
            for attempts in range(1, whole_retries + 2):
                try:
                    generate = self.backend.generate_initial if mode == "initial" else self.backend.generate_reframe
                    # The backend cannot mutate the next attempt's context.
                    response = generate(json.loads(json.dumps(context, ensure_ascii=False)), feedback=feedback)
                    if isinstance(response, ExplorerOutput):
                        response = response.model_dump(mode="json")
                    if isinstance(response, Mapping):
                        response = json.dumps(dict(response), ensure_ascii=False, allow_nan=False)
                    if not isinstance(response, str):
                        raise ValueError("backend must return a JSON object or JSON string")
                    if len(response) > self.config.max_response_chars:
                        raise ValueError("backend response exceeds max_response_chars")
                    if self.config.validation_policy == 'three_layer':
                        from .admission import admit_proposal
                        output, admission = admit_proposal(response, source, mode=mode, config=self.config,
                            reframe_reason=reframe_reason, capability_summary=capability_summary)
                        admission_checks.append({'attempt': attempts, 'decision': admission.decision,
                            **admission.model_dump(mode='json')})
                        feedback = admission.blocking_messages
                    else:
                        output = ExplorerOutput.model_validate_json(response)
                        feedback = validate_explorer_output(output, source, mode, config=self.config,
                            reframe_reason=reframe_reason, capability_summary=capability_summary)
                    if not feedback:
                        break
                except (ValueError, TypeError, ValidationError) as error:
                    if self.config.validation_policy == 'three_layer':
                        from .admission import AdmissionResult, ValidationFinding
                        layer = 'completeness' if getattr(error, 'category', None) == 'completeness' else 'machine'
                        admission = AdmissionResult(findings=(ValidationFinding(layer=layer,
                            code='ADAPTER_OR_RESPONSE_CONTRACT', message=f'{type(error).__name__}: {str(error)[:4000]}'),))
                        admission_checks.append({'attempt': attempts, 'decision': admission.decision,
                            **admission.model_dump(mode='json')})
                    feedback = (f"{type(error).__name__}: {str(error)[:4000]}",)
                except Exception as error:
                    # Provider transport failures are bounded too; avoid
                    # persisting provider exception bodies, which may contain keys.
                    feedback = (f"backend failure: {type(error).__name__}",)
                errors.extend(f"attempt {attempts}: {error}" for error in feedback)
                output = None
            if output is None:
                raise ValueError("Explorer output failed validation within the retry limit")
            if errors:
                warnings.append("Earlier invalid backend attempts were discarded; final output passed validation.")
            warnings.extend(output.warnings)
            with store.atomic(case_id, expected_revision=started.metadata.case_revision) as current:
                current = self._apply(store, current, output, mode, reframe_reason, run_id)
                _protected_state_unchanged(source, current)
                # Routing is a fixed service action authorized by the Explorer
                # contract, not an LLM-generated decision or agent invocation.
                if admission is not None:
                    from .content_adapter import canonical_hash
                    current = _annotation(store, current, 'PROPOSAL_ADMITTED', run_id,
                        policy_version=admission.policy_version, mode=mode,
                        source_case_revision=source.metadata.case_revision,
                        proposal_sha256=canonical_hash(output.model_dump(mode='json')),
                        hypothesis_revision_ids={h.hypothesis_id: h.current_revision_id for h in current.hypotheses},
                        audit_flags=[f.model_dump(mode='json') for f in admission.audit_flags],
                        pair_decisions=[d.model_dump(mode='json') for d in output.pair_decisions],
                        decision=admission.decision)
                acceptance_needed=self.config.protocol_v3 and mode=='reframe'
                if acceptance_needed:
                    request=source.critic_audits.revision_requests[-1]
                    current=_annotation(store,current,'REVISION_SUBMITTED',run_id,
                        request_id=request.request_id,mode=mode,
                        changed_hypothesis_ids=[h.hypothesis_id for h in output.hypotheses],
                        new_object_ids=[p.prediction_id for p in output.predictions]+[q.question_id for q in output.evidence_questions],
                        submitted_revision_ids={h.hypothesis_id:h.current_revision_id for h in current.hypotheses})
                critic_needed = acceptance_needed and self.config.validation_policy != "three_layer"
                current = store.set_action_state(
                    case_id, ActionState(current_phase="critique_needed" if critic_needed else "evidence_needed",
                                       next_actor="critic" if critic_needed else "investigator"),
                    actor="controller", expected_revision=current.metadata.case_revision,
                )
                result = ExplorerRunResult(**{**base, "success": True}, attempts=attempts,
                    mechanistic_question_id=current.mechanistic_question.question_id,
                    created_hypothesis_ids=tuple(h.hypothesis_id for h in output.hypotheses if h.operation == "add"),
                    revised_hypothesis_ids=tuple(h.hypothesis_id for h in output.hypotheses if h.operation == "revise"),
                    created_prediction_ids=tuple(p.prediction_id for p in output.predictions),
                    created_evidence_question_ids=tuple(q.question_id for q in output.evidence_questions),
                    warnings=tuple(warnings), validation_errors=tuple(errors), admission_checks=tuple(admission_checks),
                    committed_case_revision=current.metadata.case_revision + 1,
                )
                _annotation(store, current, "EXPLORER_COMPLETED", run_id,
                            mode=mode, reframe_reason=reframe_reason,
                            hypothesis_contrasts=[c.model_dump(mode="json") for c in output.contrasts],
                            content_assembly={
                                'version':getattr(self.backend,'audit',{}).get('version'),
                                'patches':getattr(self.backend,'audit',{}).get('patches',[]),
                                'compiled_sha256':getattr(self.backend,'audit',{}).get('compiled_sha256'),
                            },
                            run_artifact=result.model_dump(mode="json"))
        except (ValueError, TypeError, RuntimeError, sqlite3.Error, OSError) as error:
            errors.append(f"{type(error).__name__}: {str(error)[:4000]}")
            result = ExplorerRunResult(**base, attempts=attempts,
                                       warnings=tuple(warnings), validation_errors=tuple(errors), admission_checks=tuple(admission_checks))
            # A failure note may use the latest snapshot: it only records the
            # failed run and its original source revision, never stale proposals.
            try:
                latest = store.load_case(case_id)
                _annotation(store, latest, "EXPLORER_FAILED", run_id, mode=mode,
                            reframe_reason=reframe_reason, run_artifact=result.model_dump(mode="json"))
            except (ValueError, TypeError, RuntimeError, sqlite3.Error, OSError) as audit_error:
                result = result.model_copy(update={"warnings": result.warnings + (
                    f"Failure audit could not be saved ({type(audit_error).__name__}); this run did not commit proposals.",)})
        if path is not None:
            try:
                if hasattr(self.backend, 'audit'):
                    _atomic_write(str(Path(artifact_dir)/'content_assembly_audit.json'),
                                  json.dumps(self.backend.audit, ensure_ascii=False, indent=2)+'\n')
                _atomic_write(path, result.model_dump_json(indent=2) + "\n")
            except OSError as error:
                result = result.model_copy(update={"artifact_path": None, "warnings": result.warnings + (
                    f"Run artifact export failed ({type(error).__name__}); inspect SQLite run history.",)})
                try:
                    latest = store.load_case(case_id)
                    _annotation(store, latest, "EXPLORER_ARTIFACT_EXPORT_FAILED", run_id,
                                attempted_path=path, run_artifact=result.model_dump(mode="json"))
                except (ValueError, TypeError, RuntimeError, sqlite3.Error, OSError) as audit_error:
                    result = result.model_copy(update={"warnings": result.warnings + (
                        f"Export failure audit could not be saved ({type(audit_error).__name__}).",)})
        return result

    def _apply(self, store, case, output, mode, reframe_reason, run_id):
        case = _annotation(store, case, "OBSERVATION_INTERPRETED", run_id,
                           observation_interpretation=output.observation_interpretation)
        if mode == "initial":
            case = store.add_mechanistic_question(case.metadata.case_id, MechanisticQuestion(
                question_text=output.mechanistic_question, derived_from_clue_id=case.clue.clue_id),
                actor="explorer", expected_revision=case.metadata.case_revision)
            event = "MECHANISTIC_QUESTION_CREATED"
        elif case.mechanistic_question.question_text != output.mechanistic_question:
            case = store.revise_mechanistic_question(
                case.metadata.case_id, new_text=output.mechanistic_question, reason=reframe_reason,
                actor="explorer", expected_revision=case.metadata.case_revision)
            event = "MECHANISTIC_QUESTION_REVISED"
        else:
            event = "MECHANISTIC_QUESTION_PRESERVED"
        case = _annotation(store, case, event, run_id, object_type="mechanistic_question",
                           object_id=case.mechanistic_question.question_id, reframe_reason=reframe_reason)
        for hypothesis in output.hypotheses:
            sources = list(hypothesis.derived_from)
            clue_ref = ObjectReference(object_type="clue", object_id=case.clue.clue_id)
            if clue_ref not in sources:
                sources.insert(0, clue_ref)
            values = dict(title=hypothesis.title, mechanism_statement=hypothesis.mechanism_statement,
                          mechanism_type=hypothesis.mechanism_type, assumptions=hypothesis.assumptions,
                          unresolved_points=hypothesis.unresolved_points,
                          weakening_conditions=hypothesis.weakening_conditions, derived_from=tuple(sources))
            if hypothesis.operation == "add":
                case = store.add_hypothesis(case.metadata.case_id, hypothesis_id=hypothesis.hypothesis_id,
                    actor="explorer", expected_revision=case.metadata.case_revision, **values)
                event = "HYPOTHESIS_ADDED_AFTER_REFRAME" if mode == "reframe" else "HYPOTHESIS_CREATED"
            else:
                case = store.update_hypothesis(case.metadata.case_id, hypothesis.hypothesis_id,
                    reason=hypothesis.reason, actor="explorer", expected_revision=case.metadata.case_revision, **values)
                event = "HYPOTHESIS_REVISED"
            revision = next(h for h in case.hypotheses if h.hypothesis_id == hypothesis.hypothesis_id).current_revision_id
            case = _annotation(store, case, event, run_id, object_type="hypothesis",
                               object_id=hypothesis.hypothesis_id, hypothesis_revision_id=revision,
                               structure=hypothesis.structure.model_dump(mode="json"),
                               reason=hypothesis.reason, reframe_reason=reframe_reason)
        revisions = {h.hypothesis_id: h.current_revision_id for h in case.hypotheses}
        for prediction in output.predictions:
            record = PredictionRecord(**prediction.model_dump(mode="python"),
                                      hypothesis_revision_id=revisions[prediction.hypothesis_id])
            case = store.add_prediction(case.metadata.case_id, record, actor="explorer",
                                         expected_revision=case.metadata.case_revision)
            case = _annotation(store, case, "PREDICTION_CREATED", run_id,
                               object_type="prediction", object_id=record.prediction_id)
        for question in output.evidence_questions:
            values=question.model_dump(mode="python",exclude={'discrimination'})
            if question.discrimination:
                values['query_spec']={'discrimination':question.discrimination.model_dump(mode='json')}
            record = EvidenceQuestion(**values)
            case = store.add_evidence_question(case.metadata.case_id, record, actor="explorer",
                                               expected_revision=case.metadata.case_revision)
            case = _annotation(store, case, "EVIDENCE_QUESTION_CREATED", run_id,
                               object_type="evidence_question", object_id=record.question_id)
        return case
