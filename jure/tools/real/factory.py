"""Assemble one registry; registration does not decide tool order or run Agents."""
import json
from pathlib import Path
from jure.casefile.store import CaseStore,load_case
from triage.pilot_sources import VerifiedPilotSource
from jure.integrations.http import PublicHTTP
from jure.integrations.harmonizome import GeneKnowledgeTool
from jure.integrations.pubmed import LiteratureTool
from jure.integrations.primekg import KnowledgeGraphTool
from .contracts import *
from .registry import ToolRegistry,ToolSpec,digest,file_sha
from .local_tools import CaseFileTool,ClueQueryTool
from .experiment import DataExperimentTool,CellStateStore,FrozenCountsStore,DATASET
from .entities import GeneResolver

class TNStub:
    def execute(self,q,ctx):return Outcome(Status.NOT_IMPLEMENTED,error={'code':'TN_NOT_IMPLEMENTED','message':'TN query is a reserved interface only'})

def build_registry(root,*,run_id,case_store=None,cell_store='data/day6_tool_store',
        clue_root='outputs/integration_tests/adapter_smoke/replogle_frozen',
        gene_mapping='data/evidence_sources/hgnc_complete_set.txt',kg_index='data/evidence_sources/primekg.sqlite',
        allow_frozen_counts=True,mode='REAL',budgets=None,disabled_tools=()):
    registry=ToolRegistry(root,run_id=run_id,mode=mode,budgets=budgets,disabled_tools=disabled_tools)
    store=case_store or CaseStore(Path(root)/'validation_cases.sqlite')
    source=VerifiedPilotSource(clue_root)
    http=PublicHTTP(Path(root)/'source_responses',timeout=45,retries=1)
    resolver=GeneResolver(gene_mapping) if Path(gene_mapping).exists() else None
    if Path(cell_store,'manifest.json').exists():
        data=CellStateStore(cell_store);data_availability='READY'
    elif allow_frozen_counts:
        data=FrozenCountsStore('outputs/perturbation_scan_day6_v01_20260927/remote/outputs/day6_scan/counts',
            {'counts.npz':'47a3a71534e2a80d3ceee07d91930058eb52031eb7f0f264ca17b28985b8d52d',
             'identities.json':'ba58b20872f1d09a966cf77cb35f08607dd33f0f3b42392810fc796f0582274a'})
        data_availability='PARTIAL'
    else:data=None;data_availability='UNAVAILABLE'
    kg=KnowledgeGraphTool(kg_index)
    definitions=[
        ToolSpec('case_file','Read Case File sections and append revisioned role-owned records.',CaseQuery,CaseFileTool(store),ROLES,
            'JURE CaseStore','casefile-0.1.1','BACKGROUND_SOURCE','READY',
            examples=[{'operation':'read_case','case_id':'<bound case id>'}],when_to_use='Read shared state or persist your role-owned output.',when_not_to_use='Do not rewrite snapshots or impersonate another role.'),
        ToolSpec('clue_query','Inspect frozen reference, shift and landscape facts.',ClueQuery,ClueQueryTool(source),ROLES,
            'Frozen Day6 reference and landscape',digest(source.checked),'PRIMARY_EXPERIMENTAL_DATA','READY',DATASET,
            examples=[{'operation':'get_condition_association','condition':'TIMM23B','genes':['DDIT4','PHGDH','RGS16'],'states':[1,1,1]}],
            when_to_use='Inspect existing clue facts, support and related frozen states.',when_not_to_use='Not a new experiment or a mechanism search.'),
        ToolSpec('data_experiment','Query real Day6 measured signed states with matched controls.',ExperimentQuery,DataExperimentTool(data,resolver),('investigator','critic'),
            'Replogle K562 essential Day6',data.version if data else 'UNAVAILABLE','PRIMARY_EXPERIMENTAL_DATA',data_availability,DATASET,
            examples=[{'mode':'JOINT_STATE','condition':'TIMM23B','state':{'DDIT4':1,'PHGDH':1,'RGS16':1}}],
            when_to_use='Measure a specified signed-state probability/association in the canonical experiment.',when_not_to_use='Not a discovery scan, biological replication or causal proof.'),
        ToolSpec('knowledge_graph','Look up typed entities, edges and bounded directed paths.',GraphQuery,kg,('investigator','critic'),
            'PrimeKG',kg.version,'CURATED_KNOWLEDGE_GRAPH','READY' if kg.db else 'UNAVAILABLE',
            examples=[{'operation':'query_entity','entity':'DDIT4'},{'operation':'find_paths','entity':'DDIT4','target':'MTOR','max_hops':2}],
            when_to_use='Check whether curated relations or bounded paths exist.',when_not_to_use='Do not infer unrecorded edges or treat a path as case-specific mechanism.'),
        ToolSpec('gene_knowledge','Resolve human gene identity and retrieve source annotations/gene sets.',GeneQuery,GeneKnowledgeTool(http,resolver),('investigator','critic'),
            'HGNC + Harmonizome API 1.0','api1.0;snapshot:'+run_id+';hgnc:'+resolver.version if resolver else 'UNAVAILABLE','CURATED_GENESET_DATABASE','CONFIGURED' if resolver else 'UNAVAILABLE',
            examples=[{'operation':'get_gene_info','gene':'DDIT4'}],
            when_to_use='Inspect gene identity, annotations or membership in source gene sets.',when_not_to_use='Not a perturbation-specific effect or an independent confirmation.'),
        ToolSpec('literature','Search PubMed and retrieve verifiable abstracts; passage validation is partial.',LiteratureQuery,LiteratureTool(http),('investigator','critic'),
            'NCBI PubMed E-utilities','esearch0.3/efetch-xml;snapshot:'+run_id,'BACKGROUND_SOURCE','CONFIGURED',
            examples=[{'operation':'search','entities':['DDIT4'],'limit':3},{'operation':'retrieve','pmids':['35688146']}],
            limitations=['No validated automatic claim extractor; search/retrieval only plus exact passage checking.'],
            when_to_use='Find and inspect original paper records relevant to an Agent-authored question.',when_not_to_use='A search hit or abstract alone does not establish experimental design or claim support.'),
        ToolSpec('tn_query','Reserved TN interface; no backend.',TNQuery,TNStub(),('investigator','critic'),
            'not configured','NOT_IMPLEMENTED','COMPUTATIONAL_PREDICTION','NOT_IMPLEMENTED',
            examples=[{'operation':'query','query':{}}],when_to_use='Future integration only.',when_not_to_use='Unavailable in v0.1.')]
    for spec in definitions:registry.register(spec)
    return registry
