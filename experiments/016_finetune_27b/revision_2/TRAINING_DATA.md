# 审核与训练数据冻结结果

902 条初稿全部由同一未微调 BF16 27B 和原始 A0 提示词生成，Agent 已逐条核对证据、陈述、金标与初稿。原始初稿和修改历史已冻结。

最终排除 26 个完整场景组、174 条记录，保留 728 条、98 组用于三个种子的共同训练。没有补样本，没有修改原始金标。最长完整训练输入为 851 tokens，固定序列上限 1536，无截断。

| 集合 | 机制 | 原候选条数 | 保留条数 |
|---|---|---:|---:|
| basic | BOUND | 128 | 128 |
| basic | FUNCTIONAL | 32 | 32 |
| basic | IMPLICATIVE | 88 | 44 |
| basic | PLACE | 24 | 24 |
| basic | PLAN | 40 | 35 |
| basic | RELDATE | 48 | 12 |
| basic | TIMESHIFT | 120 | 120 |
| challenge | AMBIGREF | 50 | 50 |
| challenge | DENIAL | 88 | 88 |
| challenge | LOOKALIKE | 81 | 81 |
| challenge | PRESUP | 69 | 0 |
| challenge | SETCLOSE | 36 | 36 |
| challenge | TEMPSCOPE | 35 | 30 |
| challenge | UNIQUE | 63 | 48 |

PRESUP 的全部训练场景均被整组排除：重复事件存在先前发生，但当前证据没有保证它发生于指定日历年之前。该保守口径及其他排除标准详见 REVIEW_POLICY.md；验证和保留集仍按冻结原标签评分。这限制了本实验的机制覆盖，不能隐去或据后续成绩反向修改。

## 排除依据

以下为每个排除场景中至少一条触发记录的原审核理由；同组其余记录也均已审核。

- `basic/g_53f60fc0f201baca`，触发 ID `e_43cb01988bc4048b`：Read evidence, claim and draft. The arithmetic places a VHS release in 1999, but the evidence does not say first or only VHS release, leaving an earlier 1998 release or another edition possible. Gold REFUTES depends on an unstated unique-release reading. Exclude the full training scenario consistently with other nonexclusive date-event conflicts.

- `basic/g_7c0199f0b3079eb1`，触发 ID `e_127f53df37ea5040`：Read evidence, claim and draft. The evidence concerns a delayed memorial service, but the claim literally says the person Yahya Sinwar was held on the date. The draft silently substitutes the service for the person; custody or detention is not contradicted by the evidence. Gold REFUTES is ambiguous because the generated claim loses the event referent. Exclude the whole training group without changing the source.

- `basic/g_81a2a8fedb01bd4d`，触发 ID `e_44818bc07b649d70`：Read evidence, claim and draft. The supplied sequence places tariff orders by 2032, but signing tariff orders can recur and the evidence does not exclude additional orders in 2033. The draft assumes a unique signing event without an exclusivity statement. Gold REFUTES is ambiguous; exclude the entire training scenario without relabeling.

- `basic/g_8349e3674fde8df6`，触发 ID `e_017e74f377be0e51`：The festival could recur: hosting it within two years of 2012 does not exclude another occurrence in 2015. No unique or single-occurrence event is specified, so REFUTES depends on an unstated restriction; exclude this training group without changing source labels.

- `basic/g_8e75b06c03b60d2c`，触发 ID `e_98cfe196f4fddeda`：Read evidence, claim and draft. The described nomination is by 2023, but nominations can recur and no restriction excludes another in 2024. Gold REFUTES assumes a unique nomination without evidence. Exclude the entire scenario consistently with the other nomination-date ambiguity.

- `basic/g_909be1af27281019`，触发 ID `e_e8c27af129142adb`：Refusing to win an award is ambiguous between declining acceptance and the actual award outcome. Gold REFUTES is not securely entailed; exclude the entire group consistently with other refused-to-win groups.

- `basic/g_996152ac6d8828af`，触发 ID `e_a5a65692e8e02715`：Read the full draft and checked 2017 plus two years, then within three years. The evidence places an MVP reclamation by 2022 but does not make it the only reclamation or exclude another in 2023. Gold REFUTES depends on an unstated uniqueness restriction. Exclude the whole training scenario without relabeling.

- `basic/g_ad492b00d3aa1cd1`，触发 ID `e_0644dfaf3a1f2f82`：Read the evidence, claim and draft. Refusing to win an award describes a refusal, but does not establish that the award was not conferred; the evidence gives no outcome. Gold REFUTES is ambiguous for this award context. Exclude the whole training scenario group; do not relabel or replenish it.

- `basic/g_cc652179cb555f41`，触发 ID `e_25d357255e096e66`：Read evidence, claim and draft. The arithmetic locates a nomination in 2032, but receiving a nomination is not stated to be unique and does not exclude another nomination in 2031. No award body or exclusive nomination restriction is supplied. Gold REFUTES is ambiguous; exclude the whole scenario without relabeling.

- `basic/g_cdffeefd2b10876b`，触发 ID `e_1e22fb9b757ab8ee`：Read evidence, claim and draft. Refusing to win does not establish the award outcome; the draft conflates winning with accepting an award. Gold REFUTES is ambiguous in this context. Exclude the whole training scenario, consistently with the other refused-to-win award case.

- `basic/g_dcc2af7ec1230ff0`，触发 ID `e_c0b6f409da582126`：Declining to win an election is semantically ambiguous: refusing a desired outcome is not necessarily losing it. Exclude this entire election-outcome group rather than train a forced contradiction.

- `challenge/g_1905b1efc0b0558a`，触发 ID `e_424df3b7bbdc6212`：Again in 2023 entails a prior winning event, but the evidence does not date that event before the calendar year 2023. Without importing an annual-ceremony constraint, it could be earlier in 2023. Exclude the entire group consistently with other event-versus-year ambiguities.

- `challenge/g_1ddc186f18e2e037`，触发 ID `e_0356308a83a570cb`：A second Iron Cross award in 1918 entails an earlier award, but not necessarily an award before the calendar year 1918; the first could also be in 1918. No annual or different-year constraint is stated. Exclude this entire group rather than force gold SUPPORTS.

- `challenge/g_21a040f0577262ef`，触发 ID `e_f491d220d45d65f8`：Read full passage. Again in 1957 establishes a preceding Pulitzer win but does not specify that it occurred before calendar year 1957 without an unstated award-frequency constraint. Exclude entire group consistently with other recurrence cases.

- `challenge/g_280bf26971e25ba6`，触发 ID `e_6f7686136f3a07bc`：A regional amateur tournament win does not identify the Women's German Amateur Football Championship or explicitly exclude that title. Gold REFUTES depends on unstated participation/eligibility assumptions; winning can also refer to coaching or team affiliation. Exclude the entire group rather than add those assumptions.

- `challenge/g_3ca19839c010acc4`，触发 ID `e_84f6edaff467c12a`：Read full passage. A second win in 2024 establishes an earlier win but does not specify that it was before the calendar year 2024. Gold SUPPORTS requires an unstated annual-award restriction. Exclude the entire group under the same recurrence criterion.

- `challenge/g_4597b8c253a08217`，触发 ID `e_3b8dde7b4ce38661`：Again in 2026 presupposes a previous receipt but does not date that receipt before the calendar year 2026 without an unstated distinct-year constraint. Exclude the whole group consistently with other recurrence-versus-year ambiguities.

- `challenge/g_4606187f0afe2aec`，触发 ID `e_5b7a0de8d67dd76a`：The passage calls the film a 2002 film but describes 2003 as its release year, and the award sentence does not say first or only win. Gold REFUTES requires resolving conflicting release chronology or importing award eligibility rules. Exclude the entire group rather than repair the evidence.

- `challenge/g_5b16901545c2a9e3`，触发 ID `e_9a118416f10bae36`：Read full passage. A second Grammy win in 2012 entails an earlier win but does not locate it before calendar year 2012 without an unstated annual-award constraint. Exclude entire group consistently with the recurrence criterion.

- `challenge/g_5dd8394293449d1b`，触发 ID `e_c1bee6885fb5e730`：Read full passage and draft. Again in 2008 entails a prior medal event but does not place it before calendar year 2008 without an unstated Olympic-frequency restriction. Exclude entire group consistently with other recurrence cases; do not import another row's four-year rule.

- `challenge/g_62607122e29704f5`，触发 ID `e_453e891521e86c37`：A second award in 1999 establishes a previous award event, but not necessarily an award before the calendar year 1999. The evidence supplies no distinct-year constraint. Exclude this whole group consistently with the other recurrence-versus-calendar-year ambiguities.

- `challenge/g_8417e4f50f9fb072`，触发 ID `e_6f26b81b2c0b0dde`：Again in 2013 entails an earlier winning event but not necessarily an event before the calendar year 2013. The text supplies no distinct-year restriction; exclude the entire group under the same recurrence criterion.

- `challenge/g_858d4d6925c69386`，触发 ID `e_58d49da5cf4fec27`：Once more in 2017 establishes a prior winning event but does not date it before the calendar year 2017. No election-frequency or distinct-year constraint is stated. Exclude the whole group under the same temporal-granularity criterion.

- `challenge/g_a14e2b98723c8861`，触发 ID `e_44f08135d0c69bff`：Co-founder is normally a lasting historical status, not a post that ends like a CEO tenure; took office as co-founder makes the intended temporal relation ambiguous. Gold NEI depends on treating this status as an ordinary employment term. Exclude the entire group rather than impose that reading.

- `challenge/g_ab7dbaf82d843d29`，触发 ID `e_3de291bdad136c41`：The sentence truncates The Miz to the bare article The as its subject. Gold SUPPORTS requires silently repairing the input or treating an article as a name. Exclude the entire malformed-reference group; preserve the dissenting initial draft.

- `challenge/g_cd19f56a1c76ff96`，触发 ID `e_3cc3c4dfe687a847`：Once more in 2018 establishes a prior award event, but that event is not explicitly dated before the calendar year 2018. Exclude the whole group under the same temporal-granularity criterion, without importing ceremony frequency.

## 冻结身份

- training_freeze.json SHA-256：`50bea167e2ec5e748ce96c17aa23f74d694272d81cf30deb8cf64324b7f0a4dc`
- reviews.jsonl SHA-256：`4337863cce09786f8fe9dfbe8a5425595543a72b81a26eece96c26e855de06e1`
- 初稿远端校验：902 条回答及 1 份运行身份文件全部匹配。
- 训练开始之前冻结；本文件不含验证或保留评估结果。
