"""Rebuild PPT source charts from existing V17/V18 development results only."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean, stdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[1]
FUSION = REPO / "worktrees" / "A_B_fusion_v18"
V17 = FUSION / "experiments/017_unified_comparison/results"
V18 = FUSION / "experiments/018_fusion/quick24_results/evaluation"

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for directory in (V17, V18):
    audit = read(directory / "audit.json")
    assert audit["passed"]
    assert digest(directory / "results.json") == audit["results_sha256"]

a, b = read(V17 / "results.json"), read(V18 / "results.json")
with (V17 / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
    predictions = list(csv.DictReader(f))
for dataset in ("basic", "challenge"):
    rows = [r for r in predictions if r["dataset"] == dataset]
    assert len(rows) == a["datasets"][dataset]["n"]
    for method, score in a["datasets"][dataset]["scores"].items():
        assert sum(r[method] == r["gold"] for r in rows) == score["correct"]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 15, "axes.unicode_minus": False,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.spines.left": False, "axes.titleweight": "bold",
                     "svg.fonttype": "path", "figure.facecolor": "white"})
INK, GRAY, TEAL, BLUE, GOLD = "#182B3A", "#7D8995", "#167C80", "#3774B7", "#CA8A24"

def finish(fig, name, note):
    fig.text(.09, .045, note, fontsize=11, color="#546170", va="bottom")
    fig.subplots_adjust(left=.09, right=.97, top=.82, bottom=.24, wspace=.30)
    fig.savefig(OUT / f"{name}.png", dpi=220, facecolor="white")
    fig.savefig(OUT / f"{name}.svg", facecolor="white")
    plt.close(fig)

methods = ["baseline", "nli", "pj_v3", "lora"]
labels = ["Baseline", "NLI", "PJ rules", "LoRA"]
colors = [GRAY, BLUE, TEAL, GOLD]
table = []
fig, axes = plt.subplots(1, 2, figsize=(13.33, 7.5))
fig.suptitle("LoRA Achieves the Highest Challenge Accuracy", x=.09, y=.95,
             ha="left", fontsize=25, color=INK, weight="bold")
for ax, ds, title in zip(axes, ["basic", "challenge"], ["Basic accuracy · 120 items", "Challenge accuracy · 141 items"]):
    scores = a["datasets"][ds]["scores"]
    vals = [scores[m]["accuracy"] * 100 for m in methods[:3]]
    seeds = [scores[f"lora{s}"]["accuracy"] * 100 for s in (42, 43, 44)]
    vals.append(mean(seeds))
    ax.bar(range(4), vals, color=colors, width=.62)
    ax.errorbar(3, vals[3], yerr=stdev(seeds), color=INK, capsize=5, lw=1.5)
    for i, v in enumerate(vals):
        ax.text(i, v+3.4, f"{v:.2f}%", ha="center", fontsize=14, color=INK)
        table.append(["V17", ds, methods[i], "accuracy", v])
    ax.set_xticks(range(4), labels, fontsize=12)
    ax.set_ylim(0, 112)
    ax.set_yticks([0, 25, 50, 75, 100], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_title(title, loc="left", pad=14, color=INK)
    ax.set_axisbelow(True)
    ax.grid(axis="y", alpha=.18)
finish(fig, "01_unified_accuracy", "V17: Same BF16 27B backbone, items and generation protocol. LoRA: mean ± sample SD across three seeds.\nPreviously used development data; not an independent blind test. Invalid outputs count as errors.")

fig, ax = plt.subplots(figsize=(13.33, 7.5))
fig.suptitle("Higher NEI Recall, Lower REFUTES Recall", x=.09, y=.95,
             ha="left", fontsize=25, color=INK, weight="bold")
scores = a["datasets"]["challenge"]["scores"]
recall_labels = [("NOT ENOUGH INFO", "NEI recall · 68 items"), ("REFUTES", "REFUTES recall · 19 items")]
for j, (method, label, color) in enumerate(zip(["baseline", "pj_v3", "lora"], ["Baseline", "PJ rules", "LoRA, three-seed mean"], [GRAY, TEAL, GOLD])):
    vals = []
    for cls, _ in recall_labels:
        value = (mean(scores[f"lora{s}"]["classes"][cls]["recall"] for s in (42,43,44))
                 if method == "lora" else scores[method]["classes"][cls]["recall"]) * 100
        vals.append(value)
        table.append(["V17", "challenge", method, f"recall_{cls}", value])
    xs = [i + (j-1)*.24 for i in range(2)]
    ax.bar(xs, vals, width=.21, color=color, label=label)
    for x, v in zip(xs, vals):
        ax.text(x, v+2, f"{v:.2f}%", ha="center", fontsize=15, color=INK)
ax.set_xticks([0,1], [x[1] for x in recall_labels])
ax.set_ylim(0, 115)
ax.set_yticks([0,25,50,75,100], ["0%","25%","50%","75%","100%"])
ax.legend(loc="lower center", bbox_to_anchor=(.5,-.24), ncol=3, frameon=False, fontsize=12)
ax.grid(axis="y", alpha=.18)
ax.set_axisbelow(True)
finish(fig, "02_recall_tradeoff", "V17: REFUTES falls from 19/19 to 17/19 for every LoRA seed (−10.53 pp), exceeding the 5 pp limit.\nScores use frozen labels; interpretation disputes remain unresolved.")

fig, ax = plt.subplots(figsize=(13.33, 7.5))
fig.suptitle("Distillation Does Not Exceed Original LoRA", x=.09, y=.95,
             ha="left", fontsize=25, color=INK, weight="bold")
families = b["datasets"]["challenge"]["families"]
keys = ["old_a0", "distill_nli", "distill_pj", "distill_joint"]
names = ["Original LoRA", "NLI rationales", "PJ rationales", "Joint rationales"]
vals = [families[k]["accuracy"]*100 for k in keys]
errs = [families[k]["seed_accuracy_stdev"]*100 for k in keys]
ax.bar(range(4), vals, color=[GOLD, BLUE, GRAY, TEAL], width=.58)
ax.errorbar(range(4), vals, yerr=errs, fmt="none", color=INK, capsize=5)
for i, (v, e) in enumerate(zip(vals, errs)):
    ax.text(i,v+e+2.1,f"{v:.2f}%",ha="center",fontsize=18,color=INK)
    table.append(["V18 quick24", "challenge", keys[i], "accuracy", v])
ax.set_xticks(range(4), names)
ax.set_ylim(0, 112)
ax.set_yticks([0,25,50,75,100], ["0%","25%","50%","75%","100%"])
ax.set_title("Challenge accuracy · 141 items", loc="left", pad=14, color=INK)
ax.grid(axis="y", alpha=.18)
ax.set_axisbelow(True)
finish(fig, "03_fusion_result", "V18 quick scope: 141 challenge items; mean ± sample SD across three seeds. No new distillation family met all criteria.\nDifferences were not significant after correction. New adapters: epoch 3; original LoRA: prior checkpoint selection.")

with (OUT/"chart_data.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer=csv.writer(f)
    writer.writerow(["experiment","dataset","method","metric","percent"])
    writer.writerows(table)
sources = [V17/"results.json",V17/"predictions.csv",V17/"audit.json",V18/"results.json",V18/"audit.json"]
(OUT/"figure_sources.json").write_text(json.dumps({str(p):digest(p) for p in sources}, ensure_ascii=False, indent=2),encoding="utf-8")
print("Created three PNG/SVG charts, chart_data.csv and figure_sources.json.")
