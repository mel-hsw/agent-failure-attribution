"""Compute per-source, per-cluster, and P3 late-symptom breakdowns from a
per_case.jsonl file. Prints Markdown tables suitable for step4_results.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]


def infer_source(tid: str) -> str:
    if tid.startswith("WW-HC"):
        return "WW-HC"
    if tid.startswith("WW-AG"):
        return "WW-AG"
    return "AEB"


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.open()]


def pred_of(r: dict, phase: str) -> str | None:
    if phase == "b":
        return r.get("predicted_cluster")
    p = r.get("prediction") or {}
    return p.get("predicted_cluster")


def level_of(r: dict, phase: str) -> str | None:
    if phase == "b":
        return r.get("predicted_level")
    p = r.get("prediction") or {}
    return p.get("predicted_level")


def origin_of(r: dict, phase: str) -> int | None:
    if phase != "c":
        return None
    p = r.get("prediction") or {}
    v = p.get("predicted_origin_step")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def acc(n_correct: int, n: int) -> str:
    if n == 0:
        return "—"
    return f"{n_correct}/{n} ({100*n_correct/n:.0f}%)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("b", "c"), required=True)
    ap.add_argument("--per-case", required=True)
    args = ap.parse_args()

    records = load(Path(args.per_case))
    n = len(records)

    # Aggregate
    cluster_correct = sum(1 for r in records if pred_of(r, args.phase) == r["gt_cluster"])
    level_correct = sum(1 for r in records if level_of(r, args.phase) == r["gt_level"])

    # Origin step (C only)
    if args.phase == "c":
        def step_ok(r, tol):
            gt = r.get("gt_origin_step")
            pred = origin_of(r, "c")
            if gt is None or pred is None:
                return False
            return abs(pred - int(gt)) <= tol
        t0 = sum(1 for r in records if step_ok(r, 0))
        t3 = sum(1 for r in records if step_ok(r, 3))
        t5 = sum(1 for r in records if step_ok(r, 5))
    else:
        t0 = t3 = t5 = None

    print(f"## Aggregate (n={n})\n")
    print(f"- cluster_accuracy: {acc(cluster_correct, n)}")
    print(f"- level_accuracy: {acc(level_correct, n)}")
    if args.phase == "c":
        print(f"- origin_step_tol0: {acc(t0, n)}")
        print(f"- origin_step_tol3: {acc(t3, n)}  (primary)")
        print(f"- origin_step_tol5: {acc(t5, n)}")
    print()

    # By source
    by_source = defaultdict(list)
    for r in records:
        by_source[infer_source(r["trajectory_id"])].append(r)
    print("## By source\n")
    header = "| Source | n | cluster_acc | level_acc"
    sep = "|---|---|---|---"
    if args.phase == "c":
        header += " | tol-3 | tol-0"
        sep += " |---|---"
    header += " |"
    sep += " |"
    print(header)
    print(sep)
    for src in ["AEB", "WW-HC", "WW-AG"]:
        rs = by_source.get(src, [])
        nn = len(rs)
        if nn == 0:
            continue
        ca = sum(1 for r in rs if pred_of(r, args.phase) == r["gt_cluster"])
        la = sum(1 for r in rs if level_of(r, args.phase) == r["gt_level"])
        row = f"| {src} | {nn} | {acc(ca, nn)} | {acc(la, nn)}"
        if args.phase == "c":
            t3s = sum(1 for r in rs if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and abs(origin_of(r, "c") - int(r["gt_origin_step"])) <= 3)
            t0s = sum(1 for r in rs if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and origin_of(r, "c") == int(r["gt_origin_step"]))
            row += f" | {acc(t3s, nn)} | {acc(t0s, nn)}"
        row += " |"
        print(row)
    print()

    # By cluster
    by_cluster = defaultdict(list)
    for r in records:
        by_cluster[r["gt_cluster"]].append(r)
    print("## By cluster\n")
    header = "| Cluster | gt n | cluster_acc | level_acc"
    sep = "|---|---|---|---"
    if args.phase == "c":
        header += " | tol-3 | tol-0"
        sep += " |---|---"
    header += " | most_confused_with |"
    sep += " |---|"
    print(header)
    print(sep)
    for cid in CLUSTER_IDS:
        rs = by_cluster.get(cid, [])
        nn = len(rs)
        if nn == 0:
            continue
        ca = sum(1 for r in rs if pred_of(r, args.phase) == cid)
        la = sum(1 for r in rs if level_of(r, args.phase) == ("node" if cid.startswith("N") else "process"))
        preds = Counter(pred_of(r, args.phase) or "UNASSIGNED" for r in rs if pred_of(r, args.phase) != cid)
        top_confusion = ", ".join(f"{k}={v}" for k, v in preds.most_common(3))
        row = f"| {cid} | {nn} | {acc(ca, nn)} | {acc(la, nn)}"
        if args.phase == "c":
            t3s = sum(1 for r in rs if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and abs(origin_of(r, "c") - int(r["gt_origin_step"])) <= 3)
            t0s = sum(1 for r in rs if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and origin_of(r, "c") == int(r["gt_origin_step"]))
            row += f" | {acc(t3s, nn)} | {acc(t0s, nn)}"
        row += f" | {top_confusion or '—'} |"
        print(row)
    print()

    # Confusion matrix
    print("## Confusion matrix\n")
    header_row = "| gt \\ pred | " + " | ".join(CLUSTER_IDS) + " | UNASSIGNED |"
    sep_row = "|---|" + "---|" * (len(CLUSTER_IDS) + 1)
    print(header_row)
    print(sep_row)
    for gt_cid in CLUSTER_IDS:
        rs = by_cluster.get(gt_cid, [])
        counts = Counter(pred_of(r, args.phase) or "UNASSIGNED" for r in rs)
        row_cells = [f"{counts.get(pid, 0)}" for pid in CLUSTER_IDS] + [f"{counts.get('UNASSIGNED', 0)}"]
        print(f"| {gt_cid} | " + " | ".join(row_cells) + " |")
    print()

    # P3 late-symptom fidelity (phase C only, needs origin step)
    if args.phase == "c":
        p3s = by_cluster.get("P3", [])
        n3 = len(p3s)
        print(f"## P3 late-symptom fidelity (n={n3})\n")
        if n3:
            p3_as_p3 = sum(1 for r in p3s if pred_of(r, "c") == "P3")
            p3_as_node = sum(1 for r in p3s if (pred_of(r, "c") or "").startswith("N"))
            p3_trace_to_origin = sum(1 for r in p3s if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and origin_of(r, "c") <= int(r["gt_origin_step"]) + 3)
            p3_symptom = sum(1 for r in p3s if r.get("gt_origin_step") is not None and origin_of(r, "c") is not None and origin_of(r, "c") > int(r["gt_origin_step"]) + 5)
            print(f"- Classified as P3: {acc(p3_as_p3, n3)}")
            print(f"- Traced to origin (predicted_step <= gt + 3): {acc(p3_trace_to_origin, n3)}")
            print(f"- Predicted at late symptom (predicted_step > gt + 5): {acc(p3_symptom, n3)}")
            print(f"- Mis-classified as node-level origin cluster: {acc(p3_as_node, n3)}")


if __name__ == "__main__":
    main()
