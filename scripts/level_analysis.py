"""Granular analyses for the node-vs-process thesis:

  1. Source × level matrix (per evaluator): node/process accuracy broken down
     by trajectory source (AEB / WW-HC / WW-AG).
  2. McNemar's paired χ² test for evaluator-vs-evaluator level differences.
  3. Bootstrap 95% CI on macro F1 and level accuracy (1000 resamples).

Writes markdown tables to stdout (pipe into the results doc).

Usage:
    python3 scripts/level_analysis.py > /tmp/level_analysis.md
"""
from __future__ import annotations

import json
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RUNS = [
    ("Phase B",       "b", "outputs/phase_b_batch/eval/phase-b-eval-20260419T021853-28ec92/per_case.jsonl"),
    ("C.1 (v1 pro)",  "c", "outputs/phase_c/all_at_once/eval/phase-c-eval-20260419T021854-9714af/per_case.jsonl"),
    ("C.3 (fixed)",   "c", "outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-20260419T113252-c4fd41/per_case.jsonl"),
]


def pred_level(rec, phase):
    return rec.get("predicted_level") if phase == "b" else (rec.get("prediction") or {}).get("predicted_level")


def infer_source(tid):
    if tid.startswith("WW-HC"):
        return "WW-HC"
    if tid.startswith("WW-AG"):
        return "WW-AG"
    return "AEB"


def per_class_recall(records, phase):
    """Return (node_recall, process_recall, node_F1, process_F1)."""
    gt_node = [r for r in records if r["gt_level"] == "node"]
    gt_proc = [r for r in records if r["gt_level"] == "process"]
    node_tp = sum(1 for r in gt_node if pred_level(r, phase) == "node")
    proc_tp = sum(1 for r in gt_proc if pred_level(r, phase) == "process")
    node_fp = sum(1 for r in records if r["gt_level"] != "node" and pred_level(r, phase) == "node")
    proc_fp = sum(1 for r in records if r["gt_level"] != "process" and pred_level(r, phase) == "process")

    def f1(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        return 2 * p * r / (p + r) if p + r else 0

    node_r = node_tp / len(gt_node) if gt_node else 0
    proc_r = proc_tp / len(gt_proc) if gt_proc else 0
    node_f = f1(node_tp, node_fp, len(gt_node) - node_tp)
    proc_f = f1(proc_tp, proc_fp, len(gt_proc) - proc_tp)
    return node_r, proc_r, node_f, proc_f


def level_accuracy(records, phase):
    n = len(records)
    return sum(1 for r in records if pred_level(r, phase) == r["gt_level"]) / n if n else 0


def macro_f1(records, phase):
    _, _, nf, pf = per_class_recall(records, phase)
    return (nf + pf) / 2


def load(p):
    return [json.loads(l) for l in Path(p).open()]


# ---------- Analysis 1: source × level matrix ----------

def source_level_matrix():
    print("## Source × level accuracy matrix\n")
    print("Per-source breakdown of node-accuracy and process-accuracy. Cells are "
          "accuracy_class(source) = correct_predictions / gt_count. The eval "
          "ground-truth distribution by source is **AEB 45 (10n/35p), WW-HC 22 (15n/7p), WW-AG 56 (26n/30p)**.\n")
    print()

    # Header
    print("| Evaluator | AEB node | AEB proc | WW-HC node | WW-HC proc | WW-AG node | WW-AG proc |")
    print("|---|---|---|---|---|---|---|")

    for name, phase, path in RUNS:
        recs = load(path)
        row = [name]
        for src in ["AEB", "WW-HC", "WW-AG"]:
            subset = [r for r in recs if infer_source(r["trajectory_id"]) == src]
            nr, pr, _, _ = per_class_recall(subset, phase)
            gt_node_n = sum(1 for r in subset if r["gt_level"] == "node")
            gt_proc_n = sum(1 for r in subset if r["gt_level"] == "process")
            row.append(f"{nr:.3f} ({int(round(nr * gt_node_n))}/{gt_node_n})")
            row.append(f"{pr:.3f} ({int(round(pr * gt_proc_n))}/{gt_proc_n})")
        print("| " + " | ".join(row) + " |")
    print()


# ---------- Analysis 2: McNemar's paired test ----------

def mcnemar():
    print("## McNemar's paired test on level accuracy\n")
    print("Paired comparison on the same 123 eval trajectories. For each pair "
          "(A vs B), count b = cases A is correct and B is wrong, c = cases B is "
          "correct and A is wrong. Test statistic χ² = (|b − c| − 1)² / (b + c) "
          "(continuity-corrected); p-value from χ²₁ distribution.\n")
    print()
    pairs = [
        (("Phase B", "b", RUNS[0][2]), ("C.1 (v1 pro)", "c", RUNS[1][2])),
        (("C.1 (v1 pro)", "c", RUNS[1][2]), ("C.3 (fixed)", "c", RUNS[2][2])),
        (("Phase B", "b", RUNS[0][2]), ("C.3 (fixed)", "c", RUNS[2][2])),
    ]
    print("| Pair (A vs B) | both correct | A✓ B✗ (b) | A✗ B✓ (c) | both wrong | χ² | p (approx) | winner |")
    print("|---|---|---|---|---|---|---|---|")
    for (name_a, phase_a, path_a), (name_b, phase_b, path_b) in pairs:
        recs_a = load(path_a)
        recs_b_ = load(path_b)
        by_id = {r["trajectory_id"]: r for r in recs_b_}
        both_ok = a_ok_b_no = a_no_b_ok = both_no = 0
        for ra in recs_a:
            rb = by_id.get(ra["trajectory_id"])
            if not rb:
                continue
            ok_a = pred_level(ra, phase_a) == ra["gt_level"]
            ok_b = pred_level(rb, phase_b) == rb["gt_level"]
            if ok_a and ok_b:
                both_ok += 1
            elif ok_a and not ok_b:
                a_ok_b_no += 1
            elif not ok_a and ok_b:
                a_no_b_ok += 1
            else:
                both_no += 1
        b, c = a_ok_b_no, a_no_b_ok
        if b + c == 0:
            chi2 = 0
            p_approx = 1.0
            winner = "tie"
        else:
            chi2 = (abs(b - c) - 1) ** 2 / (b + c)
            # Crude p-value approximation: for χ²₁, p ≈ exp(−chi2/2) / sqrt(chi2 π)
            # Better: use the survival function but scipy isn't here; use this heuristic
            # and label bands instead.
            import math
            # Complement of chi-squared CDF for df=1 is 1 - erf(sqrt(chi2/2))
            p_approx = 1 - math.erf(math.sqrt(chi2 / 2))
            if p_approx < 0.05:
                winner = name_a if b > c else name_b
                sig = "✓ p<0.05"
                winner = f"**{winner}** ({sig})"
            else:
                winner = "not significant"
        print(f"| {name_a} vs {name_b} | {both_ok} | {b} | {c} | {both_no} | {chi2:.3f} | {p_approx:.4f} | {winner} |")
    print()


# ---------- Analysis 3: bootstrap 95% CI ----------

def bootstrap_ci(records, phase, metric_fn, n_resamples=1000, seed=20260419):
    rng = random.Random(seed)
    values = []
    n = len(records)
    for _ in range(n_resamples):
        sample = [records[rng.randrange(n)] for _ in range(n)]
        values.append(metric_fn(sample, phase))
    values.sort()
    return values[int(0.025 * n_resamples)], values[int(0.975 * n_resamples)]


def bootstrap_table():
    print("## Bootstrap 95% CI on headline level metrics (1000 resamples)\n")
    print("Paired nonparametric bootstrap over the 123 eval trajectories. For "
          "each evaluator, resample with replacement and recompute the metric. "
          "95% CI = (2.5th, 97.5th percentile) across resamples.\n")
    print()
    print("| Evaluator | Level accuracy (95% CI) | Macro F1 (95% CI) | Node F1 (95% CI) | Process F1 (95% CI) |")
    print("|---|---|---|---|---|")

    for name, phase, path in RUNS:
        recs = load(path)
        acc_lo, acc_hi = bootstrap_ci(recs, phase, level_accuracy)
        f1_lo, f1_hi = bootstrap_ci(recs, phase, macro_f1)

        def node_f1_fn(rr, ph):
            _, _, nf, _ = per_class_recall(rr, ph)
            return nf

        def proc_f1_fn(rr, ph):
            _, _, _, pf = per_class_recall(rr, ph)
            return pf

        nf_lo, nf_hi = bootstrap_ci(recs, phase, node_f1_fn)
        pf_lo, pf_hi = bootstrap_ci(recs, phase, proc_f1_fn)

        acc = level_accuracy(recs, phase)
        mf1 = macro_f1(recs, phase)
        _, _, nf, pf = per_class_recall(recs, phase)
        print(
            f"| {name} | {acc:.3f} [{acc_lo:.3f}, {acc_hi:.3f}] "
            f"| {mf1:.3f} [{f1_lo:.3f}, {f1_hi:.3f}] "
            f"| {nf:.3f} [{nf_lo:.3f}, {nf_hi:.3f}] "
            f"| {pf:.3f} [{pf_lo:.3f}, {pf_hi:.3f}] |"
        )
    print()


if __name__ == "__main__":
    source_level_matrix()
    mcnemar()
    bootstrap_table()
