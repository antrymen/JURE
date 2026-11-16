"""Tool validation only. Synthetic fixtures never enter production evidence."""
import json,sqlite3,subprocess,sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError
from jure.tools.real.contracts import *
from jure.tools.real.registry import ToolRegistry,ToolSpec,file_sha
from jure.tools.real.experiment import CellStateStore,DataExperimentTool,matched_comparison,DATASET
from jure.tools.real.local_tools import CaseFileTool
from jure.tools.real.entities import GeneResolver
from jure.tools.real.independence import build_source_graph
from jure.integrations.pubmed import LiteratureTool,parse_articles
from jure.integrations.primekg import import_primekg,KnowledgeGraphTool
from jure.casefile.store import CaseStore,load_case

class FixtureBackend:
    source_mode='TEST'
    def __init__(self):self.calls=0
    def execute(self,q,ctx):
        self.calls+=1
        return Outcome(result={'calls':self.calls},record_ids=['dataset:fixture'],provenance={'upstream_source_ids':['dataset:fixture']})

def registry(tmp_path,backend=None,**kwargs):
    r=ToolRegistry(tmp_path,run_id='unit',mode='TEST',**kwargs);b=backend or FixtureBackend()
    r.register(ToolSpec('fixture','unit only',GeneQuery,b,('investigator','critic'),'fixture','1','BACKGROUND_SOURCE','READY'))
    return r,b

def context(actor='investigator',**kwargs):
    return CallContext(case_id='TEST_ONLY',actor=actor,stage='unit',purpose='TOOL_VALIDATION',**kwargs)

Q={'operation':'get_gene_info','gene':'A'}

def test_cache_trace_force_and_version_invalidation(tmp_path):
    r,b=registry(tmp_path)
    first=r.execute('fixture',Q,context());second=r.execute('fixture',Q,context())
    assert first.status==second.status==Status.OK and b.calls==1
    assert second.cache['cache_hit'] and first.timestamp==second.timestamp
    force=r.execute('fixture',Q,context('critic',force_requery=True,requery_reason='independent acquisition check'))
    assert b.calls==2 and not force.cache['cache_hit'] and force.provenance['source_executed']
    assert not force.independence['independent_confirmation']
    r.specs['fixture'].source_version='2';r.execute('fixture',Q,context());assert b.calls==3
    assert r.export_traces(tmp_path/'traces.jsonl')==4
    graph=build_source_graph([first,second,force]);assert any(e['type']=='REUSES_DATA' for e in graph['edges'])

def test_force_reason_schema_and_role_guard(tmp_path):
    r,b=registry(tmp_path)
    with pytest.raises(ValidationError): context(force_requery=True)
    assert r.execute('fixture',Q,context('explorer')).status==Status.INVALID_QUERY
    assert r.execute('fixture',{**Q,'surprise':1},context()).status==Status.INVALID_QUERY
    assert r.execute('not_registered',Q,context()).status==Status.INVALID_QUERY
    assert b.calls==0

def test_budget_persists_restart_and_disable(tmp_path):
    r,b=registry(tmp_path,budgets={'total':1})
    r.execute('fixture',Q,context());assert r.execute('fixture',Q,context()).status==Status.BUDGET_EXHAUSTED
    r2,_=registry(tmp_path,budgets={'total':1});assert r2.execute('fixture',Q,context()).status==Status.BUDGET_EXHAUSTED
    r3,_=registry(tmp_path/'disabled',disabled_tools=['fixture']);assert r3.execute('fixture',Q,context()).status==Status.UNAVAILABLE

def test_real_rejects_test_backend_and_no_automatic_mock_import(tmp_path):
    r=ToolRegistry(tmp_path,run_id='prod')
    with pytest.raises(ValueError):r.register(ToolSpec('fixture','unit',GeneQuery,FixtureBackend(),('investigator',),'fixture','1','BACKGROUND_SOURCE','READY'))
    code="import jure.tools.real.factory,sys; assert 'jure.tools.evidence.mock' not in sys.modules"
    subprocess.run([sys.executable,'-c',code],check=True)

@pytest.fixture
def cells(tmp_path):
    # Two batches with opposing NT frequencies and unequal perturbation weights:
    # NT pooled=.5; matched=(3/4)*.25+(1/4)*.75=.375.
    values=[];meta=[]
    for condition,batch,n,a_hits in [('non-targeting','b1',8,2),('non-targeting','b2',8,6),('KO','b1',6,3),('KO','b2',2,2),('KO2','b1',4,1),('KO2','b2',4,3)]:
        for i in range(n):
            values.append([int(i<a_hits),i%2,1]);meta.append({'cell_id':f'{condition}:{batch}:{i}','source_row':len(meta),'scan_target':condition,'batch':batch})
    np.save(tmp_path/'states.npy',np.packbits(np.array(values,dtype=np.uint8),axis=1))
    pd.DataFrame(meta).to_csv(tmp_path/'cells.csv.gz',index=False);(tmp_path/'genes.json').write_text(json.dumps(['A','B','C']))
    m={'dataset_id':DATASET,'encoding':'raw_count_gt_0','source_mode':'TEST','files':{n:file_sha(tmp_path/n) for n in ('states.npy','cells.csv.gz','genes.json')}}
    (tmp_path/'manifest.json').write_text(json.dumps(m));return CellStateStore(tmp_path)

def exquery(mode='MARGINAL',state=None,**kwargs):
    return ExperimentQuery(mode=mode,condition='KO',state=state or {'A':1},min_condition_cells=1,min_nt_per_batch=1,min_effective_nt=1,min_events=1,**kwargs)

def test_independent_matched_counts_not_pooled(cells):
    result=DataExperimentTool(cells).execute(exquery(),context()).result['statistics']
    assert result['condition_hits']==5 and result['condition_n']==8
    assert result['matched_nt_frequency']==pytest.approx(.375)
    assert result['pooled_nt_frequency_descriptive']==.5
    assert result['delta']==pytest.approx(.25)
    assert result['matched_nt_effective_n']==pytest.approx(12.8)
    assert result['batch_support'][0]['condition_cell_set_id']

def test_pairwise_table_and_conditional_denominators(cells):
    tool=DataExperimentTool(cells)
    pair=tool.execute(exquery('PAIRWISE',{'A':1,'B':1}),context()).result['statistics']
    assert sum(pair['contingency_counts'])==8
    assert np.sum(pair['matched_nt_cell_probabilities'])==pytest.approx(1)
    cond=tool.execute(exquery('CONDITIONAL',conditioning_states={'B':1}),context()).result['statistics']
    assert cond['condition_n']==4 and cond['condition_hits']==2
    assert cond['conditional']
    with pytest.raises(ToolFailure) as exc:tool.execute(exquery('CONDITIONAL',conditioning_states={'C':0}),context())
    assert exc.value.code=='ZERO_DENOMINATOR'

def test_joint_state_contrast_comparison_and_missing(cells):
    tool=DataExperimentTool(cells)
    joint=tool.execute(exquery('JOINT_STATE',{'A':1,'B':1,'C':1}),context()).result['statistics']
    assert joint['condition_hits']==2
    contrast=tool.execute(exquery('STATE_CONTRAST',contrast_state={'A':0}),context()).result['statistics']
    assert contrast['state_a']['delta']==pytest.approx(-contrast['state_b']['delta'])
    comparison=tool.execute(exquery('CONDITION_COMPARISON',condition_b='KO2'),context()).result['statistics']
    assert comparison['comparable_batches'] and comparison['common_population_delta'] is not None
    with pytest.raises(ToolFailure):tool.execute(exquery(state={'UNMEASURED':1}),context())
    q=exquery().model_copy(update={'min_condition_cells':100})
    assert tool.execute(q,context()).status==Status.INSUFFICIENT_SUPPORT

@pytest.mark.parametrize('kwargs',[{'mode':'MARGINAL','state':{'A':1,'B':0}},{'mode':'PAIRWISE','state':{'A':1}},
    {'mode':'CONDITIONAL','state':{'A':1},'conditioning_states':{'A':0}},
    {'mode':'STATE_CONTRAST','state':{'A':1},'contrast_state':{'B':0}},
    {'mode':'JOINT_STATE','state':{'A':True}}])
def test_invalid_statistical_queries(kwargs):
    with pytest.raises(ValidationError):ExperimentQuery(condition='KO',**kwargs)

def test_corrupt_store_rejected(cells):
    (cells.root/'genes.json').write_text('["CORRUPTED"]')
    with pytest.raises(ValueError):CellStateStore(cells.root)

def test_missing_control_is_not_zero(cells):
    q=exquery()
    with pytest.raises(ToolFailure) as exc:matched_comparison([{'batch':'missing','n':10,'hits':2,'cell_set_id':'a'}],[],q)
    assert exc.value.code=='MISSING_MATCHED_NT'

XML=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>A <i>gene</i> title</ArticleTitle><Journal><Title>J</Title><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal><Abstract><AbstractText Label="RESULTS">Measured response.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.test/a</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''
class XMLFixture:
    def get(self,url):return XML,{'sha256':'test-only','url':url}

def test_literature_retrieval_and_extraction_never_fabricate_support():
    tool=LiteratureTool(XMLFixture());q=LiteratureQuery(operation='retrieve',pmids=['123'])
    result=tool.execute(q,context());paper=result.result['articles'][0]
    assert paper['pmid']=='123' and paper['title']=='A gene title' and paper['doi']=='10.test/a'
    assert paper['abstract_sections'][0]['location']=='PubMed:123:Abstract:1'
    e=tool.execute(LiteratureQuery(operation='extract_evidence',pmids=['123'],claim='Fixture only',passages=[{'pmid':'123','verbatim_passage':'Measured response.'}]),context())
    assert e.status==Status.NOT_EVALUABLE and e.result['verified_passages'][0]['classification'] is None
    with pytest.raises(ToolFailure):tool.execute(LiteratureQuery(operation='retrieve',pmids=['999']),context())

def test_hgnc_ambiguity_and_ensembl(tmp_path):
    p=tmp_path/'hgnc.tsv';p.write_text('symbol\tstatus\thgnc_id\tensembl_gene_id\talias_symbol\tprev_symbol\nA\tApproved\tHGNC:1\tENSG1\tOLD|AMB\t\nB\tApproved\tHGNC:2\tENSG2\tAMB\t\n')
    r=GeneResolver(p);assert r.resolve('ENSG1')['symbol']=='A';assert r.resolve('OLD')['symbol']=='A'
    with pytest.raises(ToolFailure) as e:r.resolve('AMB')
    assert e.value.status==Status.AMBIGUOUS_ENTITY

@pytest.fixture
def kg(tmp_path):
    p=tmp_path/'kg.csv';p.write_text('relation,x_index,x_id,x_type,x_name,x_source,y_index,y_id,y_type,y_name,y_source\nppi,1,1,gene,A,fixture,2,2,gene,B,fixture\nregulates,2,2,gene,B,fixture,3,3,gene,C,fixture\nppi,3,3,gene,C,fixture,1,1,gene,A,fixture\n')
    import_primekg(p,tmp_path/'kg.sqlite',{'source_mode':'TEST'})
    return KnowledgeGraphTool(tmp_path/'kg.sqlite')

def test_kg_direction_types_limits_and_no_path(kg):
    direct=kg.execute(GraphQuery(operation='query_edge',entity='A',target='B'),context());assert direct.status==Status.OK
    missing=kg.execute(GraphQuery(operation='query_edge',entity='B',target='A'),context());assert missing.status==Status.NO_RESULT
    paths=kg.execute(GraphQuery(operation='find_paths',entity='A',target='C',max_hops=2),context())
    assert paths.result['paths'][0]['node_ids']==['1','2','3']
    filtered=kg.execute(GraphQuery(operation='find_paths',entity='A',target='C',relation_types=['ppi']),context())
    assert filtered.status==Status.NO_RESULT
    limited=kg.execute(GraphQuery(operation='local_subgraph',entity='A',max_nodes=1),context());assert limited.status==Status.TRUNCATED
    assert direct.result['edges'][0]['confidence'] is None


def test_case_commands_permissions_revisions_no_real_case_mutation(tmp_path):
    store=CaseStore(tmp_path/'cases.sqlite');case=load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json');store.import_case(case)
    tool=CaseFileTool(store);r=ToolRegistry(tmp_path/'tools',run_id='unit',mode='TEST')
    r.register(ToolSpec('case_file','case',CaseQuery,tool,('explorer','investigator','critic'),'case','1','BACKGROUND_SOURCE','READY'))
    client=r.bind('investigator',case.metadata.case_id,stage='unit',purpose='TOOL_VALIDATION')
    def call(operation,**kw):return client.call('case_file',dict(operation=operation,case_id=case.metadata.case_id,**kw))
    assert call('read_case').status==Status.OK
    assert call('get_evidence').result['evidence_records']==[]
    assert call('get_hypotheses').result['hypotheses']==[]
    assert call('get_audits').status==Status.OK
    assert call('append_record',record_type='hypothesis',record={},expected_revision=1).status==Status.INVALID_QUERY
    added=call('append_record',record_type='evidence_gap',record={'description':'Infrastructure test only'},expected_revision=1)
    assert added.status==Status.OK and added.result['case_revision']==2
    stale=call('append_record',record_type='evidence_gap',record={'description':'Stale'},expected_revision=1)
    assert stale.status==Status.INVALID_QUERY
    assert store.load_case(case.metadata.case_id).metadata.case_revision==2
    assert load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json').metadata.case_revision==1


def test_mock_envelope_cannot_be_written_in_production(tmp_path):
    test,b=registry(tmp_path/'shared');env=test.execute('fixture',Q,context())
    real=ToolRegistry(tmp_path/'shared',run_id='real',mode='REAL');tool=CaseFileTool(None);tool.bind_registry(real)
    with pytest.raises(PermissionError):tool.prepare_evidence({},env.query_id,context())


def test_failure_no_cache_and_error_trace(tmp_path):
    class Failure(FixtureBackend):
        def execute(self,q,ctx):
            self.calls+=1
            raise ToolFailure(Status.SOURCE_ERROR,'SOURCE_OFFLINE','Fixture offline')
    r,b=registry(tmp_path,Failure());a=r.execute('fixture',Q,context());c=r.execute('fixture',Q,context())
    assert a.status==c.status==Status.SOURCE_ERROR and b.calls==2
    assert not c.cache['cache_hit'] and r.gap_for(a)['reason']=='SOURCE_OFFLINE'


def test_cell_fixture_cannot_register_as_real(tmp_path,cells):
    real=ToolRegistry(tmp_path/'real',run_id='prod')
    with pytest.raises(ValueError):
        real.register(ToolSpec('data_experiment','data',ExperimentQuery,DataExperimentTool(cells),('investigator',),'fixture','1','PRIMARY_EXPERIMENTAL_DATA','READY'))


def test_queue_write_and_explicit_evidence_source_mapping(tmp_path,cells):
    store=CaseStore(tmp_path/'case.sqlite')
    original=load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')
    store.import_case(original);cid=original.metadata.case_id
    reg=ToolRegistry(tmp_path/'runtime',run_id='unit',mode='TEST')
    reg.register(ToolSpec('case_file','case',CaseQuery,CaseFileTool(store),ROLES,'case','1','BACKGROUND_SOURCE','READY'))
    reg.register(ToolSpec('data_experiment','data',ExperimentQuery,DataExperimentTool(cells),('investigator','critic'),'fixture','1','PRIMARY_EXPERIMENTAL_DATA','READY',DATASET))
    client=reg.bind('investigator',cid,stage='unit',purpose='TOOL_VALIDATION')
    question=reg.bind('explorer',cid,stage='unit',purpose='TOOL_VALIDATION').call('case_file',{'operation':'append_record','case_id':cid,'expected_revision':1,'record_type':'evidence_question',
        'record':{'question_id':'Q_TEST','question_text':'Synthetic acquisition contract check','query_spec':{'tool_layer_v01':{'candidate_tools':['data_experiment'],'why_needed':'Unit validation'}}}})
    assert question.status==Status.OK
    env=client.call('data_experiment',exquery().model_dump(mode='json'),parent_question_id='Q_TEST')
    written=client.call('case_file',{'operation':'append_record','case_id':cid,'record_type':'evidence_record','expected_revision':2,
        'envelope_query_id':env.query_id,'record':{'question_id':'Q_TEST','claim_tested':'Synthetic counts only','result_summary':'Fixture measurement'}})
    assert written.status==Status.OK
    case=store.load_case(cid);record=case.evidence_records[0]
    assert record.provenance.parameters['source_mode']=='TEST' and record.raw_result_reference
    assert record.source_type=='dataset' and len(case.hypotheses)==0
    from jure.tools.real.queue_view import evidence_queue_view
    view=evidence_queue_view(case,reg)[0]
    assert view['tool_call_ids']==[env.query_id] and view['evidence_ids']==[record.evidence_id]
    from jure.tools.real.agent_surface import functions_for
    assert {c['function']['name'] for c in functions_for(client)}=={'case_file','data_experiment'}
