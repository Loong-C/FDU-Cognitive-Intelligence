"""Persist explicit source/AST inspection notes; no grading from gold or label match."""
import json
from ab_factcheck.common import ROOT, atomic_json, file_hash
from ab_factcheck.symbolic_z3.experiment import EXPERIMENT

# Entered after directly reading each original source and its raw completion.
# Index refers to frozen hash order, not labels. The original output is untouched.
REVIEWS = {
    0: (False, ["type_error", "omitted_constraint", "scope_error"],
        "年份 2005/2010 被声明为无取值 Int 常量，违反 DSL，且没有与数字值的等式；兄弟未显式不等，不定奖项没有存在量词。修正保留各自独立奖项见证，不推出 Donald 未获奖。"),
    1: (False, ["type_error", "scope_error", "omitted_constraint"],
        "attended 声明 3 参数却传入 4 个，won_regional_theater_award 声明 2 参数却传入 3 个；把两个人塞入同一次谓词应用，未分配 both。修正为两条独立存在获奖事实。"),
    2: (False, ["entity_confusion", "scope_error", "omitted_constraint"],
        "把原文 a National Book Award 与 claim 的不定奖项共用 nationalBookAward 常量，丢失独立存在作用域；兄弟间无不等约束。标签碰巧 NEI，但 AST 并非严格忠实。"),
    3: (False, ["type_error", "scope_error", "omitted_constraint"],
        "status=UNSUPPORTED 却保留非空声明/Evidence/Claim；Claim 使用未声明 negotiated，Evidence 引用未绑定变量；year 存在量化但未限制为 2005，false 谓词未连接到事件否定。原文明确调查证伪，应独立否定被报道命题。"),
    4: (False, ["unsupported_misuse", "omitted_constraint"],
        "模型因报道未得到证实而返回 UNSUPPORTED；否认事实和开放的被报道命题可在 DSL 中直接表示，证据不能判定真伪不等于不能形式化。"),
    5: (False, ["type_error", "scope_error"],
        "Claim 声明 shelter 为存在变量，却用 const 引用；Evidence 也用未声明 shelter 常量。报道内容与实际捐赠区分的方向正确，但实体绑定使 AST 无法编译。"),
    6: (False, ["omitted_constraint", "scope_error"],
        "保留了表亲和获奖者方向，没有补负事实；但 cousinOf 未携带不等语义，两个名字仍可同指，不定锦标赛也没有显式存在见证。严格形式化不完整，尽管所得 NEI 合理。"),
    7: (False, ["entity_confusion", "scope_error", "omitted_constraint"],
        "把两人各获一个该类别奖项固定为同一个 Award 常量，且未区分两名实体；both 的正事实保留，S 标签正确，但奖项实例/类别及存在量词被合并。"),
    8: (False, ["type_error", "scope_error"],
        "Like 的两人获奖含义提取正确，但将不等运算写成未声明的 pred(name=ne)，而非 op=ne，无法编译；不定奖项仍未使用存在量词。"),
    9: (False, ["scope_error", "added_constraint"],
        "exists y 的 y 未被使用；won_before 是未定义时间关系的独立谓词。once more 只保证较早一次，模型直接断言早于 2023 年；原文允许 2023 年内的先前一次。修正用事件时间顺序并保留这项年粒度歧义。"),
    10: (False, ["type_error", "scope_error", "omitted_constraint"],
        "Evidence 含自由变量 y、未声明 eq 谓词且 eq(y,y) 不能固定 2023；Claim 只存在量化获奖年份，没有 y<2023。notes 自述要改成整数/不等式，但实际 formula 未改，编译器正确忽略文字自我修正。"),
    11: (False, ["scope_error", "omitted_constraint"],
        "won_second_time_in 与 won_before 是完全独立的谓词，没有前次事件、顺序或恰为第二次的约束；exists year 为空量化。notes 的蕴含关系没有进入 AST。原文还有此前一次是否同年的歧义，不能用 gold 替代其作用域。"),
    12: (False, ["omitted_constraint"],
        "正确保留 Gabriel 与 Timothee 的兄弟姐妹关系，并合理省略无关人物；但没有显式区分这两个确定不同的人，允许自我同指模型。严格身份保持未通过，目标 S 标签和正事实投影正确。"),
    13: (False, ["type_error", "scope_error"],
        "eq/ne/or 运算被写成未声明谓词。穷尽约束把 Child(x) 与候选身份用 or 拼接，缺少 Child(x) -> (x=John or x=Sam or x=Mary)；即使补声明也不能表达 exactly three。"),
    14: (False, ["unsupported_misuse", "omitted_constraint"],
        "把未提及 Gabriel 当作不能形式化。可用存在量词表示第三名兄弟姐妹，并用全称限制总数恰为三；未命名者既可为 Gabriel，也可不是，得 NEI。"),
    15: (False, ["unsupported_misuse", "type_error"],
        "2018 年与 2020 年分开表示本身正确；但因 2020 未确定而将 status 设为 UNSUPPORTED，同时保留公式却清空全部符号声明，违反状态约定并使常量/谓词无声明。"),
    16: (False, ["unsupported_misuse", "scope_error"],
        "notes 正确指出第一任期结束不排除之后再次任职，但 status=UNSUPPORTED 却保留约束；firstTermLeadSinger 与 wasLeadSinger 也没有区间/顺序的桥接公式。修正保留首任期，不排除 2020 再任。"),
    17: (False, ["omitted_constraint", "scope_error"],
        "captain_period 的两个区间事实与 captain_of(year) 完全独立。缺少区间内年份蕴含 captain_of 的量词公式，故 Z3 得 NEI；notes 所写的覆盖关系没有进入约束。修正得到 S。"),
    18: (False, ["scope_error", "omitted_constraint", "entity_confusion"],
        "存在变量与同名 const 混用导致空量化；ne 被声明为普通谓词而非不等运算，人物仍可同指；不定区域赛事被固定成常量。NEI 与源文开放解释一致，但不代表 AST 忠实，也不能按原 gold R 添入排他性。"),
    19: (False, ["scope_error"],
        "Vladimir 与 Vladimir Lenin 的别名和 1887 年均正确，且当前标签 S 正确；但 a local chess tournament 被整个折叠为二元谓词，未按冻结要求显式引入不定赛事存在见证。记为严格表示协议不满足，而非当前标签推断失败。"),
    20: (False, ["scope_error", "omitted_constraint"],
        "获胜者指向 Alexander，原始约束未补 Vladimir 未获胜，因此 Z3 的 NEI 合理；但兄弟未加不等约束、不定比赛无存在见证。notes 声称人物不同便与 claim 矛盾，该文字没有影响求解。"),
    21: (False, ["type_error", "omitted_constraint"],
        "audience_size 是自由变量；ge/le 写成未声明谓词，且人数建成可多值的 drewAudience 关系而非单值整数函数。notes 的区间理解正确，但没有有效 AST 表达。"),
    22: (False, ["omitted_constraint"],
        "Evidence 与 Claim 完全相同，drewMoreThan 正事实足以让本题得到 S；但没有按冻结要求建模一个事件的单值人数属性和 >125010 数值条件。属于表示要求不满足，不是本条相同句子的标签推断失败。"),
    23: (False, ["added_constraint", "omitted_constraint"],
        "把 up to 125010 写成 drewAudience(...,125010) 的精确人数事实，同时又让该关系可多值，125000 与 125010 可同时成立。NEI 标签是上界错误与缺失单值性共同留下的结果，不能算翻译正确。修正为 Attendance(event)<=125010。"),
    24: (True, [],
        "将 Portland 和 Salem 分别保留为 livedIn 正事实，Claim 查询同一人物与 Salem；未把可多地点居住错误设为单值，也未增加负事实。引用、声明与目标关系一致。"),
    25: (False, ["unsupported_misuse", "type_error"],
        "lived_in 的两座城市正确分开，没有补负事实，公式本可表达 NEI；但将 status 错设为 UNSUPPORTED 且保留非空符号/公式，违反状态约定。修正 AST 不据 Portland 居住否定 Salem。"),
    26: (True, [],
        "将同一人出生于 Seattle 的事实和 Claim 一致表示为 bornIn(Person,Place)，引用精确、类型正确。当前来源没有需要合并的数值、排他性或指代范围。"),
    27: (False, ["scope_error", "omitted_constraint"],
        "did not fail to win 被写成 won OR failed_to_win，且两个谓词独立；notes 虽认为应该 won，但实际析取弱化了证据。修正为成功获奖的正事实，NEI 变为 S。"),
    28: (False, ["added_constraint", "omitted_constraint"],
        "failed to win 被直接翻译为 won 正事实，否定极性完全丢失，Z3 因而得到 S。应为 not(won)，修正后 R；这是翻译错误而非求解器错误。"),
    29: (True, [],
        "将被看好获胜的 tipped_to_win 与实际 won 明确分开，未把预测升格为结果，Claim 使用同一人物与奖项。开放的实际结果得到 NEI，形式化与原文一致。"),
    30: (True, [],
        "将出生城市 Antwerp 与 locatedIn(Antwerp,Belgium) 分开表示，Claim 直接查询来源给出的城市。没有把出生于某国反向推成出生于某城。"),
    31: (True, [],
        "Evidence 与 Claim 是同一人出生于 Antwerp 的相同正事实，声明与引用一致，没有多余约束。"),
    32: (True, [],
        "来源只限定出生国家 Belgium；Claim 查询 Antwerp，未调用外部地理知识，也未把国名与城名强行同义合并。城市保持开放，得到 NEI。"),
    33: (False, ["omitted_constraint", "scope_error"],
        "计划与实际日期分开是正确的，但同一被描述的首映日期使用可多值谓词，没有单值属性或互斥约束，允许 8 月 10 日和 15 日同时成为实际首映，故错得 NEI。修正单值实际日期后 R。"),
    34: (False, ["omitted_constraint"],
        "计划 8 月 15 日、实际 8 月 10 日的两个正事实及 S 标签正确；与同组另一题一样，未保存同一首映事件实际日期的单值性。按严格表示标准不通过，但本题正事实投影和标签有效。"),
    35: (False, ["omitted_constraint", "scope_error"],
        "was_delayed 与 premiered_on 完全独立，遗漏实际首映被推迟到原计划日期之后的约束。未给出新日期不意味着原日期仍可实际发生；修正日期顺序后 R。"),
    36: (True, [],
        "直接保留原文明确的 2023 年重新获得 MVP 的事实，Claim 使用相同关系与整数年份。重复 Evidence 公式冗余但无语义影响；相对选秀/首个 Super Bowl 年份对这条直接查询不是必要约束，允许省略。"),
    37: (False, ["type_error", "added_constraint", "omitted_constraint"],
        "2017+2 算成 2019 正确，但 within three years 被收窄成恰为 2022，丢掉区间；Claim 使用未声明 reclaimedMvpAward，与已声明 reclaimedMvpYear 不同。修正为 2019<所述事件年份<=2022，得 R。"),
    38: (False, ["unsupported_misuse", "type_error", "omitted_constraint"],
        "因 some years later 未给精确年份而返回 UNSUPPORTED，却保留非空 AST；同一 reclaimedMvpAward 在 Evidence 用一参数、Claim 用两参数，且缺少年份晚于 2019 的约束。修正保留开放的后续年份，得 NEI。"),
    39: (False, ["type_error", "scope_error", "entity_confusion", "omitted_constraint"],
        "releasedIn 缺少年份参数，starredIn 的 Person/Film 顺序在量词中反转，ne 未声明；only 被写成对所有影片成立的合取而非排他蕴含。Claim 未保留 after 2019、再次或完整成就条件，并将职业成就范围混入单个影片。"),
    40: (False, ["unsupported_misuse", "scope_error", "omitted_constraint"],
        "status=UNSUPPORTED 却保留 AST；2019/2023 年份未进入任何公式，exists y 为空量化，三次/四次用未约束的普通谓词数字参数表示，没有事件数和截至日期范围。notes 正确承认之后可能再发生，但未形成数量约束。"),
    41: (False, ["type_error", "omitted_constraint"],
        "status=OK 却 Evidence 为空、Claim=null，只在 notes 长篇描述打算怎样表达次数。finish_reason=stop，并非 token 截断；文字计划不能代替实际 AST。独立构造一次与四次事件的数量约束后得到 R。"),
}


def main():
    directory = ROOT / EXPERIMENT
    rows = json.loads((directory / "selection.json").read_text(encoding="utf-8"))["rows"]
    reviewed = []
    for index, (correct, categories, note) in sorted(REVIEWS.items()):
        row = rows[index]
        original = directory / "records" / (row["id"] + ".json")
        correction = directory / "reviewed_asts" / (row["id"] + ".json")
        if not original.exists(): raise ValueError("Review without a received completion")
        reviewed.append({"id": row["id"], "input_sha256": row["input_sha256"],
            "record_sha256": file_hash(original), "corrected_ast_sha256": file_hash(correction),
            "semantic_correct": correct, "categories": categories, "review": note,
            "dsl_expressible_under_documented_reading": True,
            "attribution": "translation" if not correct else "no_translation_error"})
    atomic_json(directory / "semantic_review.json", {
        "reviewer": "Codex assistant, not external human adjudication",
        "rubric": "Exact source-grounded claim-relevant translation, typed and executable, with explicit indefinite scopes and warranted identity/closure constraints. Label agreement is not the criterion; irrelevant background may be omitted.",
        "category_legend": {"omitted_constraint": "遗漏约束", "added_constraint": "增加约束", "entity_confusion": "实体混淆", "scope_error": "作用域错误", "unexpressible": "真实不可表达", "unsupported_misuse": "误将未知真值当成不可表达", "type_error": "类型/声明/结构错误"},
        "rows": reviewed})
    print(f"Saved {len(reviewed)}/42 explicit semantic reviews.")


if __name__ == "__main__": main()
