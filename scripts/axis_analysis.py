"""Granular cuts by metric axis × level.

Asks: for each of the three matching axes (cluster / step-tol-3 / step-tol-0),
how accurate is each evaluator when gt_level=node vs gt_level=process?

Useful because:
  - "Cluster accuracy" and "step accuracy" are different tasks; evaluators
    may excel on one without the other.
  - The node-vs-process thesis deserves this cross-cut: does the constraint
    log help cluster-picking on processes (where we've seen the gap) or does
    it also help step-localization on processes?

Also computes per-class F1/recall/precision for the cluster axis (since
there are 9 classes to break out).

Output: markdown tables to stdout.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RUNS = [
    ("Phase B",       "b", "outputs/phase_b_batch/eval/phase-b-eval-20260419T021853-28ec92/per_case.jsonl"),
    ("C.1 (v1 pro)",  "c", "outputs/phase_c/all_at_once/eval/phase-c-eval-20260419T021854-9714af/per_case.jsonl"),
    ("C.3 (fixed)",   "c", "outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-20260419T113252-c4fd41/per_case.jsonl"),
]

CLUSTERS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]


def pred_cluster(r, phase):
    return r.get("predicted_cluster") if phase == "b" else (r.get("prediction") or {}).get("predicted_cluster")


def pred_step(r, phase):
    if phase == "b":
        return None
    p = r.get("prediction") or {}
    v = p.get("predicted_origin_step")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def load(p):
    return [json.loads(l) for l in Path(p).open()]


def cluster_correct(r, phase):
    return pred_cluster(r, phase) == r["gt_cluster"]


def step_within(r, phase, tol):
    gt = r.get("gt_origin_step")
    ps = pred_step(r, phase)
    if gt is None or ps is None:
        return False
    return abs(ps - int(gt)) <= tol


def fraction(count, total):
    if total == 0:
        return "—"
    return f"{count/total:.3f} ({count}/{total})"


def main():
    print("## Metric × level accuracy matrix\n")
    print("For each metric axis (cluster exact match / step within ±3 / step exact match) "
          "and each evaluator, cross-cut by ground-truth level. Cells are "
          "`accuracy = correct / count`. Step metrics are not emitted by "
          "Phase B (rubric-only evaluator).\n")
    print()

    header = "| Metric axis | Class | " + " | ".join(n for n, _, _ in RUNS) + " |"
    sep = "|---|---|" + "|".join(["---"] * len(RUNS)) + "|"
    print(header)
    print(sep)

    axes = [
        ("Cluster (exact)",    lambda r, p: cluster_correct(r, p)),
        ("Step tol-3 (±3)",    lambda r, p: step_within(r, p, 3)),
        ("Step tol-0 (exact)", lambda r, p: step_within(r, p, 0)),
    ]

    # Pre-load
    loaded = [(name, phase, load(path)) for name, phase, path in RUNS]

    for axis_label, is_correct in axes:
        for class_label, filt in [
            ("Overall",  lambda r: True),
            ("Node",     lambda r: r["gt_level"] == "node"),
            ("Process",  lambda r: r["gt_level"] == "process"),
        ]:
            row = [axis_label if class_label == "Overall" else "",
                   class_label]
            for name, phase, recs in loaded:
                subset = [r for r in recs if filt(r)]
                if phase == "b" and axis_label.startswith("Step"):
                    row.append("n/a")
                else:
                    correct = sum(1 for r in subset if is_correct(r, phase))
                    row.append(fraction(correct, len(subset)))
            print("| " + " | ".join(row) + " |")
        print("| | | | | |")  # visual separator

    # Per-cluster F1 for the cluster axis (9-class)
    print()
    print("## Per-cluster F1 / precision / recall (9-class cluster axis)\n")
    print("Per-cluster breakdown within the 9-way cluster classification. Each row "
          "is one cluster; columns are (recall, precision, F1) per evaluator. "
          "`recall = tp / (tp + fn)`, `precision = tp / (tp + fp)`, "
          "`F1 = 2·p·r / (p+r)`.\n")
    print()

    header2 = "| Cluster | gt n | " + " | ".join(f"{n} (R / P / F1)" for n, _, _ in RUNS) + " |"
    sep2 = "|---|---|" + "|".join(["---"] * len(RUNS)) + "|"
    print(header2)
    print(sep2)

    gt_by_cluster = {c: [r for r in loaded[0][2] if r["gt_cluster"] == c] for c in CLUSTERS}
    for c in CLUSTERS:
        row = [c, str(len(gt_by_cluster[c]))]
        for name, phase, recs in loaded:
            gt_c = [r for r in recs if r["gt_cluster"] == c]
            pred_c = [r for r in recs if pred_cluster(r, phase) == c]
            tp = sum(1 for r in gt_c if pred_cluster(r, phase) == c)
            fn = len(gt_c) - tp
            fp = len(pred_c) - tp
            recall = tp / (tp + fn) if tp + fn else 0
            precision = tp / (tp + fp) if tp + fp else 0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
            row.append(f"{recall:.2f} / {precision:.2f} / {f1:.2f}")
        print("| " + " | ".join(row) + " |")

    # Macro F1 across 9 clusters
    print()
    print("### Macro F1 across 9 clusters (cluster axis)\n")
    print("| Evaluator | Macro F1 (9-class) |")
    print("|---|---|")
    for name, phase, recs in loaded:
        f1_sum = 0
        for c in CLUSTERS:
            gt_c = [r for r in recs if r["gt_cluster"] == c]
            pred_c = [r for r in recs if pred_cluster(r, phase) == c]
            tp = sum(1 for r in gt_c if pred_cluster(r, phase) == c)
            fn = len(gt_c) - tp
            fp = len(pred_c) - tp
            recall = tp / (tp + fn) if tp + fn else 0
            precision = tp / (tp + fp) if tp + fp else 0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
            f1_sum += f1
        macro = f1_sum / len(CLUSTERS)
        print(f"| {name} | {macro:.3f} |")


if __name__ == "__main__":
    main()
