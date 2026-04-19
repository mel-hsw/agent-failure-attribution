"""Cohen's κ between judge predictions and human ground truth.

Reads a per_case.jsonl (reparsed from a batch run) and computes κ on:
  - Cluster label (9-way)
  - Level label (2-way: node vs process)
  - [Phase C only] Origin step tol-3 "agreement" (binary: within ±3 or not)

Usage:
    python3 scripts/compute_kappa.py --phase b --per-case <path>
    python3 scripts/compute_kappa.py --phase c --per-case <path>

Also prints a 95% CI on κ (bootstrap, 1000 resamples) — at small n, point
estimates are noisy; the CI keeps the reader honest.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def pred_cluster(r: dict, phase: str) -> str | None:
    if phase == "b":
        return r.get("predicted_cluster")
    p = r.get("prediction") or {}
    return p.get("predicted_cluster")


def pred_level(r: dict, phase: str) -> str | None:
    if phase == "b":
        return r.get("predicted_level")
    p = r.get("prediction") or {}
    return p.get("predicted_level")


def pred_step(r: dict) -> int | None:
    p = r.get("prediction") or {}
    v = p.get("predicted_origin_step")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    """κ = (Po - Pe) / (1 - Pe). Symmetric; both raters treated equally.
    Returns NaN if Pe == 1 (degenerate: both raters always agree on the same label)."""
    if not pairs:
        return float("nan")
    n = len(pairs)
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    po = sum(1 for a, b in pairs if a == b) / n
    # Marginal distributions
    pa = {l: sum(1 for a, _ in pairs if a == l) / n for l in labels}
    pb = {l: sum(1 for _, b in pairs if b == l) / n for l in labels}
    pe = sum(pa[l] * pb[l] for l in labels)
    if pe >= 1.0:
        return float("nan")
    return (po - pe) / (1 - pe)


def bootstrap_kappa_ci(pairs: list[tuple[str, str]], n_resamples: int = 1000, seed: int = 20260419):
    if len(pairs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    kappas = []
    for _ in range(n_resamples):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        k = cohen_kappa(sample)
        if k == k:  # not NaN
            kappas.append(k)
    if not kappas:
        return (float("nan"), float("nan"))
    kappas.sort()
    lo = kappas[int(0.025 * len(kappas))]
    hi = kappas[int(0.975 * len(kappas))]
    return (lo, hi)


def interpret(kappa: float) -> str:
    """Landis & Koch (1977) conventional bands."""
    if kappa != kappa:
        return "undefined (degenerate)"
    if kappa < 0.0:
        return "worse than chance"
    if kappa < 0.20:
        return "slight (near chance)"
    if kappa < 0.40:
        return "fair"
    if kappa < 0.60:
        return "moderate"
    if kappa < 0.80:
        return "substantial"
    return "almost perfect"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("b", "c"), required=True)
    ap.add_argument("--per-case", required=True)
    args = ap.parse_args()

    records = [json.loads(l) for l in Path(args.per_case).open()]
    n = len(records)
    print(f"Computing κ on {n} cases from {args.per_case}")
    print(f"Gate from step4_plan §8.3: κ ≥ 0.70 for paper-ready claim.")
    print()

    # Cluster κ — filter rows with both labels
    cluster_pairs = [(r["gt_cluster"], pred_cluster(r, args.phase))
                     for r in records
                     if r["gt_cluster"] and pred_cluster(r, args.phase)]
    k_cluster = cohen_kappa(cluster_pairs)
    lo, hi = bootstrap_kappa_ci(cluster_pairs)
    print(f"Cluster κ (9-way): {k_cluster:.3f}  (95% CI [{lo:.2f}, {hi:.2f}])  — {interpret(k_cluster)}")
    print(f"  raw agreement: {sum(1 for a, b in cluster_pairs if a == b)}/{len(cluster_pairs)}")

    # Level κ
    level_pairs = [(r["gt_level"], pred_level(r, args.phase))
                   for r in records
                   if r["gt_level"] and pred_level(r, args.phase)]
    k_level = cohen_kappa(level_pairs)
    lo, hi = bootstrap_kappa_ci(level_pairs)
    print(f"Level κ (node/process): {k_level:.3f}  (95% CI [{lo:.2f}, {hi:.2f}])  — {interpret(k_level)}")
    print(f"  raw agreement: {sum(1 for a, b in level_pairs if a == b)}/{len(level_pairs)}")

    # Origin-step tol-3 κ (phase C only)
    if args.phase == "c":
        step_pairs = []
        for r in records:
            gt_s = r.get("gt_origin_step")
            pred_s = pred_step(r)
            if gt_s is None or pred_s is None:
                continue
            within = "within_tol3" if abs(pred_s - int(gt_s)) <= 3 else "out_of_tol3"
            # For the gt "label" we always say within_tol3 (the human-placed label is the ground truth by definition)
            step_pairs.append(("within_tol3", within))
        # This κ is degenerate because gt is always "within_tol3" by construction.
        # Report raw agreement rate instead.
        agree = sum(1 for a, b in step_pairs if a == b)
        print(f"Step-level tol-3 agreement rate (not κ; gt is trivial): {agree}/{len(step_pairs)}")

    print(f"\nSample size: {n}. At n=5, κ has very wide CIs — interpret as directional only.")


if __name__ == "__main__":
    sys.exit(main() or 0)
