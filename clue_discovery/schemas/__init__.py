"""Versioned, condition-oriented contracts; no statistical engine or Agent imports."""
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = '1.0'
METHOD_VERSION = 'clue_discovery_three_stage_v1'

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class EvidenceLevel(str, Enum):
    REFERENCE_PATTERN = 'REFERENCE_PATTERN'
    EXPLORATORY_ASSOCIATION = 'EXPLORATORY_ASSOCIATION'
    EXTERNALLY_VALIDATED_ASSOCIATION = 'EXTERNALLY_VALIDATED_ASSOCIATION'
    MECHANISTICALLY_INVESTIGATED = 'MECHANISTICALLY_INVESTIGATED'

class SignedState(Contract):
    genes: list[str]
    states: list[Literal[0, 1]]
    order: int = Field(ge=1)

    @model_validator(mode='after')
    def validate_identity(self):
        if len(self.genes) != self.order or len(self.states) != self.order or len(set(self.genes)) != self.order:
            raise ValueError('signed state requires unique genes and one state per gene')
        if any(not g.strip() for g in self.genes):
            raise ValueError('empty gene identifier')
        return self

    @property
    def signed_pattern(self):
        return ' '.join(g + ('+' if s else '-') for g, s in zip(self.genes, self.states))

class ReferenceState(SignedState):
    dataset_id: str
    reference_id: str
    reference_population: dict[str, Any]
    reference_prevalence: float | None = Field(default=None, ge=0, le=1)
    mfi_evidence: dict[str, Any] = Field(default_factory=dict)
    gain_evidence: dict[str, Any] = Field(default_factory=dict)
    estimability: dict[str, Any] = Field(default_factory=dict)
    bootstrap_stability: dict[str, Any] = Field(default_factory=dict)
    crossfold_evidence: dict[str, Any] = Field(default_factory=dict)
    qualification: dict[str, Any] = Field(default_factory=dict)
    evidence_level: Literal[EvidenceLevel.REFERENCE_PATTERN] = EvidenceLevel.REFERENCE_PATTERN
    provenance: dict[str, Any]

class ReferenceCatalogue(Contract):
    schema_version: str = SCHEMA_VERSION
    dataset_id: str
    records: list[ReferenceState]
    compatibility: dict[str, Any]
    provenance: dict[str, Any]

    @model_validator(mode='after')
    def unique_references(self):
        if len({x.reference_id for x in self.records}) != len(self.records):
            raise ValueError('duplicate reference_id')
        if any(x.dataset_id != self.dataset_id for x in self.records):
            raise ValueError('mixed source datasets in catalogue')
        return self

class ConditionAssociation(SignedState):
    candidate_id: str
    dataset_id: str
    condition_id: str
    perturbation_target: str | None = None
    condition_type: str
    reference_id: str
    matched_effect: float
    effect_units: Literal['prevalence_difference'] = 'prevalence_difference'
    direction: Literal['enrichment', 'depletion']
    condition_support: dict[str, Any]
    control_support: dict[str, Any]
    association_evidence: dict[str, Any]
    evidence_level: EvidenceLevel = EvidenceLevel.EXPLORATORY_ASSOCIATION
    external_validation_status: str = 'NOT_PERFORMED'
    quality_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any]

    @model_validator(mode='after')
    def directional_evidence(self):
        if not -1 <= self.matched_effect <= 1 or self.matched_effect == 0:
            raise ValueError('association requires nonzero prevalence difference in [-1,1]')
        if (self.matched_effect > 0) != (self.direction == 'enrichment'):
            raise ValueError('effect/direction conflict')
        if self.evidence_level == EvidenceLevel.REFERENCE_PATTERN:
            raise ValueError('reference evidence alone is not an association')
        if self.evidence_level == EvidenceLevel.EXTERNALLY_VALIDATED_ASSOCIATION and self.external_validation_status != 'VALIDATED':
            raise ValueError('external validation evidence required')
        return self

class ResponseGroup(Contract):
    group_id: str
    reference_ids: list[str]
    signed_states: list[SignedState]
    representative_reference_id: str
    stable_core: list[str]
    boundary_members: list[str]
    candidate_count: int = Field(ge=0)
    condition_count: int = Field(ge=0)
    direction_summary: dict[str, Any]
    within_group_similarity: float | None
    stability: dict[str, Any]
    sensitivity: list[dict[str, Any]] = Field(default_factory=list)
    activity_definition: str
    annotation_status: Literal['NOT_ANNOTATED'] = 'NOT_ANNOTATED'
    evidence_scope: str = 'descriptive_shared_response_structure; not_a_biological_program'

    @model_validator(mode='after')
    def membership(self):
        refs=set(self.reference_ids)
        if len(refs)!=len(self.reference_ids) or len(refs)!=len(self.signed_states) or self.representative_reference_id not in refs:
            raise ValueError('invalid group membership/representative')
        if set(self.stable_core)&set(self.boundary_members) or set(self.stable_core)|set(self.boundary_members)!=refs:
            raise ValueError('core and boundary must partition group')
        return self

class CoResponseRelation(Contract):
    relation_id: str
    reference_a: str
    reference_b: str
    relation_type: Literal['GENE_DISJOINT_CORESPONSE', 'OVERLAPPING_GENE_CORESPONSE', 'SIGNED_STATE_CONTRAST']
    shared_genes: list[str]
    gene_jaccard: float = Field(ge=0, le=1)
    pearson_r: float | None = Field(ge=-1, le=1)
    spearman_rho: float | None = Field(ge=-1, le=1)
    shared_candidate_conditions: list[str]
    direction_concordance: float | None = Field(ge=0, le=1)
    evaluable_condition_count: int
    scope: str = 'descriptive_condition_profile_association; not_regulation'
    provenance: dict[str, Any] = Field(default_factory=dict)

class ConditionProfile(Contract):
    condition_id: str
    condition_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    condition_cell_count: int | None = Field(default=None, ge=0)
    candidate_count: int = Field(ge=0)
    enrichment_count: int = Field(ge=0)
    depletion_count: int = Field(ge=0)
    response_group_ids: list[str]
    activity: dict[str, float | None]
    sample_size_context: dict[str, Any]
    quality_flags: list[str] = Field(default_factory=list)

class TriageInput(SignedState):
    schema_version: str = SCHEMA_VERSION
    case_id: str
    dataset_id: str
    condition_id: str
    candidate_id: str
    reference_id: str
    matched_effect: float
    effect_units: Literal['prevalence_difference'] = 'prevalence_difference'
    reference_evidence: dict[str, Any]
    association_evidence: dict[str, Any]
    group_context: dict[str, Any]
    stable_core_context: dict[str, Any]
    coresponse_context: list[str]
    signed_state_contrast_context: list[str]
    support: dict[str, Any]
    sample_size_context: dict[str, Any]
    external_validation_status: str
    evidence_level: EvidenceLevel
    strata: list[str]
    sampling_block_id: str
    provenance: dict[str, Any]

class SelectedCase(Contract):
    """Explicit downstream selection. A group alone cannot instantiate a case."""
    case: TriageInput
    selection_method: Literal['human', 'rule', 'model']
    selection_reason: str = Field(min_length=1)
    selector: str = Field(min_length=1)
    selected_at: str
    selection_provenance: dict[str, Any]

class StructuredClueLandscape(Contract):
    schema_version: str = SCHEMA_VERSION
    method_version: str = METHOD_VERSION
    dataset_id: str
    reference_catalogue_version: str = 'v04_validation_family_holm'
    perturbation_scan_version: str = 'perturbation_scan_v01'
    landscape_version: str = 'broad_screening_v01'
    evidence_scope: dict[str, Any]
    annotation_inputs: list[dict[str, Any]] = Field(default_factory=list)
    response_groups: list[ResponseGroup]
    condition_profiles: list[ConditionProfile]
    reference_state_profiles: list[dict[str, Any]]
    stable_cores: dict[str, list[str]]
    boundary_members: dict[str, list[str]]
    coresponse_relations: list[CoResponseRelation]
    signed_state_contrasts: list[CoResponseRelation]
    case_strata: dict[str, list[str]]
    sampling_blocks: dict[str, list[str]]
    quality_audits: dict[str, Any]
    triage_inputs: list[TriageInput]
    provenance: dict[str, Any]

    @model_validator(mode='after')
    def consistent_context(self):
        gids={g.group_id for g in self.response_groups}
        if len(gids)!=len(self.response_groups): raise ValueError('duplicate group id')
        if len({x.case_id for x in self.triage_inputs})!=len(self.triage_inputs): raise ValueError('duplicate case id')
        if any(x.dataset_id!=self.dataset_id for x in self.triage_inputs): raise ValueError('mixed dataset cases')
        return self

class LandscapeAlignmentRequest(Contract):
    source_landscape: str
    target_landscape: str
    gene_mapping: dict[str, str]
    reference_state_matching: Literal['exact_signed_state'] = 'exact_signed_state'
    compatibility_audit: dict[str, Any]

class LandscapeAlignmentResult(Contract):
    request: LandscapeAlignmentRequest
    group_matches: list[dict[str, Any]]
    unmatched_source: list[str]
    unmatched_target: list[str]
    evidence_scope: str = 'descriptive_alignment_does_not_validate_associations'

def align_landscapes(request: LandscapeAlignmentRequest) -> LandscapeAlignmentResult:
    raise NotImplementedError('Reserved interface: no cross-dataset alignment was performed')
