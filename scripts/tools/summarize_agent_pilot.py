"""Render execution facts only; never infer a case mechanism or verdict."""
import argparse,json
from pathlib import Path


def render_agent_report(path):
    d=json.loads(path.read_text())
    lines=['# JURE Agent Case Report','',
        '正文直接来自已提交的 JURE FinalReport；此脚本只排版，不补充机制分析。','',
        f"Case: `{d['case_id']}` · STOP: **{d['stop_type']}**",'',
        f"[结构化原始报告]({path.resolve()})",'']
    labels={'mechanistic_question':'Mechanistic question','clue_summary':'Clue',
        'observation':'Observation','interpretation':'Interpretation','overall_case_summary':'Agent case summary',
        'uncertainty':'Uncertainty','investigation_limitations':'Investigation limitations'}
    for field,label in labels.items():
        lines += ['## '+label,'']
        value=d[field]
        lines += ['- '+str(v) for v in value] if isinstance(value,list) else [value]
        lines.append('')
    for hypothesis in d['final_hypotheses']:
        lines += [f"## {hypothesis['hypothesis_id']} — {hypothesis['status']}",'',hypothesis['mechanism_statement'],'']
        for field in ('key_supported_claims','key_challenged_claims','critical_gaps','key_evidence_ids','contradictions','remaining_uncertainties'):
            if hypothesis[field]:lines += [field+':','',*[('- '+str(v)) for v in hypothesis[field]],'']
    lines += ['## Agent-recommended experiments','']
    for experiment in d['recommended_experiments']:
        lines += ['```json',json.dumps(experiment,ensure_ascii=False,indent=2),'```','']
    out=path.with_name('AGENT_CASE_REPORT.md');out.write_text('\n'.join(lines));return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='outputs/agent_pilot_v1_20260928');args=p.parse_args()
    root=Path(args.root);rows=[];calls=[]
    for run in sorted(root.glob('run_*')):
        for path in sorted(run.glob('*/case_run_summary.json')):
            d=json.loads(path.read_text());rows.append((run.name,d))
        for path in sorted(run.glob('*/model_calls/call_*/call.json')):
            calls.append(json.loads(path.read_text()))
    report=['# JURE real Agent pilot execution report','',
        '本报告只汇总真实执行记录。机制解释、假说、审计和最终科学结论以 JURE Agent 的原始输出和已提交 Case File 为准。所有尝试均保留，不按科学结论筛选。','',
        '这是包含接口调试、失败重试和 checkpoint 续跑的工程 pilot，不是正式 benchmark。同一 case 的 checkpoint 携带不算新案例；Hypotheses / Evidence / Tools 为该 checkpoint 的累计状态，不能跨运行相加。模型调用同时列出本次与续跑链累计数。','']
    latest={}
    for run,d in rows:latest[d['case']]=(run,d)
    report += ['## 四个固定案例的最新已结束运行','',
        '| Case | 运行状态 | Hypotheses | Evidence | Tools | 记录 |',
        '|---|---|---:|---:|---:|---|']
    for letter in 'ABCD':
        if letter not in latest:
            report.append(f'| {letter} | 尚无结束记录 | — | — | — | — |');continue
        run,d=latest[letter];directory=root/run/letter
        state=d['stop_reason'] if d['completed'] else d['failure'] or '未完成'
        report.append(f"| {letter} | {state} | {d['hypotheses']} | {d['evidence_records']} | {d['tool_calls']} | [摘要]({(directory/'case_run_summary.json').resolve()}) |")
    report += ['', '## 完整运行历史','',
        '| Run | Case | 完成/技术门槛 | STOP | Hypotheses | Evidence | Tools | Critic rechecks | Model calls 本次/累计 |',
        '|---|---|---|---|---:|---:|---:|---:|---:|']
    for run,d in rows:
        report.append(f"| {run} | {d['case']} | {d['completed']}/{d['technical_gate_passed']} | {d['stop_reason'] or '未产生'} | {d['hypotheses']} | {d['evidence_records']} | {d['tool_calls']} | {d['critic_recheck_calls']} | {d['model']['calls']}/{d.get('cumulative_model_calls',d['model']['calls'])} |")
    total=sum(int((c.get('usage') or {}).get('total_tokens',0)) for c in calls)
    estimates={}
    pricing=json.loads(Path('configs/glm_pricing_snapshot_20260928.json').read_text())
    for c in calls:
        usage=c.get('usage')
        model=c.get('requested_model')
        if not isinstance(pricing.get(model),list) or usage is None:continue
        n=usage.get('prompt_tokens',0);cached=usage.get('prompt_tokens_details',{}).get('cached_tokens',0)
        rate=next(tier for tier in pricing[model] if tier['input_tokens_less_than'] is None or n<tier['input_tokens_less_than'])
        estimates[model]=estimates.get(model,0)+(max(0,n-cached)*rate['input']+min(cached,n)*rate['cached_input']+usage.get('completion_tokens',0)*rate['output'])/1e6
    for model,cost in sorted(estimates.items()):
        report+=['',f'{model} 已报告用量对应估算费用：人民币 {cost:.4f} 元（官方价格快照，非账单；未返回 usage 的请求无法计入）。','']
    report+=['',f'已记录 provider 请求 {len(calls)} 次；成功 {sum(c["status"]=="success" for c in calls)} 次；已报告 token {total}。失败或中断请求未返回 usage 时，token 总量和上述费用估算均不代表完整账单。此处按请求原始记录统计，不重复计算继承 checkpoint 中的调用。','']
    for run,d in rows:
        directory=root/run/d['case']
        abort=root/run/'HOST_ABORT.json'
        if not abort.exists():abort=root/run/'DEVELOPMENT_NOTE.json'
        host_note=json.loads(abort.read_text())['reason'] if abort.exists() else None
        if host_note:report += [f'Host 调试备注：{host_note}','']
        report+=[f"## {run} / Case {d['case']}",'',f"失败信息：{d['failure'] or host_note or '无'}",'',
            f"初始文件保持不变：{d['initial_source_unchanged']}；全部工具来源为 REAL：{d.get('all_tool_sources_real')}。",'',
            f"Critic 路由：{json.dumps(d['critic_routes'],ensure_ascii=False)}；工具选择：{json.dumps(d['tool_selection'],ensure_ascii=False)}。",'',
            f"[执行摘要]({(directory/'case_run_summary.json').resolve()}) · [模型 usage]({(directory/'model_usage.json').resolve()}) · [工具 trace]({(directory/'tool_trace.jsonl').resolve()}) · [Case File]({(directory/'case_file/case_file.json').resolve()})",'']
        if d.get('predecessor'):
            report += [f"Checkpoint 来源：`{d['predecessor']['directory']}`；本次新增阶段：{d['current_run_stages']}。",'']
        if (directory/'final_case_report.json').exists():
            rendered=render_agent_report(directory/'final_case_report.json')
            report += [f"[Agent 最终报告]({rendered.resolve()})",'']
    errors={}
    for c in calls:
        if c['status']!='success':
            key=f"{c.get('error')} / HTTP {c.get('http_status')} / code {c.get('provider_error_code')}"
            errors[key]=errors.get(key,0)+1
    report+=['## Provider diagnostics','',json.dumps(errors,ensure_ascii=False,indent=2),'']
    out=root/'AGENT_PILOT_EXECUTION_REPORT.md';out.write_text('\n'.join(report));print(out)

if __name__=='__main__':main()
