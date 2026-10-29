"""对完成的Baseline生成错例清单与阶段分析；不修改模型、标签或提示词。"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from baseline_eval import percentage, read_records
from benchmark import DATASETS, LABELS, read_sources, write_json

NAMES = {
    'DENIAL': '否认与证伪', 'TEMPSCOPE': '时间范围', 'PRESUP': '预设',
    'SETCLOSE': '开放列表与封闭集合', 'UNIQUE': '排他性与唯一性',
    'LOOKALIKE': '相似主体与属性归属', 'AMBIGREF': '指代歧义',
}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('result_dir', type=Path)
    args = parser.parse_args()
    out = args.result_dir.resolve()
    status = json.loads((out / 'run_status.json').read_text(encoding='utf-8'))
    if not status['complete']:
        raise SystemExit('全量尚未完成；暂不生成最终分析。失败输出在完成后保留计分。')
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    manifest = json.loads((out / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['settings']['phase'] != 'full':
        raise SystemExit('此脚本只分析全量结果')
    datasets, _, audit = read_sources()
    errors = {}
    lines = ['# 认知智能课程 PJ 事实判断 Baseline 阶段分析', '',
             '本轮使用远程开放权重模型qwen38-27b，按A方原提示词进行零样本三分类事实核查。输入仅为给定证据和陈述，不检索外部知识，不引入示例，不进行训练。', '',
             '## 实验设置', '',
             f"temperature=0；enable_thinking=false；max_tokens={manifest['settings']['config']['max_tokens']}；并发数={manifest['settings']['workers']}。逐条保存原始响应、终止原因、token用量和耗时。只解析最终Verdict行。", '',
             '模型量化格式据此前聊天为W8A8，尚未由服务提供方独立确认；A方参考模型使用Q8_0。下表只并列描述，不将差异解释为同配置优化收益。', '',
             '## 两份集合分别评分', '',
             '| 集合 | 正确/总数 | Accuracy | Macro-F1 | SUPPORTS Recall | REFUTES Recall | NEI Recall |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for name, m in summary['datasets'].items():
        recalls = [percentage(m['per_class'][label]['recall']) for label in LABELS]
        lines.append(f"| {DATASETS[name][0].removesuffix('.jsonl')} | {m['correct']}/{m['count']} | {percentage(m['accuracy'])} | {m['macro_f1']:.4f} | " + ' | '.join(recalls) + ' |')
    lines += ['', '失败输出未剔除。完整混淆矩阵、机制分组与耗时见同目录report.md和summary.json。', '']
    for name, m in summary['datasets'].items():
        records = read_records(out / f'{name}.jsonl')
        errors[name] = []
        usage_reasoning = 0
        for row in datasets[name]:
            record = records[row['id']]
            usage = record.get('raw_response', {}).get('usage') or {}
            details = usage.get('completion_tokens_details') or {}
            usage_reasoning += details.get('reasoning_tokens') or 0
            if row['label'] != record['prediction']:
                errors[name].append({**row, 'prediction': record['prediction'], 'model_output': record.get('raw_text', ''),
                                     'status': record['status'], 'parse_error': record.get('parse_error')})
        lines += [f"## {DATASETS[name][0].removesuffix('.jsonl')}的错误分布", '',
                  f"错例{len(errors[name])}条；解析失败{m['status_counts']['parse_error']}条，请求失败{m['status_counts']['request_error']}条。服务端用量字段中累计reasoning_tokens={usage_reasoning}；缺失该字段的响应不据此推断内部推理。", '']
        if name == 'challenge':
            nei = m['confusion_matrix']['NOT ENOUGH INFO']
            lines += [f"425条NEI中，正确{nei['NOT ENOUGH INFO']}条，误判REFUTES {nei['REFUTES']}条，误判SUPPORTS {nei['SUPPORTS']}条。", '',
                      '| 机制 | Accuracy | NEI Recall | 错例数 |', '| --- | ---: | ---: | ---: |']
            for mechanism, group in m['by_mechanism'].items():
                lines.append(f"| {mechanism}（{NAMES.get(mechanism, mechanism)}） | {percentage(group['accuracy'])} | {percentage(group['per_class']['NOT ENOUGH INFO']['recall'])} | {group['count'] - group['correct']} |")
            lines += ['']
        confusions = Counter((r['label'], r['prediction']) for r in errors[name])
        if confusions:
            lines.append('主要混淆：' + '；'.join(f'{gold} → {pred}：{count}条' for (gold, pred), count in confusions.most_common()) + '。')
            lines.append('')
    lines += ['## 后续优化与验证', '',
              '先冻结本轮配置和结果。以错误集中的证据边界、时间范围、主体归属和指代消解为候选问题，后续是否改进以实验为准，不预先承诺增益。', '',
              '任何开发集与保留集划分均须按group整组进行；不能将同一场景的不同变体分到两边。本轮两份集合已经完成全量观察，因此后续无偏验证宜向A方索取新增且未参与分析的保留集。基础能力集同时作为回归检查，防止一味增加NEI预测。', '',
              '基础能力集原始human_review_status全部为pending；本轮沿用提供的label评分，不改变其审核状态。模型预测与这些标签不一致时，先作为待复核案例，不直接宣称模型或数据哪方一定错误。', '',
              '## 课程交付范围', '',
              '当前完成Baseline代码、两份集合评测与缺陷分析。模型优化、训练日志、组员分工、两次展示及正文不超过8页的最终报告仍需后续完成。课程规定不得使用闭源大模型作为被测或优化模型；代码辅助使用的AI工具和模型来源需在最终报告如实说明。']
    (out / '阶段分析.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(out / 'error_analysis.json', errors)
    cases = ['# 事实判断 Baseline 代表错例', '', '每类机制按原数据顺序选前两条；完整错例见error_analysis.json。金标准为A方提供标签。', '']
    for name, values in errors.items():
        cases += ['## ' + DATASETS[name][0].removesuffix('.jsonl'), '']
        counts = Counter()
        for row in values:
            if counts[row['mechanism']] >= 2:
                continue
            counts[row['mechanism']] += 1
            cases += [f"### {row['mechanism']} · {row['id']}", '',
                      f"提供标签：{row['label']}；模型预测：{row['prediction']}；group：{row['group']}。", '',
                      '**证据**', '', row['evidence'], '', '**陈述**', '', row['claim'], '', '**模型原始输出**', '', row['model_output'], '']
    (out / '代表错例.md').write_text('\n'.join(cases) + '\n', encoding='utf-8')
    print('阶段分析、完整错例JSON与代表错例已生成。')


if __name__ == '__main__':
    main()
