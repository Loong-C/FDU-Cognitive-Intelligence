"""Build vector evidence charts for the Beamer report from frozen results."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean, stdev

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)
FUSION = ROOT / "worktrees/A_B_fusion_v18"
V17 = FUSION / "experiments/017_unified_comparison/results"
V18 = FUSION / "experiments/018_fusion/quick24_results/evaluation"
read = lambda p: json.loads(p.read_text(encoding="utf-8"))
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
for folder in (V17, V18):
    audit = read(folder / "audit.json")
    assert audit["passed"] and digest(folder / "results.json") == audit["results_sha256"]
a, b = read(V17 / "results.json"), read(V18 / "results.json")
with (V17 / "predictions.csv").open(encoding="utf-8-sig", newline="") as f:
    predictions = list(csv.DictReader(f))
for ds in ("basic", "challenge"):
    subset = [r for r in predictions if r["dataset"] == ds]
    for method, score in a["datasets"][ds]["scores"].items():
        assert sum(r[method] == r["gold"] for r in subset) == score["correct"]

INK, BLUE, TEAL, GOLD, GRAY = "#202D3A", "#2B5783", "#167C80", "#BE8529", "#7D8995"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 16,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.titleweight": "bold",
    "pdf.fonttype": 42, "svg.fonttype": "none", "text.color": INK,
    "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})

def save(fig, name):
    fig.savefig(ASSETS / f"{name}.pdf", transparent=True)
    fig.savefig(ASSETS / f"{name}.png", dpi=160, facecolor="white")
    plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(13, 4.0))
for ax, ds, title in zip(axes, ["basic", "challenge"], ["Basic (n = 120)", "Challenge (n = 141)"]):
    scores = a["datasets"][ds]["scores"]
    vals = [scores[m]["accuracy"] * 100 for m in ("baseline", "nli", "pj_v3")]
    seeds = [scores[f"lora{s}"]["accuracy"] * 100 for s in (42, 43, 44)]
    vals.append(mean(seeds))
    ax.bar(range(4), vals, width=.62, color=[GRAY, BLUE, TEAL, GOLD], zorder=3)
    ax.errorbar(3, vals[3], yerr=stdev(seeds), fmt="none", capsize=5, color=INK, zorder=4)
    for i, val in enumerate(vals):
        ax.text(i, val + 4, f"{val:.2f}", ha="center", fontsize=17)
    ax.set_ylim(0, 115)
    ax.set_yticks([0, 50, 100], ["0%", "50%", "100%"])
    ax.set_xticks(range(4), ["Baseline", "NLI", "PJ", "LoRA"], fontsize=17)
    ax.set_title(title, fontsize=19, loc="left", pad=12)
    ax.grid(axis="y", alpha=.16, zorder=0)
fig.subplots_adjust(left=.07, right=.99, bottom=.13, top=.84, wspace=.24)
save(fig, "accuracy")

fig, ax = plt.subplots(figsize=(13, 4.0))
families = b["datasets"]["challenge"]["families"]
keys = ["old_a0", "distill_nli", "distill_pj", "distill_joint"]
vals = [families[k]["accuracy"] * 100 for k in keys]
errs = [families[k]["seed_accuracy_stdev"] * 100 for k in keys]
ax.bar(range(4), vals, color=[GOLD, BLUE, TEAL, GRAY], width=.55, zorder=3)
ax.errorbar(range(4), vals, yerr=errs, fmt="none", capsize=6, color=INK, zorder=4)
for i, (v, e) in enumerate(zip(vals, errs)):
    ax.text(i, v+e+3, f"{v:.2f}%", ha="center", fontsize=20)
ax.set_xticks(range(4), ["Original LoRA", "NLI rationales", "PJ rationales", "Joint rationales"], fontsize=18)
ax.set_yticks([0, 50, 100], ["0%", "50%", "100%"])
ax.set_ylim(0, 115)
ax.grid(axis="y", alpha=.16, zorder=0)
fig.subplots_adjust(left=.07, right=.99, bottom=.14, top=.95)
save(fig, "distillation")

labels = ["SUPPORTS", "REFUTES", "NOT ENOUGH INFO"]
rows = [r for r in predictions if r["dataset"] == "challenge"]
matrices = {}
for m in ("baseline", "nli", "pj_v3", "lora42", "lora43", "lora44"):
    matrices[m] = np.array([[sum(r["gold"] == g and
        (r[m] == p if p != "Invalid" else r[m] not in labels) for r in rows)
        for p in labels + ["Invalid"]] for g in labels])
    assert matrices[m].sum(axis=1).tolist() == [54, 19, 68]
denoms = np.array([54, 19, 68])[:, None]
rates = {k: v / denoms * 100 for k, v in matrices.items()}
rates["lora"] = np.mean([rates[f"lora{s}"] for s in (42, 43, 44)], axis=0)

def heatmap(ax, rate, annotation, title, show_rows=True, highlight=False):
    im = ax.imshow(rate, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_title(title, loc="center", fontsize=20, pad=13)
    ax.set_xticks(range(4), ["S", "R", "NEI", "Invalid"], fontsize=17)
    ax.set_yticks(range(3), ["S (54)", "R (19)", "NEI (68)"] if show_rows else ["", "", ""], fontsize=17)
    ax.tick_params(axis="both", length=0, pad=9)
    ax.set_xticks(np.arange(-.5, 4, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 3, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for i in range(3):
        for j in range(4):
            ax.text(j, i, annotation[i][j], ha="center", va="center", fontsize=18,
                    color="white" if rate[i, j] >= 57 else INK)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if highlight:
        ax.add_patch(Rectangle((.5, 1.5), 1, 1, fill=False, edgecolor=GOLD, linewidth=3, zorder=5))
    return im

fig, axes = plt.subplots(1, 3, figsize=(14, 4.4))
for ax, key, title in zip(axes, ["baseline", "pj_v3", "lora"], ["Baseline", "PJ rules", "LoRA (3-seed mean)"]):
    rate = rates[key]
    annotation = [["0" if v == 0 else f"{v:.2f}" for v in row] for row in rate]
    im = heatmap(ax, rate, annotation, title, show_rows=ax is axes[0], highlight=True)
axes[2].add_patch(Rectangle((-.5, .5), 4, 1, fill=False, edgecolor="#BE5347", linewidth=2.5, zorder=5))
fig.subplots_adjust(left=.105, right=.99, bottom=.25, top=.84, wspace=.08)
fig.text(.014, .54, "True label", rotation=90, va="center", fontsize=17)
fig.text(.52, .09, "Predicted label", ha="center", fontsize=17)
cax = fig.add_axes([.79, .075, .20, .027])
bar = fig.colorbar(im, cax=cax, orientation="horizontal", ticks=[0, 50, 100])
bar.ax.tick_params(labelsize=12)
fig.text(.60, .07, "Row percentage (%)", fontsize=13)
save(fig, "confusion_main")

fig, axes = plt.subplots(2, 2, figsize=(13, 5.0))
for ax, key, title in zip(axes.flat, ["nli", "lora42", "lora43", "lora44"], ["NLI", "LoRA: seed 42", "LoRA: seed 43", "LoRA: seed 44"]):
    heatmap(ax, rates[key], [[str(v) for v in row] for row in matrices[key]], title)
fig.subplots_adjust(left=.14, right=.98, bottom=.10, top=.90, wspace=.34, hspace=.66)
save(fig, "confusion_seeds")

sources = [V17/"results.json", V17/"predictions.csv", V17/"audit.json", V18/"results.json", V18/"audit.json", HERE.parent/"slide_examples.json"]
(HERE/"build/sources.json").write_text(json.dumps({str(p.relative_to(ROOT)):digest(p) for p in sources}, indent=2), encoding="utf-8")
(HERE/"build/confusion_data.json").write_text(json.dumps({"counts":{k:v.tolist() for k,v in matrices.items()},"percent":{k:v.tolist() for k,v in rates.items()}}, indent=2), encoding="utf-8")
print("Created 4 vector chart PDFs and PNG previews; validated frozen-result hashes and counts.")
