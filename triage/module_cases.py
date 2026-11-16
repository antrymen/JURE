"""Select one real, eligible core candidate per requested module; initialize CaseFiles."""
from __future__ import annotations
import argparse,csv,json,tempfile,shutil
from pathlib import Path
from datetime import datetime,timezone
from clue_discovery.integration.io import sha256,write_json,write_jsonl
from clue_discovery.schemas import SelectedCase
from jure.casefile import CaseStore,load_case
from jure.casefile.selected_adapter import initialize_selected_case
from .pilot import eligibility,directional_support,assert_initial
from .pilot_sources import VerifiedPilotSource


def choose(cases,source,protocol):
    def rank(c):
        s=source.shifts[c.case_id]
        return (-abs(c.matched_effect),-s.perturbation_n,-directional_support(c,s),c.condition_id,c.reference_id,c.case_id)
    selected=[];trace=[];audit=[]
    accepted=[]
    for c in cases:
        reasons=eligibility(c,source.shifts[c.case_id],protocol)
        if c.stable_core_context['status']!='stable_core':reasons.append('not_stable_core')
        if c.group_context['group_id'] not in protocol['modules']:reasons.append('outside_requested_modules')
        if not reasons:accepted.append(c)
        audit.append({'case_id':c.case_id,'module':c.group_context['group_id'],'target':c.condition_id,'reference_id':c.reference_id,'eligible':not reasons,'exclusions':'|'.join(reasons)})
    for module in protocol['modules']:
        ranked=sorted((c for c in accepted if c.group_context['group_id']==module),key=rank)
        winner=None;rows=[]
        for i,c in enumerate(ranked,1):
            reasons=[f for f in protocol['deduplication'] if any(getattr(c,f)==getattr(old,f) for old in selected)]
            if not reasons and winner is None:winner=c
            rows.append({'rank':i,'case_id':c.case_id,'rank_key':rank(c),'blocked_by':reasons,'selected':c is winner})
        if winner is None:raise ValueError(f'FAIL_CLOSED: no candidate for {module}')
        selected.append(winner);trace.append({'module':module,'selected_case_id':winner.case_id,'eligible_before_dedup':len(ranked),'ranking':rows})
    return selected,trace,sorted(audit,key=lambda x:x['case_id'])


def prepare(protocol_path,output):
    p=Path(protocol_path);out=Path(output).resolve()
    if out.exists():raise FileExistsError(out)
    protocol=json.loads(p.read_text());freeze=json.loads(p.with_suffix('.freeze.json').read_text())
    assert sha256(p)==freeze['protocol_sha256']
    assert protocol['modules']==['M01','M02','M03','M04','M05']
    assert protocol['membership']=='stable_core' and not protocol['literature_used_in_selection']
    assert protocol['ranking']==['abs(matched_effect)_descending','condition_cells_descending','directional_support_descending','condition_id_ascending','reference_id_ascending','case_id_ascending']
    assert protocol['deduplication']==['condition_id','reference_id','sampling_block_id']
    source=VerifiedPilotSource(protocol['source_run'])
    assert len(source.cases)==protocol['expected_candidate_count']
    assert source.manifest['dataset_id']==protocol['dataset_id']
    choices,trace,audit=choose(source.cases,source,protocol)
    reverse_choices,reverse_trace,_=choose(list(reversed(source.cases)),source,protocol)
    assert [c.case_id for c in choices]==[c.case_id for c in reverse_choices] and trace==reverse_trace
    now=datetime.now(timezone.utc).isoformat()
    assert now>freeze['frozen_at']
    lines={c.case_id:i for i,c in enumerate(source.cases,1)}
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.module-selection-',dir=out.parent) as tmp:
        stage=Path(tmp)/'result';stage.mkdir()
        write_json(stage/'protocol.json',protocol);write_json(stage/'protocol.freeze.json',freeze)
        write_json(stage/'selection_trace.json',trace)
        with (stage/'candidate_eligibility.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(audit[0]));w.writeheader();w.writerows(audit)
        selections=[];index=[];checks=[]
        with CaseStore(stage/'case_store.sqlite') as store:
            for c in choices:
                module=c.group_context['group_id'];dest=stage/'initial_cases'/module
                selected=SelectedCase(case=c,selection_method='rule',selection_reason=f'{module}: eligible stable-core candidate; ranked by absolute matched effect, support, and fixed tie breakers; distinct target from earlier modules. No literature-based ranking.',selector=protocol['protocol_id'],selected_at=now,selection_provenance={'slot':module,'protocol_sha256':freeze['protocol_sha256'],'protocol_frozen_at':freeze['frozen_at'],'triage_path':str(source.triage_path),'triage_sha256':source.checked[str(source.triage_path)],'source_line':lines[c.case_id],'ranking_trace':f'selection_trace.json#module={module}','user_authorization':protocol['user_request']})
                case=initialize_selected_case(selected,verified_source=source,store=store);assert_initial(case)
                store.export_case(case.metadata.case_id,dest);write_json(dest/'selected_case.json',selected)
                assert load_case(dest/'case_file.json')==case and load_case(dest/'case_file.yaml')==case
                # Companions remain source records outside the authoritative focal clue.
                companions=sorted([x for x in source.cases if x.condition_id==c.condition_id and x.group_context['group_id']==module],key=lambda x:(-abs(x.matched_effect),x.reference_id))
                write_jsonl(dest/'same_target_module_candidates.jsonl',companions)
                companions_summary=[{'reference_id':x.reference_id,'signed_pattern':x.signed_pattern,'delta_pp':100*x.matched_effect,'core_status':x.stable_core_context['status'],'is_focal_case':x.case_id==c.case_id,'passes_case_gates':not eligibility(x,source.shifts[x.case_id],protocol)} for x in companions]
                write_json(dest/'companion_summary.json',companions_summary)
                s=source.shifts[c.case_id];rep=source.groups[module].representative_reference_id
                index.append({'module':module,'case_id':c.case_id,'target':c.condition_id,'signed_pattern':c.signed_pattern,'reference_id':c.reference_id,'is_module_medoid':c.reference_id==rep,'core_status':c.stable_core_context['status'],'delta_pp':100*c.matched_effect,'matched_nt_frequency':s.control_frequency,'perturbation_frequency':s.perturb_frequency,'target_cells':s.perturbation_n,'perturbation_hits':s.perturb_count,'holm_exploratory':s.selected_family_holm_exploratory,'same_target_module_candidates':len(companions),'day8_status':c.external_validation_status,'initial_case_file':f'initial_cases/{module}/case_file.json','initial_case_sha256':sha256(dest/'case_file.json')})
                selections.append(selected)
        write_jsonl(stage/'selected_cases.jsonl',selections);write_json(stage/'initial_case_index.json',index)
        source.assert_unchanged();assert sha256(p)==freeze['protocol_sha256']
        write_json(stage/'integrity_audit.json',{'status':'PASS','source_candidates_verified':len(source.cases),'source_files_verified':source.checked,'source_files_unchanged':True,'selection_invariant_to_input_order':True,'five_distinct_targets':len({c.condition_id for c in choices})==5,'all_cases_stable_core':True,'JSON_YAML_roundtrip':True,'all_cases_revision_1_no_scientific_content':True,'agent_calls':0,'statistical_tests_recomputed':False,'selection_script_sha256':sha256(__file__)})
        report=['# M01–M05：每模块一个 Agent 入选案例','','状态：5 个 Initial Case Files 已准备；尚未运行 Explorer / Investigator / Critic。','','选择来源为完整 6,129 条画圈候选，不局限于展示热图的 24×16 子集。沿用既有资格门槛：target cells ≥300、|Δ|≥20 个百分点、每 batch NT ≥20、effective NT ≥100、方向支持 ≥10、探索性 Holm ≤0.05。要求 stable core；按 |Δ|、细胞数、方向支持降序及固定 ID 排序；按 M01→M05 依次排除重复 target/reference/sampling block。未使用文献或先前 Agent 的科学结论。此规则在本轮排序前保存，但不是 discovery 事前注册。','','| Module | Target | Signed pattern | Δ (pp) | Target cells | 同模块同扰动候选数（含主例） |','|---|---|---|---:|---:|---:|']
        for s in index:report.append(f"| {s['module']} | {s['target']} | {s['signed_pattern']} | {s['delta_pp']:+.2f} | {s['target_cells']} | {s['same_target_module_candidates']} |")
        report+=['','每个案例保留一个明确的 target × 完整 signed pattern 主身份。同扰动同模块的其他原始候选保存于 same_target_module_candidates.jsonl / companion_summary.json，作为上下文；不把它们视为独立重复，也不替换主线索。代表案例不一定是模块 medoid，是否为 medoid 已在 index 中注明。','','这些是 Day 6 exploratory associations；Day 8 未验证。Stage 1 A/B 验证不等于该扰动关联已验证。下游按 Explorer → Investigator → Critic 执行，假说、取证顺序、科学判断由真实 Agent 生成。','']
        (stage/'SELECTION_REPORT.md').write_text('\n'.join(report))
        write_json(stage/'preparation_manifest.json',{'status':'INITIAL_CASE_FILES_READY','completed_at':now,'protocol_sha256':freeze['protocol_sha256'],'selected_count':5,'agent_calls':0,'next_stage':'Explorer → Investigator → Critic','artifacts_sha256':{str(f.relative_to(stage)):sha256(f) for f in stage.rglob('*') if f.is_file()}})
        shutil.move(str(stage),out)
    print(json.dumps(index,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',default='configs/module_top5_selection_v1.json');p.add_argument('--output',default='outputs/module_top5_cases_20261004');a=p.parse_args();prepare(a.protocol,a.output)
