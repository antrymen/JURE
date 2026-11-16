"""Fixed acceptance queries only. NEVER constructs or invokes an Agent/LLM."""
import argparse,json
from pathlib import Path
from jure.casefile.store import CaseStore,load_case
from jure.tools.real.factory import build_registry
from jure.tools.real.contracts import Status
from jure.tools.real.registry import file_sha
from jure.tools.real.independence import build_source_graph

def save(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

def validate(output,run_id,*,skip_data=False):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cases=CaseStore(out/'read_only_case_copies.sqlite')
    for letter in 'ABCD':
        case=load_case(f'outputs/pilot_preparation_v1_20260928/initial_cases/{letter}/case_file.json')
        try: cases.load_case(case.metadata.case_id)
        except KeyError:cases.import_case(case)
    a=load_case('outputs/pilot_preparation_v1_20260928/initial_cases/A/case_file.json')
    reg=build_registry(out/'runtime',run_id=run_id,case_store=cases,budgets={'total':160,'literature':30,'knowledge_graph':30,'data_experiment':40})
    reg.snapshot(out/'registry_snapshot.json');results={}
    def call(name,tool,query,actor='investigator',case_id='TOOL_VALIDATION_TIMM23B',**kwargs):
        purpose='CRITIC_RECHECK' if actor=='critic' else 'TOOL_VALIDATION'
        result=reg.bind(actor,case_id,stage='FIXED_ACCEPTANCE_SCRIPT',purpose=purpose).call(tool,query,**kwargs)
        results[name]=result;save(out/(name+'.json'),result.model_dump(mode='json'))
        print(name,result.status.value,flush=True);return result
    for op in ('read_case','history','get_evidence','get_hypotheses','get_audits','read_section'):
        q={'operation':op,'case_id':a.metadata.case_id}
        if op=='read_section':q['section']='clue'
        call('case_'+op,'case_file',q,case_id=a.metadata.case_id)
    clue=call('clue_query_result','clue_query',{'operation':'get_condition_association','condition':'TIMM23B','genes':['DDIT4','PHGDH','RGS16'],'states':[1,1,1]})
    ref=clue.result['matches'][0]['reference_id'] if clue.result.get('matches') else None
    for op in ('get_reference_state','get_landscape_context','get_related_states','get_signed_state_contrasts','get_co_response_context'):
        call('clue_'+op,'clue_query',{'operation':op,'reference_id':ref})
    call('clue_missing','clue_query',{'operation':'get_reference_state','reference_id':'ABSENT_REFERENCE'})
    if not skip_data:
        base={'condition':'TIMM23B'}
        joint=call('data_joint_state_result','data_experiment',{**base,'mode':'JOINT_STATE','state':{'DDIT4':1,'PHGDH':1,'RGS16':1}})
        call('data_marginal_result','data_experiment',{**base,'mode':'MARGINAL','state':{'DDIT4':1}})
        call('data_pairwise_result','data_experiment',{**base,'mode':'PAIRWISE','state':{'DDIT4':1,'PHGDH':1}})
        call('data_conditional_result','data_experiment',{**base,'mode':'CONDITIONAL','state':{'DDIT4':1},'conditioning_states':{'PHGDH':1,'RGS16':1}})
        call('data_condition_comparison_result','data_experiment',{**base,'mode':'CONDITION_COMPARISON','state':{'DDIT4':1},'condition_b':'HSPA9'})
        call('data_state_contrast_result','data_experiment',{**base,'mode':'STATE_CONTRAST','state':{'DDIT4':1,'PHGDH':1,'RGS16':1},'contrast_state':{'DDIT4':0,'PHGDH':1,'RGS16':1}})
        call('data_missing_gene','data_experiment',{**base,'mode':'MARGINAL','state':{'NO_SUCH_GENE_JURE_TEST':1}})
        call('data_low_support','data_experiment',{**base,'mode':'MARGINAL','state':{'DDIT4':1},'min_condition_cells':100000})
        call('data_invalid_state','data_experiment',{**base,'mode':'MARGINAL','state':{'DDIT4':7}})
        same={**base,'mode':'JOINT_STATE','state':{'RGS16':1,'PHGDH':1,'DDIT4':1}}
        call('critic_cached_data','data_experiment',same,actor='critic')
        call('critic_requery_data','data_experiment',same,actor='critic',force_requery=True,requery_reason='Fixed test of independent re-acquisition permission')
        stats=joint.result.get('statistics',{})
        known={'perturbation_hits':stats.get('condition_hits')==240,'perturbation_n':stats.get('condition_n')==498,
            'matched_nt_frequency':abs(stats.get('matched_nt_frequency',99)-.03165512087116487)<1e-12,
            'delta':abs(stats.get('delta',99)-.4502725899722)<1e-12}
        save(out/'known_counts_check.json',{'checks':known,'pass':all(known.values()),'method':'Independent measured state-store query, not candidate CSV'})
    for name,q in [
        ('kg_result',{'operation':'query_entity','entity':'DDIT4'}),
        ('kg_entity_phgdh',{'operation':'query_entity','entity':'PHGDH'}),
        ('kg_subgraph',{'operation':'local_subgraph','entity':'DDIT4','max_hops':1,'max_nodes':12,'max_edges':15}),
        ('kg_edge',{'operation':'query_edge','entity':'DDIT4','target':'MTOR'}),
        ('kg_paths',{'operation':'find_paths','entity':'DDIT4','target':'MTOR','max_hops':2,'max_nodes':30,'max_edges':50}),
        ('kg_missing',{'operation':'query_entity','entity':'ABSENT_JURE_TEST_NODE'}),
        ('kg_invalid',{'operation':'local_subgraph','entity':'DDIT4','max_hops':9})]:call(name,'knowledge_graph',q)
    for name,q in [
        ('gene_knowledge_result',{'operation':'get_gene_info','gene':'DDIT4'}),
        ('gene_alias',{'operation':'get_gene_info','gene':'REDD1'}),
        ('gene_sets',{'operation':'query_gene_sets','gene':'DDIT4','limit':5}),
        ('gene_pathways',{'operation':'query_pathways','gene':'PHGDH','limit':5}),
        ('gene_functional_context',{'operation':'query_functional_context','gene':'RGS16','limit':5}),
        ('gene_missing',{'operation':'get_gene_info','gene':'ABSENT_JURE_TEST_GENE'})]:call(name,'gene_knowledge',q)
    search=call('literature_search_result','literature',{'operation':'search','entities':['DDIT4'],'limit':3})
    ids=[x['pmid'] for x in search.result.get('items',[])][:2]
    if ids:
        retrieved=call('literature_retrieve_result','literature',{'operation':'retrieve','pmids':ids})
        call('critic_requery_literature','literature',{'operation':'retrieve','pmids':ids},actor='critic',force_requery=True,requery_reason='Fixed test of Critic direct source retrieval')
        call('literature_extraction_partial','literature',{'operation':'extract_evidence','pmids':ids})
    else:call('literature_retrieve_result','literature',{'operation':'retrieve','pmids':['35688146']})
    call('literature_no_result','literature',{'operation':'search','keywords':['JURE_ABSENT_LITERAL_9262026_XYZ'],'limit':2})
    call('literature_invalid','literature',{'operation':'retrieve','pmids':['not-a-pmid']})
    call('tn_stub','tn_query',{'query':{}})
    call('explorer_denied_statistics','data_experiment',{'mode':'MARGINAL','condition':'TIMM23B','state':{'DDIT4':1}},actor='explorer')
    count=reg.export_traces(out/'tool_trace.jsonl')
    save(out/'source_independence_graph.json',build_source_graph(results.values()))
    required=['case_read_case','clue_query_result','literature_search_result','literature_retrieve_result']+([] if skip_data else ['data_joint_state_result','data_marginal_result'])
    provenance_pass=all(results[n].source_mode=='REAL' and results[n].source_version and results[n].provenance and results[n].status in (Status.OK,Status.TRUNCATED) for n in required)
    before=json.loads(Path('outputs/tool_validation/protected_before.json').read_text())
    changed=[p for p,sha in before.items() if not Path(p).exists() or file_sha(p)!=sha]
    audit={'source_mode':'REAL','provenance_pass':bool(provenance_pass),'trace_count':count,
        'trace_pass':count==len(results),'protected_files_checked':len(before),'protected_files_changed':changed,
        'agent_invocations':0,'llm_invocations':0,'case_investigations':0,'mock_fallback':False,
        'initial_cases_pristine':all(load_case(f'outputs/pilot_preparation_v1_20260928/initial_cases/{x}/case_file.json').metadata.case_revision==1 for x in 'ABCD')}
    save(out/'provenance_audit.json',audit)
    availability={s.name:{'backend':s.data_source,'configured_status':s.availability,'version':s.source_version} for s in reg.specs.values()}
    for tool,checks in {'case_file':['case_read_case'],'clue_query':['clue_query_result'],'knowledge_graph':['kg_result'],'gene_knowledge':['gene_knowledge_result','gene_sets'],'literature':['literature_search_result','literature_retrieve_result']}.items():
        ok=all(results[n].status in (Status.OK,Status.TRUNCATED) for n in checks)
        availability[tool].update(healthcheck_ids=[results[n].query_id for n in checks],validated_status=('PARTIAL' if tool=='literature' else 'READY') if ok else 'UNAVAILABLE')
    if not skip_data:
        ready=reg.specs['data_experiment'].availability=='READY' and all(known.values()) and results['data_marginal_result'].status==Status.OK
        availability['data_experiment']['validated_status']='READY' if ready else 'PARTIAL'
    else:availability['data_experiment']['validated_status']='NOT_CHECKED'
    availability['tn_query']['validated_status']='NOT_IMPLEMENTED'
    minimum=(all(availability[t]['validated_status']=='READY' for t in ('case_file','clue_query','data_experiment')) and availability['literature']['validated_status']=='PARTIAL' and provenance_pass and audit['trace_pass'] and not changed and audit['initial_cases_pristine'])
    save(out/'tool_availability_manifest.json',{'tools':availability,'MINIMUM_REAL_INVESTIGATION_READY':bool(minimum),'agent_run_authorized_or_started':False})
    print('MINIMUM_REAL_INVESTIGATION_READY',minimum,flush=True)
    return reg

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='outputs/tool_validation/smoke_case');p.add_argument('--run-id',default='real-tools-v01-smoke');p.add_argument('--skip-data',action='store_true');a=p.parse_args()
    validate(a.output,a.run_id,skip_data=a.skip_data)
