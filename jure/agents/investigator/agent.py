"""I1–I5: bounded question selection, acquisition, then one atomic case commit."""
from pathlib import Path

from jure.casefile import ActionState, CaseStore, new_id
from jure.casefile.models import Identifier
from jure.casefile.history import count_evidence_tool_calls, agent_round_counts
from jure.casefile.store import _atomic_write
from pydantic import TypeAdapter

from jure.tools.evidence.registry import EvidenceToolRegistry
from .artifacts import save_raw_result
from .backend import MockInvestigatorBackend, ToolInterpretation, ToolSelection
from .context import build_investigator_context
from .evidence_normalizer import normalize_tool_result
from .prioritization import PrioritizationResult
from .query_plan import QueryPlan
from .queue import SELECTABLE, deduplicate_evidence_questions, record_event
from .recording import InvestigationRecorder
from .result import InvestigatorConfig, InvestigatorRunResult
from .validation import parse_backend_output, validate_investigator_action


def latest_investigation_budget(case):
    """Use the latest audit or explicit controller budget-extension snapshot.

    A historical exhausted audit must not veto a later user-authorized extension;
    a subsequent Critic audit must still take precedence over that extension.
    """
    for event in reversed(case.investigation_history):
        extension = (event.actor == 'controller'
                     and event.metadata.get('controller_event') == 'USER_AUTHORIZED_BUDGET_EXTENSION'
                     and event.metadata.get('authorization', {}).get('user_instruction'))
        if event.action == 'FINAL_CRITIC_AUDIT_STARTED' or extension:
            budget = event.metadata.get('budget_state')
            if budget is not None:
                return budget
    return None


class EvidenceInvestigator:
    def __init__(self, backend=None, registry=None, config=None):
        self.backend = backend or MockInvestigatorBackend()
        self.registry = registry or EvidenceToolRegistry()
        self.config = InvestigatorConfig.model_validate((config or InvestigatorConfig()).model_dump(mode="json"))

    def run(self, store: CaseStore, case_id: str, *, run_id=None, artifact_dir=None):
        """Acquire against a detached state, validate, and commit using revision CAS.

        The backend only sees JSON. It never receives a store or tools. Repeated
        completed run IDs return the original audit artifact without another call.
        SQLite remains authoritative; exported files can be rebuilt from history.
        """
        run_id = TypeAdapter(Identifier).validate_python(run_id or new_id("INVESTIGATOR"))
        source = store.load_case(case_id)
        for event in reversed(source.investigation_history):
            if event.metadata.get("run_id") == run_id and event.metadata.get("run_artifact"):
                return InvestigatorRunResult.model_validate(event.metadata["run_artifact"])
        directory = Path(artifact_dir) if artifact_dir else (
            Path(store.path).resolve().parent / "investigator_runs" / run_id if store.path != ":memory:"
            else Path("outputs/evidence_investigator_runs") / run_id)
        directory = directory.resolve()
        path = directory / "investigator_run.json"
        base = dict(run_id=run_id, case_id=case_id, source_case_revision=source.metadata.case_revision,
                    artifact_path=str(path))
        selected, assessments, plans, calls, warnings = [], [], [], [], []
        recorder = None
        try:
            runtime_config = self.config
            budget = latest_investigation_budget(source)
            if budget:
                total_limit = budget["total_tool_calls"] + budget["tool_calls_remaining"]
                remaining = total_limit - count_evidence_tool_calls(source)
                round_limit = budget["investigator_rounds"] + budget["investigator_rounds_remaining"]
                rounds = agent_round_counts(source, 'investigator')[budget.get('round_budget_basis', 'started')]
                if remaining <= 0 or rounds >= round_limit:
                    raise ValueError("Critic investigation budget exhausted; final audit is required before further acquisition")
                runtime_config = self.config.model_copy(update={"max_tool_calls_per_run": min(
                    self.config.max_tool_calls_per_run, remaining)})
            if source.mechanistic_question is None or not source.hypotheses:
                raise ValueError("Investigator requires a Case File already populated by Explorer")
            if source.action_state.current_phase == "stopped":
                raise ValueError("Investigator cannot resume a stopped case")
            from jure.protocol.admission import investigation_first
            if investigation_first(source):
                if source.action_state.next_actor != 'investigator':
                    raise ValueError('Investigator requires the current Investigator route')
            elif self.config.protocol_v3:
                from jure.protocol.contracts import latest_revision_state,pending_submission
                request,checks=latest_revision_state(source)
                if pending_submission(source) or (request and not any(x['status']=='RESOLVED' for x in checks)):
                    raise ValueError('Revision requires Critic acceptance before evidence acquisition')
            started = record_event(store, source, "INVESTIGATOR_STARTED", run_id,
                                   source_case_revision=source.metadata.case_revision)
            with CaseStore() as stage:
                stage.import_case(started)
                recorder = InvestigationRecorder(stage, started, runtime_config, run_id)
                recorder.consume_critic_request()
                for duplicate, original in deduplicate_evidence_questions(started.evidence_questions):
                    question = next(q for q in recorder.case.evidence_questions if q.question_id == duplicate)
                    if question.status in SELECTABLE:
                        recorder.status(duplicate, "cancelled")
                        recorder.event("DUPLICATE_QUESTION_CANCELLED", object_type="evidence_question",
                                       object_id=duplicate, reason=f"duplicate_of:{original}")
                for _ in range(self.config.max_questions_per_run):
                    context = build_investigator_context(recorder.case, registry=self.registry,
                        source_aware_planning=self.config.source_aware_planning,
                        budget={"questions_remaining": self.config.max_questions_per_run - len(selected),
                                "tool_calls_remaining": runtime_config.max_tool_calls_per_run - len(calls),
                                "allow_counter_evidence_search": self.config.allow_counter_evidence_search})
                    context["pending_questions"] = [q for q in context["pending_questions"]
                                                    if q["question_id"] not in selected]
                    if not context["pending_questions"]:
                        break
                    priority = parse_backend_output(PrioritizationResult, self.backend.prioritize_questions(context))
                    available = {q["question_id"] for q in context["pending_questions"]}
                    ids = [a.question_id for a in priority.assessments]
                    if len(ids) != len(set(ids)):
                        raise ValueError("Duplicate priority assessment IDs")
                    assessments.extend(a.model_dump(mode="json") for a in priority.assessments)
                    for assessment in priority.assessments:
                        if assessment.question_id not in available:
                            recorder.event("NONSELECTABLE_PRIORITY_ANNOTATION", assessment=assessment.model_dump(mode="json"))
                            continue
                        recorder.event("QUESTION_PRIORITIZED", object_type="evidence_question",
                                       object_id=assessment.question_id, assessment=assessment.model_dump(mode="json"))
                    question_id = priority.selected_question_id
                    if question_id is None:
                        break
                    if question_id not in available:
                        raise ValueError("backend selected a question outside the pending queue")
                    selected.append(question_id)
                    question = next(q for q in recorder.case.evidence_questions if q.question_id == question_id)
                    validate_investigator_action(recorder.case, question_id=question_id)
                    focused = build_investigator_context(recorder.case, registry=self.registry,
                                                       source_aware_planning=self.config.source_aware_planning,
                                                       question_id=question_id, budget=context["action_budget"])
                    plan = parse_backend_output(QueryPlan, self.backend.operationalize_question(focused, question_id))
                    if self.config.protocol_v3 and plan.discrimination is None:
                        raise ValueError('Protocol v3 plan needs hypothesis-linked discrimination')
                    validate_investigator_action(recorder.case, question_id=question_id, plan=plan)
                    plans.append(plan.model_dump(mode="json"))
                    assessment = next(a for a in priority.assessments if a.question_id == question_id)
                    recorder.status(question_id, "selected")
                    recorder.event("QUESTION_SELECTED", object_type="evidence_question", object_id=question_id,
                                   priority_reason=assessment.priority_reason)
                    recorder.event("QUERY_PLAN_CREATED", object_type="evidence_question", object_id=question_id,
                                   query_plan=plan.model_dump(mode="json"))
                    if plan.discrimination and set(plan.discrimination.targets)-set(question.relevant_hypothesis_ids):
                        recorder.event("COMPARISON_SCOPE_EXPANDED", object_type="evidence_question", object_id=question_id,
                            original_targets=list(question.relevant_hypothesis_ids),
                            investigator_targets=list(plan.discrimination.targets),
                            plan_id=plan.plan_id, scientific_validity='For Critic audit')
                    recorder.status(question_id, "in_progress")
                    recorder.call("set_action_state", ActionState(current_phase="evidence_in_progress",
                                  next_actor="investigator", selected_question_id=question_id))
                    statuses = []
                    if not plan.planned_operations:
                        recorder.gap(question, "The question cannot be operationalized using the current tool capabilities and inputs.")
                    for operation in plan.planned_operations:
                        if self.config.source_aware_planning and not operation.evidence_planning:
                            warnings.append('Evidence planning was omitted; no rationale was supplied by software.')
                            recorder.event('EVIDENCE_PLANNING_MISSING', question_id=question_id,
                                           operation=operation.operation, plan_id=plan.plan_id)
                        if len(calls) >= runtime_config.max_tool_calls_per_run:
                            recorder.event("BUDGET_REACHED", limit=runtime_config.max_tool_calls_per_run,
                                           blocked_operation=operation.operation)
                            warnings.append("Tool-call budget reached; remaining plan steps were not executed.")
                            recorder.gap(question, "Tool-call budget was reached before the query plan completed.")
                            statuses.append("unresolved")
                            break
                        family = operation.evidence_type or plan.evidence_type
                        single_plan = plan.model_copy(update={"planned_operations": (operation,), "evidence_type": family})
                        # Refresh after each acquisition so tool selection sees completed
                        # prerequisites and current evidence, not the pre-plan snapshot.
                        focused = build_investigator_context(recorder.case, registry=self.registry,
                            source_aware_planning=self.config.source_aware_planning,
                            question_id=question_id, budget={**context["action_budget"],
                                "tool_calls_remaining": runtime_config.max_tool_calls_per_run - len(calls)})
                        focused["current_operation"] = operation.model_dump(mode="json")
                        focused["completed_tool_calls"] = list(calls)
                        selection = parse_backend_output(ToolSelection, self.backend.select_tool(focused, single_plan.model_dump(mode="json")))
                        if selection.tool_id is None:
                            recorder.gap(question, "No available tool can answer the current operational query.")
                            statuses.append("unresolved")
                            continue
                        tool = self.registry.get_tool(selection.tool_id)
                        if tool is None:
                            raise ValueError("backend selected an unregistered tool")
                        validate_investigator_action(recorder.case, question_id=question_id, plan=single_plan,
                            tool=tool, operation=operation, tool_calls=len(calls),
                            max_tool_calls=runtime_config.max_tool_calls_per_run)
                        inputs = operation.inputs.to_dict()
                        if family == "dataset" and not getattr(self.registry, "native_envelopes", False):
                            inputs["min_conditional_support"] = max(
                                self.config.min_conditional_support, inputs.get("min_conditional_support", 0))
                        recorder.event("TOOL_SELECTED", object_type="evidence_question", object_id=question_id,
                                       tool_id=selection.tool_id, reason=selection.reason)
                        recorder.event("TOOL_CALL_STARTED", object_type="evidence_question", object_id=question_id,
                                       tool_id=selection.tool_id, operation=operation.operation, inputs=inputs)
                        calls.append({"tool_id": selection.tool_id, "operation": operation.operation,
                            "question_id": question_id, "parameters": inputs, "status": "failed",
                            "failure_reason": "Acquisition did not complete or persist its raw artifact.",
                            "raw_result_reference": None})
                        if hasattr(self.registry, "set_context"):
                            self.registry.set_context(question_id=question_id, stage="INVESTIGATOR_ACQUISITION")
                        result = self.registry.execute(selection.tool_id, operation.operation, inputs)
                        raw = save_raw_result(result, directory, run_id)
                        call = {"tool_id": result.tool_id, "tool_version": result.tool_version,
                                "operation": result.operation, "question_id": question_id,
                                "parameters": result.parameters.to_dict(), "status": result.status,
                                "failure_reason": result.failure_reason, "raw_result_reference": raw.raw_result_reference,
                                "started_at": result.started_at.isoformat(), "completed_at": result.completed_at.isoformat()}
                        calls[-1] = call
                        recorder.event("TOOL_CALL_FAILED" if result.status == "failed" else "TOOL_CALL_COMPLETED",
                                       object_type="evidence_question", object_id=question_id, **{k: v for k, v in call.items() if k != "question_id"})
                        interpretation = parse_backend_output(ToolInterpretation, self.backend.interpret_tool_result(
                            focused, single_plan.model_dump(mode="json"), result.model_dump(mode="json")))
                        warnings.extend(interpretation.warnings)
                        if self.config.protocol_v3:
                            if interpretation.information_update is None:raise ValueError('Protocol v3 requires an information update')
                            recorder.event('DISCRIMINATION_PROGRESS_RECORDED',question_id=question_id,
                                plan_id=plan.plan_id,tool_query=call,
                                comparison=plan.discrimination.model_dump(mode='json'),
                                information_update=interpretation.information_update.model_dump(mode='json'),
                                status_scope='Investigator advisory progress, not a Critic evidence verdict')
                        normalizer = getattr(self.registry, "normalize_result", normalize_tool_result)
                        normalized = normalizer(question, result, raw, recorder.case,
                                                self.config, run_id, family)
                        # Preserve Agent-authored intent beside source facts, never as a verdict.
                        if operation.evidence_planning:
                            from jure.casefile.models import FrozenJSON
                            normalized.records = [e.model_copy(update={'provenance':
                                e.provenance.model_copy(update={'parameters': FrozenJSON({
                                    **e.provenance.parameters.to_dict(),
                                    'investigator_evidence_planning': operation.evidence_planning.to_dict(),
                                    'planning_scope': 'Agent-authored rationale, not source evidence or Critic verdict',
                                })})}) for e in normalized.records]
                        recorder.record(question, normalized)
                        if interpretation.possible_gap and not normalized.gap:
                            recorder.gap(question, interpretation.possible_gap)
                        statuses.append(normalized.question_status)
                    final_status = self._question_status(statuses)
                    recorder.status(question_id, final_status)
                    if len(calls) >= runtime_config.max_tool_calls_per_run:
                        if not any(e.action == "BUDGET_REACHED" and e.metadata.get("run_id") == run_id
                                   for e in recorder.case.investigation_history):
                            recorder.event("BUDGET_REACHED", limit=runtime_config.max_tool_calls_per_run)
                        break
                recorder.call("set_action_state", ActionState(current_phase="critique_needed", next_actor="critic"))
                final_status = next((q.status for q in recorder.case.evidence_questions
                                     if selected and q.question_id == selected[0]), None)
                result = InvestigatorRunResult(**base, success=True,
                    selected_question_id=selected[0] if selected else None, selected_question_ids=tuple(selected),
                    priority_assessment=tuple(assessments), query_plan_id=plans[0]["plan_id"] if plans else None,
                    query_plans=tuple(plans), tool_calls=tuple(calls), created_evidence_ids=tuple(recorder.evidence_ids),
                    linked_evidence_ids=tuple(recorder.linked_ids), created_gap_ids=tuple(recorder.gap_ids),
                    created_followup_question_ids=tuple(recorder.followup_ids), question_final_status=final_status,
                    question_final_statuses={q.question_id: q.status for q in recorder.case.evidence_questions
                                             if q.question_id in selected},
                    warnings=tuple(warnings), committed_case_revision=recorder.case.metadata.case_revision + 1)
                recorder.event("INVESTIGATOR_COMPLETED", run_artifact=result.model_dump(mode="json"))
                validate_investigator_action(recorder.case, before=source)
                store.commit_investigator_case(case_id, recorder.case, expected_revision=started.metadata.case_revision)
        except Exception as error:
            # The entire staged update is discarded. Raw acquisitions remain
            # referenced in this failure artifact for inspection, never as evidence.
            result = InvestigatorRunResult(**base, selected_question_id=selected[0] if selected else None,
                selected_question_ids=tuple(selected), priority_assessment=tuple(assessments),
                query_plan_id=plans[0]["plan_id"] if plans else None, query_plans=tuple(plans),
                tool_calls=tuple(calls), warnings=tuple(warnings),
                validation_errors=(f"{type(error).__name__}: {str(error)[:2000]}",))
            try:
                latest = store.load_case(case_id)
                record_event(store, latest, "INVESTIGATOR_FAILED", run_id, run_artifact=result.model_dump(mode="json"))
            except Exception as audit_error:
                result = result.model_copy(update={"warnings": result.warnings +
                    (f"Failure audit unavailable: {type(audit_error).__name__}",)})
        try:
            _atomic_write(path, result.model_dump_json(indent=2) + "\n")
        except OSError as error:
            result = result.model_copy(update={"warnings": result.warnings +
                (f"Artifact export failed ({type(error).__name__}); use the SQLite run artifact.",)})
        return result

    @staticmethod
    def _question_status(statuses):
        if not statuses:
            return "unresolved"
        if all(status == "answered" for status in statuses):
            return "answered"
        if any(status in {"answered", "partially_answered"} for status in statuses):
            return "partially_answered"
        if all(status == "pending" for status in statuses):
            return "pending"
        return "unresolved"
