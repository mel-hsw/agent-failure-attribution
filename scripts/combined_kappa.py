"""Combined κ over multiple per_case.jsonl files.

Usage:
    python3 scripts/combined_kappa.py --phase c --per-case file1.jsonl file2.jsonl

Doubles effective n by pooling held-out sets (dev + calibration). This is
methodologically OK because prompts weren't tuned on dev (the rubric
wording came from step3 taxonomy definitions, not from iterating on dev
predictions). Output: same shape as compute_kappa.py, larger n.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from compute_kappa import (  # noqa: E402
    bootstrap_kappa_ci,
    cohen_kappa,
    interpret,
    pred_cluster,
    pred_level,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("b", "c"), required=True)
    ap.add_argument("--per-case", nargs="+", required=True)
    args = ap.parse_args()

    records = []
    for p in args.per_case:
        for line in Path(p).open():
            records.append(json.loads(line))

    n = len(records)
    print(f"Combined κ on n={n} cases from {len(args.per_case)} files")
    print()

    cluster_pairs = [(r["gt_cluster"], pred_cluster(r, args.phase))
                     for r in records
                     if r["gt_cluster"] and pred_cluster(r, args.phase)]
    k_c = cohen_kappa(cluster_pairs)
    lo, hi = bootstrap_kappa_ci(cluster_pairs)
    print(f"Cluster κ (9-way): {k_c:.3f}  (95% CI [{lo:.2f}, {hi:.2f}])  — {interpret(k_c)}")
    print(f"  raw agreement: {sum(1 for a, b in cluster_pairs if a == b)}/{len(cluster_pairs)}")

    level_pairs = [(r["gt_level"], pred_level(r, args.phase))
                   for r in records
                   if r["gt_level"] and pred_level(r, args.phase)]
    k_l = cohen_kappa(level_pairs)
    lo, hi = bootstrap_kappa_ci(level_pairs)
    print(f"Level κ (node/process): {k_l:.3f}  (95% CI [{lo:.2f}, {hi:.2f}])  — {interpret(k_l)}")
    print(f"  raw agreement: {sum(1 for a, b in level_pairs if a == b)}/{len(level_pairs)}")

    print(f"\nGate: κ ≥ 0.70 (from step4_plan §8.3)")


if __name__ == "__main__":
    main()
