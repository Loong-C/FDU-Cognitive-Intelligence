# 续跑统计表（由原始记录离线生成）

> 2026-10-26 续跑已完成全部104题。下文 `stops` 是保留的10月24日历史停点，不代表本次仍被限流；分日成本与当前状态见 [续跑摘要](resumption_20261026_summary.json)。

生成时间：2026-10-26T02:15:28.295763+00:00

主要分母为冻结的全部104题。完整配对子集另列，不能替代完整评测；未决和缺失均计错。

## 全部预定样本

| 数据 | 方法 | 正确/分母 | 准确率 | 宏F1 | 三分类覆盖率 | 已给三分类条件准确率 |
|---|---|---|---|---|---|---|
| combined | A27 | 90/104 | 86.54% | 0.8722 | 100.00% | 86.54% |
| combined | V5 | 69/104 | 66.35% | 0.7438 | 75.00% | 88.46% |
| basic | A27 | 60/60 | 100.00% | 1.0000 | 100.00% | 100.00% |
| basic | V5 | 51/60 | 85.00% | 0.8571 | 90.00% | 94.44% |
| challenge | A27 | 30/44 | 68.18% | 0.6594 | 100.00% | 68.18% |
| challenge | V5 | 18/44 | 40.91% | 0.4931 | 54.55% | 75.00% |

| 数据 | 方法 | 类别 | 支持数 | 精确率 | 召回率 | F1 |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 13 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | REFUTES | 23 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | NOT ENOUGH INFO | 24 | 100.00% | 100.00% | 1.0000 |
| basic | V5 | SUPPORTS | 13 | 100.00% | 53.85% | 0.7000 |
| basic | V5 | REFUTES | 23 | 100.00% | 86.96% | 0.9302 |
| basic | V5 | NOT ENOUGH INFO | 24 | 88.89% | 100.00% | 0.9412 |
| challenge | A27 | SUPPORTS | 17 | 100.00% | 88.24% | 0.9375 |
| challenge | A27 | REFUTES | 5 | 27.78% | 100.00% | 0.4348 |
| challenge | A27 | NOT ENOUGH INFO | 22 | 90.91% | 45.45% | 0.6061 |
| challenge | V5 | SUPPORTS | 17 | 100.00% | 41.18% | 0.5833 |
| challenge | V5 | REFUTES | 5 | 28.57% | 40.00% | 0.3333 |
| challenge | V5 | NOT ENOUGH INFO | 22 | 90.00% | 40.91% | 0.5625 |

| 数据 | 方法 | gold | 预测S | 预测R | 预测NEI | INVALID（未决/缺失） |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 13 | 0 | 0 | 0 |
| basic | A27 | REFUTES | 0 | 23 | 0 | 0 |
| basic | A27 | NOT ENOUGH INFO | 0 | 0 | 24 | 0 |
| basic | V5 | SUPPORTS | 7 | 0 | 2 | 4 |
| basic | V5 | REFUTES | 0 | 20 | 1 | 2 |
| basic | V5 | NOT ENOUGH INFO | 0 | 0 | 24 | 0 |
| challenge | A27 | SUPPORTS | 15 | 1 | 1 | 0 |
| challenge | A27 | REFUTES | 0 | 5 | 0 | 0 |
| challenge | A27 | NOT ENOUGH INFO | 0 | 12 | 10 | 0 |
| challenge | V5 | SUPPORTS | 7 | 0 | 1 | 9 |
| challenge | V5 | REFUTES | 0 | 2 | 0 | 3 |
| challenge | V5 | NOT ENOUGH INFO | 0 | 5 | 9 | 8 |

| 数据 | 方法 | NEI→R | NEI→S | S→NEI | R→NEI | 未决按gold | 未运行按gold |
|---|---|---|---|---|---|---|---|
| basic | A27 | 0 | 0 | 0 | 0 | {} | {} |
| basic | V5 | 0 | 0 | 2 | 1 | {"SUPPORTS": 4, "REFUTES": 2} | {} |
| challenge | A27 | 12 | 0 | 1 | 0 | {} | {} |
| challenge | V5 | 5 | 0 | 1 | 0 | {"SUPPORTS": 9, "NOT ENOUGH INFO": 8, "REFUTES": 3} | {} |

## 已完成配对子集（描述性）

| 数据 | 方法 | 正确/分母 | 准确率 | 宏F1 | 三分类覆盖率 | 已给三分类条件准确率 |
|---|---|---|---|---|---|---|
| combined | A27 | 90/104 | 86.54% | 0.8722 | 100.00% | 86.54% |
| combined | V5 | 69/104 | 66.35% | 0.7438 | 75.00% | 88.46% |
| basic | A27 | 60/60 | 100.00% | 1.0000 | 100.00% | 100.00% |
| basic | V5 | 51/60 | 85.00% | 0.8571 | 90.00% | 94.44% |
| challenge | A27 | 30/44 | 68.18% | 0.6594 | 100.00% | 68.18% |
| challenge | V5 | 18/44 | 40.91% | 0.4931 | 54.55% | 75.00% |

| 数据 | 方法 | 类别 | 支持数 | 精确率 | 召回率 | F1 |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 13 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | REFUTES | 23 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | NOT ENOUGH INFO | 24 | 100.00% | 100.00% | 1.0000 |
| basic | V5 | SUPPORTS | 13 | 100.00% | 53.85% | 0.7000 |
| basic | V5 | REFUTES | 23 | 100.00% | 86.96% | 0.9302 |
| basic | V5 | NOT ENOUGH INFO | 24 | 88.89% | 100.00% | 0.9412 |
| challenge | A27 | SUPPORTS | 17 | 100.00% | 88.24% | 0.9375 |
| challenge | A27 | REFUTES | 5 | 27.78% | 100.00% | 0.4348 |
| challenge | A27 | NOT ENOUGH INFO | 22 | 90.91% | 45.45% | 0.6061 |
| challenge | V5 | SUPPORTS | 17 | 100.00% | 41.18% | 0.5833 |
| challenge | V5 | REFUTES | 5 | 28.57% | 40.00% | 0.3333 |
| challenge | V5 | NOT ENOUGH INFO | 22 | 90.00% | 40.91% | 0.5625 |

| 数据 | 方法 | gold | 预测S | 预测R | 预测NEI | INVALID（未决/缺失） |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 13 | 0 | 0 | 0 |
| basic | A27 | REFUTES | 0 | 23 | 0 | 0 |
| basic | A27 | NOT ENOUGH INFO | 0 | 0 | 24 | 0 |
| basic | V5 | SUPPORTS | 7 | 0 | 2 | 4 |
| basic | V5 | REFUTES | 0 | 20 | 1 | 2 |
| basic | V5 | NOT ENOUGH INFO | 0 | 0 | 24 | 0 |
| challenge | A27 | SUPPORTS | 15 | 1 | 1 | 0 |
| challenge | A27 | REFUTES | 0 | 5 | 0 | 0 |
| challenge | A27 | NOT ENOUGH INFO | 0 | 12 | 10 | 0 |
| challenge | V5 | SUPPORTS | 7 | 0 | 1 | 9 |
| challenge | V5 | REFUTES | 0 | 2 | 0 | 3 |
| challenge | V5 | NOT ENOUGH INFO | 0 | 5 | 9 | 8 |

| 数据 | 方法 | NEI→R | NEI→S | S→NEI | R→NEI | 未决按gold | 未运行按gold |
|---|---|---|---|---|---|---|---|
| basic | A27 | 0 | 0 | 0 | 0 | {} | {} |
| basic | V5 | 0 | 0 | 2 | 1 | {"SUPPORTS": 4, "REFUTES": 2} | {} |
| challenge | A27 | 12 | 0 | 1 | 0 | {} | {} |
| challenge | V5 | 5 | 0 | 1 | 0 | {"SUPPORTS": 9, "NOT ENOUGH INFO": 8, "REFUTES": 3} | {} |

## 机制与场景组

每个数据集/机制恰好冻结一个组；因此下表同时是按机制及完整group的统计，包含未完成组。

| 数据/机制 | group | 预定题数 | 完成配对 | A27正确 | V5正确 | V5未决 |
|---|---|---|---|---|---|---|
| basic/BOUND | g_e26e5d6db3b5626f | 16 | 16 | 16 | 15 | 1 |
| basic/FUNCTIONAL | g_3de67df163064b7b | 4 | 4 | 4 | 4 | 0 |
| basic/IMPLICATIVE | g_ad492b00d3aa1cd1 | 11 | 11 | 11 | 9 | 0 |
| basic/PLACE | g_7815dde1d465582b | 3 | 3 | 3 | 2 | 1 |
| basic/PLAN | g_c028121037aa9d69 | 5 | 5 | 5 | 5 | 0 |
| basic/RELDATE | g_12e0067f8de17ee6 | 6 | 6 | 6 | 2 | 4 |
| basic/TIMESHIFT | g_1c41e6ca0b24cdc3 | 15 | 15 | 15 | 14 | 0 |
| challenge/AMBIGREF | g_3b8f9bb9621efceb | 5 | 5 | 3 | 4 | 1 |
| challenge/DENIAL | g_8610864a2344d7ec | 8 | 8 | 5 | 1 | 4 |
| challenge/LOOKALIKE | g_915d36e1eecfcae6 | 6 | 6 | 4 | 3 | 1 |
| challenge/PRESUP | g_21a040f0577262ef | 6 | 6 | 3 | 0 | 6 |
| challenge/SETCLOSE | g_300777675f747c85 | 6 | 6 | 6 | 6 | 0 |
| challenge/TEMPSCOPE | g_abdd085764da8b87 | 5 | 5 | 4 | 3 | 1 |
| challenge/UNIQUE | g_eee6bfb6e0ddbde9 | 8 | 8 | 5 | 1 | 7 |

## 节点成本与状态

smoke 的 reused=true 行为旧响应谱系，不计入本次新增用量。客户端秒含节流；服务端秒来自 usage.total_time。

| 阶段 | 节点 | 复用 | 响应 | 输入token | 输出token | 总token | 客户端秒 | 服务端秒 |
|---|---|---|---|---|---|---|---|---|
| fresh | baseline_A27 | False | 104 | 29996 | 4687 | 34683 | 329.93 | 12.25 |
| fresh | generate_F | False | 104 | 55580 | 8252 | 63832 | 1072.07 | 21.05 |
| fresh | generate_T | False | 104 | 49028 | 8039 | 57067 | 1119.35 | 21.21 |
| fresh | verify_F | False | 104 | 85339 | 10088 | 95427 | 3033.10 | 27.48 |
| fresh | verify_T | False | 104 | 80129 | 10019 | 90148 | 3712.38 | 28.09 |
| smoke | bad_candidate_open_target | True | 1 | 597 | 81 | 678 | 3.16 | 0.23 |
| smoke | control | True | 1 | 25 | 3 | 28 | 1.56 | 0.01 |
| smoke | generate_F | False | 6 | 2523 | 333 | 2856 | 17.44 | 0.87 |
| smoke | generate_F | True | 4 | 1678 | 251 | 1929 | 11.39 | 0.67 |
| smoke | generate_T | False | 6 | 2145 | 301 | 2446 | 15.74 | 0.78 |
| smoke | generate_T | True | 4 | 1426 | 174 | 1600 | 11.52 | 0.50 |
| smoke | length_constrained | True | 1 | 26 | 11 | 37 | 2.99 | 0.03 |
| smoke | length_control | True | 1 | 26 | 18 | 44 | 2.57 | 0.04 |
| smoke | sentinel_A27 | True | 1 | 25 | 63 | 88 | 3.06 | 0.13 |
| smoke | sentinel_generator_true | True | 1 | 25 | 45 | 70 | 2.04 | 0.10 |
| smoke | sentinel_verifier_true | True | 1 | 25 | 101 | 126 | 3.32 | 0.23 |
| smoke | target_contradiction | True | 1 | 619 | 105 | 724 | 3.06 | 0.29 |
| smoke | verify_F | False | 7 | 4763 | 601 | 5364 | 308.71 | 1.60 |
| smoke | verify_F | True | 3 | 2092 | 261 | 2353 | 113.52 | 0.71 |
| smoke | verify_T | False | 7 | 4390 | 597 | 4987 | 19.46 | 1.58 |
| smoke | verify_T | True | 3 | 1876 | 247 | 2123 | 49.54 | 0.67 |

同一完整配对子集的成本：

| 方法 | 题数 | 调用数 | 总token | 客户端秒 | 服务端秒 |
|---|---|---|---|---|---|
| A27 | 104 | 104 | 34683 | 329.93 | 12.25 |
| V5 | 104 | 416 | 306474 | 8936.90 | 97.83 |

### 正式验证器决策

| 项目 | 数量 |
|---|---|
| verify_F:WITNESS_VALID | 74 |
| verify_T:WITNESS_VALID | 59 |
| verify_T:CANDIDATE_INVALID | 17 |
| verify_F:TARGET_CONTRADICTS_EVIDENCE | 17 |
| verify_T:TARGET_CONTRADICTS_EVIDENCE | 28 |
| verify_F:CANDIDATE_INVALID | 13 |

### 正式最终状态对

| 项目 | 数量 |
|---|---|
| ('INFEASIBLE', 'FEASIBLE') | 27 |
| ('FEASIBLE', 'FEASIBLE') | 37 |
| ('FEASIBLE', 'UNKNOWN') | 8 |
| ('FEASIBLE', 'INFEASIBLE') | 14 |
| ('UNKNOWN', 'FEASIBLE') | 10 |
| ('INFEASIBLE', 'INFEASIBLE') | 1 |
| ('UNKNOWN', 'UNKNOWN') | 5 |
| ('UNKNOWN', 'INFEASIBLE') | 2 |

### 正式字符限长标记

| 项目 | 数量 |
|---|---|
| verify_F:REASON_LIMIT_HIT:reason | 101 |
| verify_T:REASON_LIMIT_HIT:reason | 95 |
| generate_F:REASON_LIMIT_HIT:target_condition | 2 |
| verify_F:REASON_LIMIT_HIT:evidence_anchor | 1 |
| verify_T:REASON_LIMIT_HIT:evidence_anchor | 1 |

### 实际模型ID

| 项目 | 数量 |
|---|---|
| qwen/qwen3.8-27b | 568 |

### 托管系统指纹

| 项目 | 数量 |
|---|---|
| fp_424cb89518 | 161 |
| fp_21e59ac2de | 254 |
| fp_a1293f40b5 | 152 |
| fp_61e8d148b4 | 1 |

## 调用记账

| 项目 | 值 |
|---|---|
| new_attempts | 549 |
| new_attempt_statuses | {"received": 546, "http_error": 3} |
| new_http_statuses | {"200": 546, "503": 2, "429": 1} |
| new_successful_tokens | 356810 |
| new_charged_tokens_including_unknown_reservations | 370222 |
| first_new_requested_at | "2026-10-24T09:39:17.548474+00:00" |
| last_new_requested_at | "2026-10-26T02:06:59.740773+00:00" |
| last_rate_limit_headers | {"x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-requests": "772", "x-ratelimit-remaining-tokens": "6583", "x-ratelimit-reset-requests": "5h28m19.2s", "x-ratelimit-reset-tokens": "10.627s"} |
| stops | {"fresh": {"reason": "Quota reset exceeds bounded wait; resume this run later", "time": "2026-10-24T11:17:55.237339+00:00", "type": "Halt"}} |

未完成逐题阶段、原始文件哈希、非思考检查及完整指标见 continuation_summary.json；正式逐题预测和审阅队列见 reports/ 下对应运行目录。
