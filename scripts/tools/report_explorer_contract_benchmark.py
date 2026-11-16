"""Render frozen Explorer contract metrics; never write scientific verdicts."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    root=Path(args.root).resolve();summary=json.loads((root/'BENCHMARK_SUMMARY.json').read_text())
    frozen=json.loads((root/'BENCHMARK_FROZEN.json').read_text())
    if not summary['completed']:raise ValueError('Do not publish a final report before every fixed attempt finishes')
    rows=[json.loads(p.read_text()) for p in sorted((root/'runs').glob('*/*/RESULT.json'))]
    labels={'legacy_identifiers':'旧接口：模型生成完整对象','deterministic_adapter':'新接口：程序装配对象'}
    lines=['# Explorer-only Contract Benchmark v1','',
        '本报告是 Codex 对真实 Explorer 执行的工程统计，不是生物 benchmark、Critic 科学判决或机制研究结果。', '',
        '**仅运行 Explorer。A/B/C/D 没有执行，真实证据工具、Investigator、Critic 调用均为 0。**','',
        f"契约通过率 ≥95%：{'达到' if summary['adapter_contract_threshold_met'] else '未达到'}。完整 proposal 提交率 ≥95%：{'达到' if summary['full_proposal_threshold_met'] else '未达到'}。",'',
        '| 指标 | 旧接口 | deterministic adapter |','|---|---:|---:|']
    left=summary['arms']['legacy_identifiers'];right=summary['arms']['deterministic_adapter']
    for label,key in [('固定输入数','planned_attempts'),('完成尝试','finished_attempts'),('schema + reference 通过','contract_passes'),
                      ('完整 proposal 提交','submitted'),('模型调用','model_calls'),('重试','retries'),('已报告 token','reported_tokens')]:
        lines.append(f'| {label} | {left[key]} | {right[key]} |')
    for label,key in [('契约通过率','contract_pass_rate'),('完整提交率','submission_rate')]:
        lines.append(f'| {label} | {left[key]:.0%} | {right[key]:.0%} |')
    saved=left['reported_tokens']-right['reported_tokens']
    lines+=['',f"已报告 token 差额（旧−新）：{saved:,}。Usage 完整性：旧={left['usage_complete']}，新={right['usage_complete']}；无 usage 的请求不能当作零成本。",'',
        '契约指标的分母固定为每组 20 次尝试，包含 provider/JSON 失败。完整提交还必须通过原有科学内容守卫；这两个指标不可互换。20 个输入不足以证明总体可靠性。','',
        '## 失败类别','',
        '下列计数按错误记录统计，单次尝试可能有多个错误，不能跨类别相加当作失败样本数。','',
        '| 类别 | 旧接口 | adapter |','|---|---:|---:|']
    categories=set(left['engineering_failure_categories'])|set(right['engineering_failure_categories'])
    for c in sorted(categories):lines.append(f"| {c} | {left['engineering_failure_categories'].get(c,0)} | {right['engineering_failure_categories'].get(c,0)} |")
    lines+=['',f"契约通过后仍被自动内容守卫拒绝的尝试：旧 {left['scientific_guard_failed_attempts']}，新 {right['scientific_guard_failed_attempts']}。其中带 entity guard flag：旧 {left['entity_guard_flagged_attempts']}，新 {right['entity_guard_flagged_attempts']}。",'',
        '**这些是现有自动校验器的标记，不能直接命名为 genuine scientific-content failure。** 命名误报、限定语识别、统计语义和真正过度推断可能混在其中，未调用 Critic 作生物学裁决。原始错误逐样本保留。','',
        '## 科学内容保留','',
        f"Adapter 已完成 {right['content_retention_verified']} 份 proposal 的内容往返哈希核验；仅对成功编译的输出计算，不把无法解析的输出算作已保留。程序复制问题、机制、假设、预测、区分期望、结果分支与对照差异，没有补造科学内容。结构边中已提供基因符号的大小写规范化单独留痕。",'',
        '两组是独立模型生成，不能说两组 hypotheses 内容相同。保留率测的是一次 adapter 转换前后，而不是模型间科学答案一致性。','',
        '## 设计与边界','',
        '只有四份既存 pilot Initial Case Files。为本次测试从已验证的 6,129 个候选中另行初始化 20 个输入：enrichment/depletion 各 10 个，按冻结哈希规则选取，扰动条件不重复并排除 A/B/C/D 条件。未按 effect 或结果好坏选样。两组使用相同输入、模型设置及科学守卫，每输入每组一请求、零重试。','',
        '本比较改变了完整的输出接口及相应指令，不能解释成“只改变 IDs”这一单因素的因果消融，也不能包装成科学方法创新。所有失败保留，没有据中途结果调参或换样。','',
        f"运行代码与冻结 manifest 一致：{summary['runtime_unchanged']}；四份 pilot 原始文件未改：{summary['pilot_initial_files_unchanged']}。A 之前消耗的 8 次调用仍保留，其全局剩余额度为 72；阶段尝试限制仍须另行遵守，本测试不重置 A 预算。",'',
        '本轮不自动启动 A。即使工程契约达标，若完整 proposal 提交仍不稳定，也不能据此直接进入科学循环。三个 v3 科学协议接口在这个 Explorer-only 测试里未得到 end-to-end 验证。','',
        '## 每个输入的真实结果','',
        '| 输入 | 组 | 契约通过 | 正式提交 | 错误类别 | 记录 |','|---|---|---|---|---|---|']
    for r in rows:
        errors=','.join(sorted({e['category'] for e in r['engineering_errors']})) or ('自动内容守卫' if not r['proposal_submitted'] else '无')
        path=root/'runs'/r['slot']/r['arm']/'RESULT.json'
        lines.append(f"| {r['slot']} | {labels[r['arm']]} | {r['contract_pass']} | {r['proposal_submitted']} | {errors} | [原始记录]({path}) |")
    lines+=['','## 复现资料','',
        f"- [冻结规则、代码及输入哈希]({root/'BENCHMARK_FROZEN.json'})",
        f"- [固定输入目录]({root/'INITIAL_CASE_INDEX.json'})",
        f"- [机器可读指标]({root/'BENCHMARK_SUMMARY.json'})",
        '- [接口说明](/Users/mac/Documents/ChatGPT/JURE/docs/tools/EXPLORER_CONTRACT_STABILIZATION.md)',
        '- [离线测试](/Users/mac/Documents/ChatGPT/JURE/tests/test_explorer_content_adapter.py)','']
    out=root/'EXPLORER_CONTRACT_BENCHMARK_REPORT.md';out.write_text('\n'.join(lines));print(out)


if __name__=='__main__':main()
