"""Readable final analysis from independently verified quick24 artifacts only."""
import csv
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / 'experiments/018_fusion'
OUT = EXP / 'quick24_results'
NAMES = {'base_a0': '原模型 A0', 'old_a0': '原 LoRA', 'distill_nli': 'NLI 解释蒸馏',
         'distill_pj': 'PJ 解释蒸馏', 'distill_joint': '联合解释蒸馏'}
ORDER = ['base_a0', 'old_a0', 'distill_nli', 'distill_pj', 'distill_joint']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    receipt = read(ROOT / 'outputs/fusion_v18_collection/latest_quick24.json')
    if not receipt['verified'] or receipt['status'] != 'complete':
        raise ValueError('Requires complete independently verified collection')
    received = Path(receipt['received'])
    results = {part: read(OUT / part / 'results.json') for part in ('validation', 'evaluation')}
    data = {part: {r['dataset'] + '_' + r['id']: r for r in
                  (json.loads(line) for line in (EXP / (part + '.jsonl')).read_text(encoding='utf-8').splitlines())}
            for part in results}
    protocol = read(EXP / 'protocol.json')
    changes = []
    for part, result in results.items():
        for dataset, arms in result['corrections'].items():
            for arm, bases in arms.items():
                for baseline, delta in bases.items():
                    for kind in ('rescued', 'harmed'):
                        for key in delta[kind + '_ids']:
                            row = data[part][key]
                            old = read(received / part / 'direct' / baseline / (key + '.json'))
                            folder = 'direct' if arm in protocol['direct'] else 'fusion'
                            new = read(received / part / folder / arm / (key + '.json'))
                            changes.append({'part': part, 'dataset': dataset, 'method': arm, 'baseline': baseline,
                                'change': kind, 'key': key, 'group': row['group'], 'mechanism': row['mechanism'],
                                'gold': row['label'], 'old_prediction': old['prediction'], 'new_prediction': new['prediction'],
                                'evidence': row['evidence'], 'claim': row['claim'], 'old_explanation': old['text'],
                                'new_explanation': new['text'], 'old_record_sha256': old['record_sha256'],
                                'new_record_sha256': new['record_sha256']})
    with (OUT / 'corrections_and_harms.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(changes[0])); writer.writeheader(); writer.writerows(changes)
    evaluation = results['evaluation']; validation = results['validation']
    lines = ['# V18 一天版最终分析', '',
        '完成的融合方案没有达到预先规定的成功标准。261题开发比较中，原LoRA挑战均值97.40%，联合解释蒸馏96.93%，NLI解释蒸馏95.74%，PJ解释蒸馏95.27%。这些差异未通过组配对检验的23项Holm校正，不能据此断言蒸馏显著变差。', '',
        '服务器于2026-11-03 11:26（北京时间）完成归档和API恢复，比15:55截止提前约4小时29分。九次训练、35×259验证和13×261开发比较全部完成；本机已核对接收字节、独立复算指标/组检验和物理调用成本。原62配置研究的延期部分不计为完成。', '',
        '## 261题开发比较', '',
        '含LoRA的结果是三个种子的均值；±为样本标准差。基础120题，挑战141题。', '',
        '| 方法 | 基础准确率 | 挑战准确率 | 挑战Macro-F1 | 相对原LoRA挑战变化 | 全种子幅度限制 |',
        '|---|---:|---:|---:|---:|---|']
    for family in ORDER:
        b = evaluation['datasets']['basic']['families'][family]
        t = evaluation['datasets']['challenge']['families'][family]
        base = evaluation['datasets']['challenge']['families']['old_a0']['accuracy']
        fmt = lambda v: f"{v['accuracy']:.2%}" + (f" ± {v['seed_accuracy_stdev']:.2%}" if v['seed_accuracy_stdev'] is not None else '')
        lines.append(f"| {NAMES[family]} | {fmt(b)} | {fmt(t)} | {t['macro_f1']:.4f} | {(t['accuracy']-base)*100:+.2f} pp | {evaluation['guardrails'][family]['passed']} |")
    lines += ['', '## 三种子明细', '', '| 方法 | 种子 | 基础准确率 | 挑战准确率 | 基础无效 | 挑战无效 |', '|---|---:|---:|---:|---:|---:|']
    for family in ORDER[1:]:
        for seed in (42, 43, 44):
            arm = family + '_' + str(seed)
            b, t = (evaluation['datasets'][d]['scores'][arm] for d in ('basic', 'challenge'))
            lines.append(f"| {NAMES[family]} | {seed} | {b['accuracy']:.2%} | {t['accuracy']:.2%} | {b['invalid']} | {t['invalid']} |")
    lines += ['', '## 修正与损害', '',
        '下表是相对于同种子原LoRA的每种子平均题数；同一题跨种子重复出现，不当作独立样本。CSV保留题号、原证据/陈述、两份解释、金标和响应哈希。', '',
        '| 来源 | 集合 | 修正均值 | 损害均值 | 准确率差 | 配对p | Holm p |', '|---|---|---:|---:|---:|---:|---:|']
    for family in ORDER[2:]:
        for dataset in ('basic', 'challenge'):
            v = next(x for x in evaluation['datasets'][dataset]['pairs'] if x['method'] == family)
            lines.append(f"| {NAMES[family]} | {dataset} | {v['rescued_mean']:.2f} | {v['harmed_mean']:.2f} | {v['accuracy_delta']*100:+.2f} pp | {v['p']:.4f} | {v['holm_p']:.4f} |")
    lines += ['', f"[逐题修正与损害 CSV]({(OUT/'corrections_and_harms.csv').as_posix()})", '',
        '## 类别召回和约束筛选', '',
        '相对本轮原模型A0，基础准确率最多下降2个百分点，两集合各类召回最多下降5个百分点；含LoRA要求每个种子都通过，并且挑战均值高于原LoRA。不能以均值掩盖失败种子。联合蒸馏的挑战NEI平均召回较高，但REFUTES平均召回下降。', '',
        '| 方法 | 集合 | SUPPORTS召回 | REFUTES召回 | NEI召回 |', '|---|---|---:|---:|---:|']
    for family in ORDER:
        for dataset in ('basic', 'challenge'):
            v = evaluation['datasets'][dataset]['families'][family]['recall']
            lines.append(f"| {NAMES[family]} | {dataset} | {v['SUPPORTS']:.2%} | {v['REFUTES']:.2%} | {v['NOT ENOUGH INFO']:.2%} |")
    lines += ['',
        '快速版只在事前固定的13配置、五个方法族中作最终推荐。验证阶段已冻结的正式退回项是原模型A0：所有新蒸馏族未达标，原LoRA也有种子触及原先的退步限制。挑战REFUTES只有19题，错1题即下降5.26个百分点，超过5个百分点阈值。A0在开发比较的挑战准确率为71.63%，原LoRA为97.40%；这展示了严格类别约束与挑战准确率之间的权衡。推荐文件保留原规则的结果，不按开发比较成绩另选种子或放宽阈值。',
        '本轮不采用新的融合适配器。原LoRA仍是本次挑战准确率最高的参照，但它并未满足全部类别约束；两项事实均须保留。', '',
        '## 三条融合路径的已完成证据', '',
        '- 提示词组合：259题验证中，LoRA+NLI挑战均值96.88%，原LoRA96.64%，仅+0.24pp，种子43未通过限制，Holm p=1；LoRA+PJ与三者提示拼接均未超过原LoRA。该路径未补跑261题。',
        '- 分歧复核：259题验证中，NLI+LoRA、PJ+LoRA、三路复核挑战均值分别91.61%、91.37%、89.21%，基础均为100%；均未达到挑战提升要求。新蒸馏适配器的复核未执行。',
        '- 解释蒸馏：三个来源、每来源三个种子均完成三轮训练，并完成完整259/261题；联合来源最接近原LoRA，但仍未达标。', '',
        '## 实测推理成本', '',
        '以下来自261题比较，含LoRA先按种子平均。时间为单次生成的观测耗时，不含模型加载，也不是部署吞吐保证。', '',
        '| 方法 | 平均调用/题 | 平均输入+输出token/题 | 平均生成秒/题 |', '|---|---:|---:|---:|']
    cost_table = {}
    for family in ORDER:
        weighted = {field: sum(evaluation['datasets'][d]['families'][family][field] * evaluation['datasets'][d]['n']
                              for d in ('basic', 'challenge')) / 261 for field in ('mean_calls', 'mean_tokens', 'mean_seconds')}
        cost_table[family] = weighted
        lines.append(f"| {NAMES[family]} | {weighted['mean_calls']:.2f} | {weighted['mean_tokens']:.1f} | {weighted['mean_seconds']:.2f} |")
    cost = read(OUT / 'costs.json'); history = read(OUT / 'historical_costs.json')
    new = sum(cost['physical_by_phase'][n]['calls'] for n in ('quick24_validation', 'quick24_evaluation'))
    total = cost['calls'] + history['historical_teacher_and_smoke_calls'] + sum(v['calls'] for v in history['training_smoke_inference'])
    lines += ['',
        f"一天版新增物理生成{new}次（2331验证+3393比较，3条烟测包含在验证内）；加上复用的旧验证与复核，本次报告覆盖{cost['calls']}次物理生成。再计教师及各类烟测，本轮记录到{total}次生成，另有{history['unanswered_attempts_unknown_cost']}次未收到响应的尝试，成本未知。",
        f"九次训练共{history['training_updates']}个更新，步骤耗时合计{history['training_step_seconds']/3600:.2f}小时；切换回放{history['preserved_replayed_updates']}个更新，另保留{history['replayed_step_seconds']:.1f}秒已完成步骤成本。并行步骤耗时合计不等于墙钟时间，未落盘的部分更新、模型加载及服务健康检查开销不在这些生成/步骤计数内。", '',
        '## 范围与限制', '',
        '- 新模型固定第3轮，旧LoRA沿用已冻结checkpoint；没有完成原先的27轮checkpoint择优，不能排除其他轮次更好。',
        '- 261题已有历史暴露；这里是开发比较，不是独立盲测泛化证明。缩减范围是在先前验证成绩已知、用户提出一天时限后冻结。',
        '- 场景组配对检验分别使用14个基础组和23个挑战组。保留23项Holm比较范围，未执行项p=1，不把三个种子当三倍独立题目。',
        '- 原金标、题目和已收到的无效输出均保留；AI辅助理由审核、PRESUP训练缺失、原标签歧义和V16封存偏差继续披露。',
        '- 原完整方案仍缺49个261题配置、蒸馏后的新增复核及逐轮选优。本报告仅称一天版完成。', '',
        '## 交付文件', '',
        f"- [完整259题验证表]({(OUT/'validation/RESULTS.md').as_posix()})", 
        f"- [完整261题比较表]({(OUT/'evaluation/RESULTS.md').as_posix()})",
        f"- [机器可复用配置]({(OUT/'evaluation/recommended_method.json').as_posix()})",
        f"- [验证审计]({(OUT/'validation/audit.json').as_posix()}) / [比较审计]({(OUT/'evaluation/audit.json').as_posix()})",
        f"- [调用成本]({(OUT/'costs.json').as_posix()}) / [训练与历史成本]({(OUT/'historical_costs.json').as_posix()})",
        f"- [原标签歧义记录]({(EXP/'REVIEW_AMBIGUITIES.json').as_posix()})",
        f"- 接收归档SHA256：{receipt['archive_sha256']}；文件数：{receipt['files']}。"]
    (OUT / 'ASSESSMENT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (OUT / 'COST_COMPARISON.json').write_text(json.dumps(cost_table, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'assessment': str(OUT / 'ASSESSMENT.md'), 'correction_rows': len(changes),
                      'new_physical_calls': new, 'recorded_generation_total': total}, ensure_ascii=False))


if __name__ == '__main__':
    main()
