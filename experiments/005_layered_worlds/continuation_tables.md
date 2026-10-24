# 续跑统计表（由原始记录离线生成）

生成时间：2026-10-24T11:19:04.993179+00:00

主要分母为冻结的全部104题。完整配对子集另列，不能替代完整评测；未决和缺失均计错。

## 全部预定样本

| 数据 | 方法 | 正确/分母 | 准确率 | 宏F1 | 三分类覆盖率 | 已给三分类条件准确率 |
|---|---|---|---|---|---|---|
| combined | A27 | 49/104 | 47.12% | 0.6123 | 56.73% | 83.05% |
| combined | V5 | 38/104 | 36.54% | 0.5074 | 43.27% | 84.44% |
| basic | A27 | 34/60 | 56.67% | 0.7357 | 56.67% | 100.00% |
| basic | V5 | 30/60 | 50.00% | 0.6365 | 53.33% | 93.75% |
| challenge | A27 | 15/44 | 34.09% | 0.4384 | 56.82% | 60.00% |
| challenge | V5 | 8/44 | 18.18% | 0.2654 | 29.55% | 61.54% |

| 数据 | 方法 | 类别 | 支持数 | 精确率 | 召回率 | F1 |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 13 | 100.00% | 69.23% | 0.8182 |
| basic | A27 | REFUTES | 23 | 100.00% | 56.52% | 0.7222 |
| basic | A27 | NOT ENOUGH INFO | 24 | 100.00% | 50.00% | 0.6667 |
| basic | V5 | SUPPORTS | 13 | 100.00% | 38.46% | 0.5556 |
| basic | V5 | REFUTES | 23 | 100.00% | 56.52% | 0.7222 |
| basic | V5 | NOT ENOUGH INFO | 24 | 85.71% | 50.00% | 0.6316 |
| challenge | A27 | SUPPORTS | 17 | 100.00% | 47.06% | 0.6400 |
| challenge | A27 | REFUTES | 5 | 30.77% | 80.00% | 0.4444 |
| challenge | A27 | NOT ENOUGH INFO | 22 | 75.00% | 13.64% | 0.2308 |
| challenge | V5 | SUPPORTS | 17 | 100.00% | 17.65% | 0.3000 |
| challenge | V5 | REFUTES | 5 | 20.00% | 20.00% | 0.2000 |
| challenge | V5 | NOT ENOUGH INFO | 22 | 80.00% | 18.18% | 0.2963 |

| 数据 | 方法 | gold | 预测S | 预测R | 预测NEI | INVALID（未决/缺失） |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 9 | 0 | 0 | 4 |
| basic | A27 | REFUTES | 0 | 13 | 0 | 10 |
| basic | A27 | NOT ENOUGH INFO | 0 | 0 | 12 | 12 |
| basic | V5 | SUPPORTS | 5 | 0 | 2 | 6 |
| basic | V5 | REFUTES | 0 | 13 | 0 | 10 |
| basic | V5 | NOT ENOUGH INFO | 0 | 0 | 12 | 12 |
| challenge | A27 | SUPPORTS | 8 | 1 | 1 | 7 |
| challenge | A27 | REFUTES | 0 | 4 | 0 | 1 |
| challenge | A27 | NOT ENOUGH INFO | 0 | 8 | 3 | 11 |
| challenge | V5 | SUPPORTS | 3 | 0 | 1 | 13 |
| challenge | V5 | REFUTES | 0 | 1 | 0 | 4 |
| challenge | V5 | NOT ENOUGH INFO | 0 | 4 | 4 | 14 |

| 数据 | 方法 | NEI→R | NEI→S | S→NEI | R→NEI | 未决按gold | 未运行按gold |
|---|---|---|---|---|---|---|---|
| basic | A27 | 0 | 0 | 0 | 0 | {} | {"SUPPORTS": 4, "REFUTES": 10, "NOT ENOUGH INFO": 12} |
| basic | V5 | 0 | 0 | 2 | 0 | {"SUPPORTS": 2} | {"SUPPORTS": 4, "REFUTES": 10, "NOT ENOUGH INFO": 12} |
| challenge | A27 | 8 | 0 | 1 | 0 | {} | {"NOT ENOUGH INFO": 11, "SUPPORTS": 7, "REFUTES": 1} |
| challenge | V5 | 4 | 0 | 1 | 0 | {"SUPPORTS": 5, "NOT ENOUGH INFO": 3, "REFUTES": 3} | {"SUPPORTS": 8, "NOT ENOUGH INFO": 11, "REFUTES": 1} |

## 已完成配对子集（描述性）

| 数据 | 方法 | 正确/分母 | 准确率 | 宏F1 | 三分类覆盖率 | 已给三分类条件准确率 |
|---|---|---|---|---|---|---|
| combined | A27 | 49/58 | 84.48% | 0.8505 | 100.00% | 84.48% |
| combined | V5 | 38/58 | 65.52% | 0.7258 | 77.59% | 84.44% |
| basic | A27 | 34/34 | 100.00% | 1.0000 | 100.00% | 100.00% |
| basic | V5 | 30/34 | 88.24% | 0.8791 | 94.12% | 93.75% |
| challenge | A27 | 15/24 | 62.50% | 0.6134 | 100.00% | 62.50% |
| challenge | V5 | 8/24 | 33.33% | 0.4074 | 54.17% | 61.54% |

| 数据 | 方法 | 类别 | 支持数 | 精确率 | 召回率 | F1 |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 9 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | REFUTES | 13 | 100.00% | 100.00% | 1.0000 |
| basic | A27 | NOT ENOUGH INFO | 12 | 100.00% | 100.00% | 1.0000 |
| basic | V5 | SUPPORTS | 9 | 100.00% | 55.56% | 0.7143 |
| basic | V5 | REFUTES | 13 | 100.00% | 100.00% | 1.0000 |
| basic | V5 | NOT ENOUGH INFO | 12 | 85.71% | 100.00% | 0.9231 |
| challenge | A27 | SUPPORTS | 9 | 100.00% | 88.89% | 0.9412 |
| challenge | A27 | REFUTES | 4 | 30.77% | 100.00% | 0.4706 |
| challenge | A27 | NOT ENOUGH INFO | 11 | 100.00% | 27.27% | 0.4286 |
| challenge | V5 | SUPPORTS | 9 | 100.00% | 33.33% | 0.5000 |
| challenge | V5 | REFUTES | 4 | 20.00% | 25.00% | 0.2222 |
| challenge | V5 | NOT ENOUGH INFO | 11 | 80.00% | 36.36% | 0.5000 |

| 数据 | 方法 | gold | 预测S | 预测R | 预测NEI | INVALID（未决/缺失） |
|---|---|---|---|---|---|---|
| basic | A27 | SUPPORTS | 9 | 0 | 0 | 0 |
| basic | A27 | REFUTES | 0 | 13 | 0 | 0 |
| basic | A27 | NOT ENOUGH INFO | 0 | 0 | 12 | 0 |
| basic | V5 | SUPPORTS | 5 | 0 | 2 | 2 |
| basic | V5 | REFUTES | 0 | 13 | 0 | 0 |
| basic | V5 | NOT ENOUGH INFO | 0 | 0 | 12 | 0 |
| challenge | A27 | SUPPORTS | 8 | 1 | 0 | 0 |
| challenge | A27 | REFUTES | 0 | 4 | 0 | 0 |
| challenge | A27 | NOT ENOUGH INFO | 0 | 8 | 3 | 0 |
| challenge | V5 | SUPPORTS | 3 | 0 | 1 | 5 |
| challenge | V5 | REFUTES | 0 | 1 | 0 | 3 |
| challenge | V5 | NOT ENOUGH INFO | 0 | 4 | 4 | 3 |

| 数据 | 方法 | NEI→R | NEI→S | S→NEI | R→NEI | 未决按gold | 未运行按gold |
|---|---|---|---|---|---|---|---|
| basic | A27 | 0 | 0 | 0 | 0 | {} | {} |
| basic | V5 | 0 | 0 | 2 | 0 | {"SUPPORTS": 2} | {} |
| challenge | A27 | 8 | 0 | 0 | 0 | {} | {} |
| challenge | V5 | 4 | 0 | 1 | 0 | {"SUPPORTS": 5, "NOT ENOUGH INFO": 3, "REFUTES": 3} | {} |

## 机制与场景组

每个数据集/机制恰好冻结一个组；因此下表同时是按机制及完整group的统计，包含未完成组。

| 数据/机制 | group | 预定题数 | 完成配对 | A27正确 | V5正确 | V5未决 |
|---|---|---|---|---|---|---|
| basic/BOUND | g_e26e5d6db3b5626f | 16 | 16 | 16 | 15 | 1 |
| basic/FUNCTIONAL | g_3de67df163064b7b | 4 | 4 | 4 | 4 | 0 |
| basic/IMPLICATIVE | g_ad492b00d3aa1cd1 | 11 | 11 | 11 | 9 | 0 |
| basic/PLACE | g_7815dde1d465582b | 3 | 3 | 3 | 2 | 1 |
| basic/PLAN | g_c028121037aa9d69 | 5 | 0 | 0 | 0 | 0 |
| basic/RELDATE | g_12e0067f8de17ee6 | 6 | 0 | 0 | 0 | 0 |
| basic/TIMESHIFT | g_1c41e6ca0b24cdc3 | 15 | 0 | 0 | 0 | 0 |
| challenge/AMBIGREF | g_3b8f9bb9621efceb | 5 | 5 | 3 | 4 | 1 |
| challenge/DENIAL | g_8610864a2344d7ec | 8 | 8 | 5 | 1 | 4 |
| challenge/LOOKALIKE | g_915d36e1eecfcae6 | 6 | 6 | 4 | 3 | 1 |
| challenge/PRESUP | g_21a040f0577262ef | 6 | 5 | 3 | 0 | 5 |
| challenge/SETCLOSE | g_300777675f747c85 | 6 | 0 | 0 | 0 | 0 |
| challenge/TEMPSCOPE | g_abdd085764da8b87 | 5 | 0 | 0 | 0 | 0 |
| challenge/UNIQUE | g_eee6bfb6e0ddbde9 | 8 | 0 | 0 | 0 | 0 |

## 节点成本与状态

smoke 的 reused=true 行为旧响应谱系，不计入本次新增用量。客户端秒含节流；服务端秒来自 usage.total_time。

| 阶段 | 节点 | 复用 | 响应 | 输入token | 输出token | 总token | 客户端秒 | 服务端秒 |
|---|---|---|---|---|---|---|---|---|
| fresh | baseline_A27 | False | 59 | 17524 | 2513 | 20037 | 154.83 | 6.93 |
| fresh | generate_F | False | 59 | 32038 | 4232 | 36270 | 922.67 | 11.14 |
| fresh | generate_T | False | 59 | 28321 | 4488 | 32809 | 561.99 | 12.48 |
| fresh | verify_F | False | 58 | 47141 | 5456 | 52597 | 2175.76 | 15.04 |
| fresh | verify_T | False | 58 | 44622 | 5384 | 50006 | 1674.68 | 15.84 |
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
| A27 | 58 | 58 | 19242 | 151.97 | 6.78 |
| V5 | 58 | 232 | 169500 | 5217.85 | 53.80 |

### 正式验证器决策

| 项目 | 数量 |
|---|---|
| verify_F:WITNESS_VALID | 41 |
| verify_T:WITNESS_VALID | 33 |
| verify_T:TARGET_CONTRADICTS_EVIDENCE | 19 |
| verify_F:TARGET_CONTRADICTS_EVIDENCE | 10 |
| verify_F:CANDIDATE_INVALID | 7 |
| verify_T:CANDIDATE_INVALID | 6 |

### 正式最终状态对

| 项目 | 数量 |
|---|---|
| ('INFEASIBLE', 'FEASIBLE') | 18 |
| ('FEASIBLE', 'FEASIBLE') | 19 |
| ('FEASIBLE', 'UNKNOWN') | 6 |
| ('FEASIBLE', 'INFEASIBLE') | 8 |
| ('UNKNOWN', 'FEASIBLE') | 4 |
| ('INFEASIBLE', 'INFEASIBLE') | 1 |
| ('UNKNOWN', 'UNKNOWN') | 1 |
| ('UNKNOWN', 'INFEASIBLE') | 1 |

### 正式字符限长标记

| 项目 | 数量 |
|---|---|
| verify_F:REASON_LIMIT_HIT:reason | 55 |
| verify_T:REASON_LIMIT_HIT:reason | 52 |
| verify_F:REASON_LIMIT_HIT:evidence_anchor | 1 |
| verify_T:REASON_LIMIT_HIT:evidence_anchor | 1 |
| generate_F:REASON_LIMIT_HIT:target_condition | 1 |

### 实际模型ID

| 项目 | 数量 |
|---|---|
| qwen/qwen3.8-27b | 341 |

### 托管系统指纹

| 项目 | 数量 |
|---|---|
| fp_424cb89518 | 98 |
| fp_21e59ac2de | 160 |
| fp_a1293f40b5 | 82 |
| fp_61e8d148b4 | 1 |

## 调用记账

| 项目 | 值 |
|---|---|
| new_attempts | 321 |
| new_attempt_statuses | {"received": 319, "http_error": 2} |
| new_http_statuses | {"200": 319, "503": 1, "429": 1} |
| new_successful_tokens | 207372 |
| new_charged_tokens_including_unknown_reservations | 217980 |
| first_new_requested_at | "2026-10-24T09:39:17.548474+00:00" |
| last_new_requested_at | "2026-10-24T11:17:51.501812+00:00" |
| last_rate_limit_headers | {"retry-after": "239", "x-ratelimit-limit-requests": "1000", "x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-requests": "680", "x-ratelimit-remaining-tokens": "8000", "x-ratelimit-reset-requests": "7h40m48s", "x-ratelimit-reset-tokens": "1ms"} |
| stops | {"fresh": {"reason": "Quota reset exceeds bounded wait; resume this run later", "time": "2026-10-24T11:17:55.237339+00:00", "type": "Halt"}} |

未完成逐题阶段、原始文件哈希、非思考检查及完整指标见 continuation_summary.json；正式逐题预测和审阅队列见 reports/ 下对应运行目录。
