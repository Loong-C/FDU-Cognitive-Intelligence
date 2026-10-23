# 第四轮真实结果：27B非思考模式下，双世界没有取得总体收益

2026-10-23 已完成 **294/294 个正式回答**，运行ID为 `pilot_groq_qwen38_27b_nonthink_v4_r2`。
基于指定的 `codex/14b-nonthink-v3` / `a99a5d8`，没有从main开始，没有更改历史数据、gold或v2提示词。
模型为GroqCloud的 `qwen/qwen3.8-27b`，显式 `reasoning_effort=none`。

**直接分类A27表现改善，但冻结的双世界B27明显损伤REFUTES能力。** 挑战集NEI召回提高，却不足以抵消R类损失；基础集准确率和NEI召回均下降。NEI→REFUTES下降不能单独解读为推理改善，因为许多错误转成了SUPPORTS或INVALID_LOGIC。

[完整兼容报告](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/pilot_report.md)包括混淆矩阵、分机制表、结构有效率和成本；[逐题预测](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/predictions.csv)、[配对变化](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/changed_predictions.csv)及[脱敏原始记录](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/api_records.jsonl)可复算全部成绩。

## 同一模型内的A27/B27比较

沿用第三轮开发pilot：challenge 87题/14个完整group，basic 60题/7个完整group；同序ID哈希和manifest哈希均通过核对。内部臂名仍为A2/B2，显示A27/B27。未使用C2示例或封存test推理。格式、逻辑无效均计错，分母为全部应测样本；B标签只由两个世界状态确定，不从理由猜标签。

| 数据集 | 方法 | 正确/全部 | 准确率 | 宏F1 | S召回 | R召回 | NEI召回 |
|---|---|---:|---:|---:|---:|---:|---:|
| challenge | A27 | 56/87 | 64.37% | 0.6258 | 93.94% | 85.71% | 32.50% |
| challenge | B27 | 52/87 | 59.77% | 0.4495 | 96.97% | **0.00%** | 50.00% |
| basic | A27 | 58/60 | 96.67% | 0.9710 | 100.00% | 100.00% | 91.30% |
| basic | B27 | 33/60 | 55.00% | 0.5608 | 100.00% | **0.00%** | 82.61% |

- challenge：B27−A27为 **−4.60个百分点**，11题错→对、15题对→错。NEI多对7题、S多对1题，R少对12题。
- basic：B27−A27为 **−41.67个百分点**，0题错→对、25题对→错。S正确数不变，R少对23题、NEI少对2题。
- B27在全部37道gold为REFUTES的题上 **0道正确**。所有题都有真实且结构合规的回答，不是缺失或接口失败。

| 数据集/方法 | NEI→R | NEI→S | NEI→INVALID | S→NEI | R→NEI | R→S | R→INVALID |
|---|---:|---:|---:|---:|---:|---:|---:|
| challenge A27 | 27 | 0 | 0 | 1 | 2 | 0 | 0 |
| challenge B27 | 1 | 17 | 2 | 1 | 1 | 9 | 4 |
| basic A27 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| basic B27 | 0 | 4 | 0 | 0 | 0 | 4 | 19 |

challenge原先27道NEI→R中，只有9道在B27被纠正为NEI；basic原先2道NEI→R均没有被纠正为NEI。误伤不能只看S→NEI和R→NEI，本轮最大的损失是R→S和R→INVALID。

## 分机制、group与历史对照

| challenge机制 | A27正确 | B27正确 | 每条件题数 |
|---|---:|---:|---:|
| AMBIGREF | 6 | 10 | 10 |
| DENIAL | 10 | 7 | 16 |
| LOOKALIKE | 7 | 8 | 12 |
| PRESUP | 7 | 6 | 12 |
| SETCLOSE | 10 | 7 | 12 |
| TEMPSCOPE | 8 | 8 | 10 |
| UNIQUE | 8 | 6 | 15 |

challenge的14个group中，B27净改善3组、下降6组、不变5组；basic的7组中，改善0组、下降6组、不变1组。basic的BOUND从16/16降至7/16，TIMESHIFT从13/15降至6/15。完整分母见[分组表](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/metrics_by_group.csv)。

| 数据集 | 4B A/B正确数 | 14B A/B正确数 | 27B A/B正确数 |
|---|---|---|---|
| challenge | 50 / 55 | 53 / 69 | 56 / 52 |
| basic | 42 / 34 | 46 / 48 | 58 / 33 |

相对14B，A27多对3道challenge和12道basic；B27分别少对17道和15道。跨模型配对ID见[upgrade_comparison.json](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/upgrade_comparison.json)。这只是描述性比较：模型代际、训练、量化、模板实现和后端不同，不能把变化归因于参数规模。group内变体相关，不作逐题独立性假设或显著性宣称；basic冻结gold的原始人类审核状态仍为pending。

## 结构与语义复核

**294/294的JSON、字段和协议验证通过。** B27有25条双IMPOSSIBLE：challenge 6条、basic 19条，逻辑组合有效率分别93.10%和68.33%。A27无无效输出。无max_tokens截断；B27有17条回答至少一个理由达到320字符（challenge 10、basic 7），可见句中/词中结束。字符上限触顶和token截断分开统计。

| 预指定ID/案例 | B14 | B27 | 语义结论 |
|---|---|---|---|
| `e_5c7b1b9b012be799` / 肯定Salem | S | S | P/I及明确居住证据一致。 |
| `e_83ecbf82546d00f0` / 任期覆盖2026 | S | S | 正确使用2023–2027包含2026。 |
| `e_e362e2444350daca` / 124999与125000 | NEI | INVALID | 不再引入四舍五入，但数字比较正确后仍填I/I，最终仍错。 |
| `e_d936aaf07ff8dcd7` / only one | R | S | 真世界改写家庭范围，假世界理由承认排他性却填IMPOSSIBLE。 |

四题B27为2/4，B14为3/4，不能代表四类错误总体发生率。完整A/B及4B/14B/27B原始理由见[typical_errors.csv](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/typical_errors.csv)。

按第三轮相同规则固定复核18题（每数据集每gold标签的前三个ID），明确的理由/世界状态方向冲突为 **B14 2/18、B27 10/18**。这是助手语义复核，不是外部人类审核或随机抽样总体估计。

- 数学：`e_15706bbc1df121d5`正确理解up to 125010排除more than 125010，却将假世界也标IMPOSSIBLE；`e_3180992e4dc5cc71`两个理由逐字相同，均证明claim为假，却输出I/I。
- 时间：`e_00a14eca36dfd42e`纠正14B在覆盖区间内假设提前卸任的反例；`e_365682368482ff06`正确算出2017+2+4=2023，纠正旧模型改写事实，但理由末句措辞仍内部矛盾。
- 开放世界：`e_09a8bae1417a4f20`把attempted误作失败蕴涵，又将支持claim为假的理由标为IMPOSSIBLE；`e_09f65643cf9bd6b1`自行假设唯一获胜者；`e_1227e8efede9f7c4`放宽before 2019的条件。
- 正确标签不保证正确说明：`e_11b9a984df88d017`为正确P/P，但真世界理由举124991/125001，假世界理由举125000，两个见证对调。这种情况及日期题的内部措辞错误单列，未计入上述10条直接状态冲突。

**不能认定非法反例已全面减少。** 两个旧时间/日期反例被修正，但仍存在改写disproven、家庭范围、时间条件和世界目标的说明；更突出的退步是混淆“claim为假”和“假世界不可能”。没有据此修复标签或重新生成。逐条意见及原始哈希见[review_notes.json](review_notes.json)和[复核CSV](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/reason_consistency_review.csv)。

## 推理成本和免费额度

| 数据集/方法 | 完成/HTTP尝试 | 输入token | 输出token | 总token | 客户端累计秒（含节流） | 服务端处理秒 |
|---|---:|---:|---:|---:|---:|---:|
| challenge A27 | 87/88 | 33,678 | 3,722 | 37,400 | 824.02 | 10.28 |
| challenge B27 | 87/89 | 53,775 | 9,620 | 63,395 | 2,019.23 | 23.47 |
| basic A27 | 60/60 | 11,867 | 2,922 | 14,789 | 214.89 | 7.05 |
| basic B27 | 60/60 | 25,727 | 7,029 | 32,756 | 644.23 | 16.39 |

正式合计 **148,340 token**（输入125,047、输出23,293），294个唯一成功回答、297次HTTP尝试，含3次503重试。B27总token为96,151，A27为52,189，约1.84倍；challenge为1.70倍，basic为2.21倍。第三轮同批143,254 token，本轮高约3.55%；不同tokenizer下仍只是描述性成本比较。

正式跨度为北京时间 **19:17:52–20:20:36，约62.73分钟**；客户端累计61.71分钟包括节流、退避、网络与处理。成功响应的服务端`usage.total_time`合计57.19秒，与客户端口径不同，亦不含失败请求未知处理时间。免费额度等待不能当作模型推理速度，托管/本地硬件差异也不能归因于参数量。

全阶段305个成功回答：294正式、5技术探针、6虚构smoke。r2共309次HTTP尝试（4次503）；加上r1两次403，共311次。成功响应usage合计 **150,855 token**，加失败保守预留后账本为 **167,639 token**，低于本地180,000 token/800请求保护值和Free Plan参考200,000 token/1,000请求。失败请求无usage，预留不是实际用量或账单。

用户确认Free Plan，实际响应头显示1000 RPD、8000 TPM；未升级套餐、换模型或启用付费服务。**本次记录在免费参考额度内，但未查询账单或全组织TPD余额。** 响应头无TPD剩余，不能声称独立核验零费用。见[脱敏API诊断](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/api_diagnostics.json)。

## 非思考与复现边界

全部请求显式none、temperature=0、seed=42、stream=false、max_completion_tokens=1024；A/B统一strict Schema及maxLength=320。5次真实技术对照验证了服务端字段/枚举/长度约束，6次smoke通过后才进入dev接入。前10题×两组的20次调用直接保留为正式前缀，无额外重生成或挑答案。

**按Groq API非思考模式执行，可观察检查全部通过**：返回模型ID均匹配，未见reasoning字段或think内容。服务端没有reasoning token分项及内部模板/计算检查接口，因此不额外声称独立证明内部思考token为零。本地权重SHA、GPU卸载、DLL和/apply-template计数均N/A。

两方法均出现三个fingerprint：`fp_21e59ac2de`、`fp_424cb89518`、`fp_a1293f40b5`，分布见[costs.json](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/costs.json)。模型ID固定不等于后端逐位固定；seed被接受不保证确定性。严格与A组Q8_0比较仍需匹配模型版本、可验证权重/量化、模板/tokenizer、解码/输出协议、数据顺序和后端条件；Groq不公开这些本地身份信息，本轮不能提供严格等价证明。

## 验证

完整 **109项测试通过**。独立审计重新检查294个原始回答、Schema/标签映射、精确输入、指纹、技术探针、数据/提示词哈希，以及混淆矩阵、召回、宏F1、配对ID和297个正式HTTP尝试唯一性。见[独立统计审计](reports/pilot_groq_qwen38_27b_nonthink_v4_r2/independent_statistics_audit.json)、[测试凭据](test_validation.json)和[执行日志](EXECUTION_LOG.md)。

两次直连403、系统代理接入和r2的503均保留，r1失败未伪装为推理结果。密钥只用于进程环境和固定Groq HTTPS认证头；`.env.local`被忽略且未跟踪。提交前扫描实际密钥值及密钥模式，历史v1/v2/v3数据、报告与提示词保持不变。
