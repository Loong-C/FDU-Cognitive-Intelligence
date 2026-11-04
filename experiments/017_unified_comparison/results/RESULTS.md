# 统一 BF16 开发比较

Historical development data, 120 basic + 141 challenge; disjoint from this LoRA training and validation by group/text. PJ used full benchmark, NLI has prior development exposure, and prior LoRA holdout results are known. NOT independent blind testing.

全部 1,566 个评测单元重新生成；不是独立测试。三个适配器分别计分，未挑选保留集最高分种子。

| 方法 | basic | challenge | challenge NEI召回 | challenge R召回 | 幅度限制 |
|---|---:|---:|---:|---:|---|
| baseline | 116/120 (96.67%) | 101/141 (71.63%) | 41.18% | 100.00% | 参照 |
| nli | 115/120 (95.83%) | 105/141 (74.47%) | 48.53% | 100.00% | True |
| pj_v3 | 116/120 (96.67%) | 120/141 (85.11%) | 70.59% | 100.00% | True |
| lora42 | 115/120 (95.83%) | 138/141 (97.87%) | 98.53% | 89.47% | False |
| lora43 | 116/120 (96.67%) | 139/141 (98.58%) | 100.00% | 89.47% | False |
| lora44 | 116/120 (96.67%) | 135/141 (95.74%) | 94.12% | 89.47% | False |

## 挑战集配对比较

| 左侧 | 右侧 | 右减左 | 原始p | Holm p |
|---|---|---:|---:|---:|
| baseline | nli | +2.84 pp | 0.359375 | 0.359375 |
| baseline | pj_v3 | +13.48 pp | 0.0012207031 | 0.0048828125 |
| baseline | lora | +25.77 pp | 1.5258789e-05 | 9.1552734e-05 |
| nli | pj_v3 | +10.64 pp | 0.0072021484 | 0.014404297 |
| nli | lora | +22.93 pp | 4.9591064e-05 | 0.00024795532 |
| pj_v3 | lora | +12.29 pp | 0.0035095215 | 0.010528564 |

## 相对共同基线的预定门槛

{"nli": false, "pj_v3": true, "lora": false}

达到门槛只描述历史开发数据；不等于独立测试泛化或统计非劣效。

## 幅度限制未通过项

- lora42: challenge/REFUTES recall -10.53pp
- lora43: challenge/REFUTES recall -10.53pp
- lora44: challenge/REFUTES recall -10.53pp

## 实际生成成本

| 方法 | 输入token | 输出token | 平均生成秒 |
|---|---:|---:|---:|
| baseline | 86818 | 27650 | 22.250 |
| nli | 116572 | 34722 | 27.934 |
| pj_v3 | 296140 | 43126 | 34.863 |
| lora42 | 86818 | 7488 | 8.356 |
| lora43 | 86818 | 7739 | 8.584 |
| lora44 | 86818 | 7638 | 8.511 |

完整三类指标、分机制结果、无效输出、均值/标准差见 results.json；逐题原文与 token 见 records。
原 A0、NLI、PJ 实质指导不同；统一的是数据、权重精度、计算路径、输入角色、输出协议、上限及评分，不声称提示词长度相等。
PRESUP 在原 LoRA 审核训练中没有样本；训练理由是 AI 辅助标注。V16 原测试封存工程偏差仍保留披露。

## 暂停与恢复披露

用户曾要求缩减评测，原任务暂停后又要求恢复原规模；缩减版没有执行。暂停前已收到的回答均经哈希核验保持原字节。另有 3 次中断请求没有收到回答，原尝试记录保留、用量未知；恢复后仅为缺失评分单元生成回答。本轮存在暂停与恢复，不能描述为从未中断。详见 interruptions.json。
评测中发生一次显存不足，收到的失败记录作为 INVALID 保留计错。经用户许可暂停原 API 后，两个 worker 改用同型号设备 2/3 恢复，推理代码、参数、数据与适配器不变。前后设备资源负载不同，耗时不应外推为纯模型速度差异。
