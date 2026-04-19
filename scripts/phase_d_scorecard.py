"""Phase D — three-part scorecard across all runs.

Reads `per_case.jsonl` from any Phase B / Phase C run directory and emits a
unified scorecard per CLAUDE.md:

  1. Origin-step match  (tol-0 and tol-3; tol-3 is the headline)
  2. Cluster match      (9-way exact; also the 2-way node/process level)
  3. Late-symptom fidelity (P3 subset: predicted step <= gt_origin_step +tol)

Stratifications (per step4_plan §8):
  - Aggregate
  - By source: AEB / WW-HC / WW-AG  (derived from eval_id prefix + source meta)
  - By cluster

Calibration κ (Cohen's kappa between judge and human cluster labels) is
computed on the calibration split when both splits have been run.

Invocation:
    python3 scripts/phase_d_scorecard.py \\
        --runs outputs/phase_b_batch/eval/phase-b-eval-*/per_case.jsonl \\
               outputs/phase_c/all_at_once/eval/phase-c-eval-*/per_case.jsonl \\
               outputs/phase_c/binary_search/eval/phase-c-bs-eval-*/per_case.jsonl \\
               outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-*/per_case.jsonl \\
        --labels phase_b c1_allatonce c2_binsearch c3_constraint \\
        --calibration outputs/phase_c/all_at_once/calibration/*/per_case.jsonl \\
        --output docs/reports/step4_results.md

The default invocation with no args auto-discovers the latest run under each
of the standard output paths and writes `docs/reports/step4_results.md`.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_IDS}


# ---------------------------------------------------------------------------
# Shape-normalization: Phase B and Phase C runs have slightly different fields
# (phase B writes predicted_cluster at top level; phase C writes it inside a
# `prediction` sub-object). normalize_record returns a flat dict with the
# shape Phase D expects.

def normalize_record(rec: dict) -> dict:
    pred = rec.get("prediction")
    if isinstance(pred, dict):
        pred_cluster = pred.get("predicted_cluster")
        pred_level = pred.get("predicted_level") or (
            CLUSTER_LEVEL.get(pred_cluster) if pred_cluster else None
        )
        pred_step = pred.get("predicted_origin_step")
        confidence = pred.get("confidence")
        unassignable = pred.get("unassignable")
    else:
        pred_cluster = rec.get("predicted_cluster")
        pred_level = rec.get("predicted_level") or (
            CLUSTER_LEVEL.get(pred_cluster) if pred_cluster else None
        )
        pred_step = rec.get("predicted_origin_step")
        confidence = rec.get("confidence")
        unassignable = rec.get("unassignable")
    return {
        "trajectory_id": rec["trajectory_id"],
        "gt_cluster": rec.get("gt_cluster"),
        "gt_level": rec.get("gt_level"),
        "gt_origin_step": rec.get("gt_origin_step"),
        "predicted_cluster": pred_cluster,
        "predicted_level": pred_level,
        "predicted_origin_step": pred_step,
        "confidence": confidence,
        "unassignable": bool(unassignable) if unassignable is not None else None,
        "error": rec.get("error"),
    }


# ---------------------------------------------------------------------------
# Source assignment from eval_id prefix


def source_of(tid: str) -> str:
    if tid.startswith("WW-HC"):
        return "WW-HC"
    if tid.startswith("WW-AG"):
        return "WW-AG"
    return "AEB"  # AEB ids are model-name-prefixed (GPT-4o_*, Llama*_*, Qwen*_*)


# ---------------------------------------------------------------------------
# Metric helpers


def _acc(records: list[dict], pred_fn) -> tuple[float, int]:
    hits = sum(1 for r in records if pred_fn(r))
    n = len(records)
    return (round(hits / max(1, n), 3), n)


def cluster_match(r: dict) -> bool:
    return r["predicted_cluster"] == r["gt_cluster"]


def level_match(r: dict) -> bool:
    return r["predicted_level"] == r["gt_level"]


def step_within(tol: int):
    def fn(r: dict) -> bool:
        gt = r["gt_origin_step"]
        ps = r["predicted_origin_step"]
        if gt is None or ps is None:
            return False
        return abs(int(ps) - int(gt)) <= tol

    return fn


def p3_late_symptom_fidelity(records: list[dict], tol: int = 3) -> tuple[float, int]:
    """On P3 records only: the prediction must be AT or BEFORE the origin step
    (with tolerance). If the judge picked a later step, it's pointing at the
    symptom, not the root. Reports only on records that gt_cluster=='P3'."""
    subset = [r for r in records if r["gt_cluster"] == "P3"]
    if not subset:
        return (0.0, 0)
    hits = 0
    for r in subset:
        gt = r["gt_origin_step"]
        ps = r["predicted_origin_step"]
        if gt is None or ps is None:
            continue
        # "root, not symptom": predicted step must not be meaningfully LATER
        # than the gt origin. Allow tol slack, since step indices wobble.
        if int(ps) <= int(gt) + tol:
            hits += 1
    return (round(hits / len(subset), 3), len(subset))


def cohen_kappa(gt: list[str], pred: list[str]) -> float | None:
    """Cohen's κ between two categorical labellings. Returns None if either
    side is empty or variance is zero (undefined)."""
    if not gt or len(gt) != len(pred):
        return None
    labels = sorted(set(gt) | set(pred))
    n = len(gt)
    po = sum(1 for a, b in zip(gt, pred) if a == b) / n
    gt_ct = Counter(gt)
    pr_ct = Counter(pred)
    pe = sum((gt_ct[l] / n) * (pr_ct[l] / n) for l in labels)
    if pe >= 1.0:
        return None
    return round((po - pe) / (1 - pe), 3)


# ---------------------------------------------------------------------------
# Core scoring


def score_run(label: str, per_case_path: Path, source_by_id: dict[str, str]) -> dict:
    records = []
    with per_case_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            rec = normalize_record(json.loads(line))
            rec["source"] = source_by_id.get(rec["trajectory_id"], "UNKNOWN")
            records.append(rec)
    # Filter to records with usable prediction
    pred_records = [r for r in records if r["predicted_cluster"] and not r["error"]]
    n_all = len(records)
    n_pred = len(pred_records)

    # Aggregate
    cluster_acc, _ = _acc(records, cluster_match)
    level_acc, _ = _acc(records, level_match)
    t0_acc, _ = _acc(records, step_within(0))
    t3_acc, _ = _acc(records, step_within(3))
    p3_acc, p3_n = p3_late_symptom_fidelity(records, tol=3)

    # By source
    by_source = {}
    for src in ("AEB", "WW-HC", "WW-AG"):
        sub = [r for r in records if r["source"] == src]
        if not sub:
            continue
        by_source[src] = {
            "n": len(sub),
            "cluster": _acc(sub, cluster_match)[0],
            "level": _acc(sub, level_match)[0],
            "step_tol3": _acc(sub, step_within(3))[0],
        }

    # By cluster
    by_cluster = {}
    for cid in CLUSTER_IDS:
        sub = [r for r in records if r["gt_cluster"] == cid]
        if not sub:
            continue
        by_cluster[cid] = {
            "n": len(sub),
            "cluster": _acc(sub, cluster_match)[0],
            "level": _acc(sub, level_match)[0],
            "step_tol3": _acc(sub, step_within(3))[0],
        }

    return {
        "label": label,
        "source_path": str(Path(per_case_path).resolve().relative_to(REPO_ROOT)),
        "n_cases": n_all,
        "n_with_prediction": n_pred,
        "cluster_accuracy": cluster_acc,
        "level_accuracy": level_acc,
        "origin_step_tol0": t0_acc,
        "origin_step_tol3": t3_acc,
        "p3_late_symptom_fidelity_tol3": {"rate": p3_acc, "n_p3": p3_n},
        "by_source": by_source,
        "by_cluster": by_cluster,
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(r["predicted_cluster"] or "UNASSIGNED" for r in records)
        ),
        "records": records,  # stashed for κ computation
    }


# ---------------------------------------------------------------------------
# Auto-discover runs (latest run dir per evaluator)


def _latest(pattern: str) -> Path | None:
    matches = [Path(p) for p in glob.glob(pattern)]
    if not matches:
        return None
    # Each match is a per_case.jsonl; pick the one whose parent dir sorts last
    # (run dirs include a timestamp prefix).
    return max(matches, key=lambda p: p.parent.name)


def auto_discover(split: str) -> list[tuple[str, Path]]:
    candidates = [
        ("phase_b_batch", f"outputs/phase_b_batch/{split}/*/per_case.jsonl"),
        ("c1_all_at_once", f"outputs/phase_c/all_at_once/{split}/*/per_case.jsonl"),
        ("c2_binary_search", f"outputs/phase_c/binary_search/{split}/*/per_case.jsonl"),
        ("c3_constraint_grounded", f"outputs/phase_c/constraint_grounded/{split}/*/per_case.jsonl"),
    ]
    found: list[tuple[str, Path]] = []
    for label, pat in candidates:
        hit = _latest(str(REPO_ROOT / pat))
        if hit is not None:
            found.append((label, hit))
    return found


# ---------------------------------------------------------------------------
# Markdown rendering


def render_markdown(split: str, scores: list[dict], kappa_rows: list[dict]) -> str:
    lines = []
    lines.append(f"# Step 4 — Failure Attribution Results\n")
    lines.append("_Auto-generated by `scripts/phase_d_scorecard.py`. Primary split: **eval** (123 active records). "
                 "Origin-step headline metric is tolerance-3 per step4_plan.md §8. Cluster accuracy is exact 9-way match; "
                 "level accuracy is 2-way node-vs-process. See §7 late-symptom fidelity for the P3 sub-scorecard._\n")
    lines.append(f"_Primary split reported: `{split}`_\n")

    # Aggregate table
    lines.append("## 1. Aggregate scorecard\n")
    lines.append("| Evaluator | n | cluster | level | step tol-3 | step tol-0 | P3 late-symptom (n) | pred w/o error |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in scores:
        p3 = s["p3_late_symptom_fidelity_tol3"]
        lines.append(
            f"| `{s['label']}` | {s['n_cases']} | {s['cluster_accuracy']} | {s['level_accuracy']} | "
            f"{s['origin_step_tol3']} | {s['origin_step_tol0']} | {p3['rate']} (n={p3['n_p3']}) | {s['n_with_prediction']} |"
        )

    # By source
    lines.append("\n## 2. Stratified by source\n")
    lines.append("| Evaluator | source | n | cluster | level | step tol-3 |")
    lines.append("|---|---|---|---|---|---|")
    for s in scores:
        for src, d in s["by_source"].items():
            lines.append(
                f"| `{s['label']}` | {src} | {d['n']} | {d['cluster']} | {d['level']} | {d['step_tol3']} |"
            )

    # By cluster
    lines.append("\n## 3. Stratified by ground-truth cluster\n")
    lines.append("| Evaluator | cluster | n | cluster hit | level hit | step tol-3 |")
    lines.append("|---|---|---|---|---|---|")
    for s in scores:
        for cid, d in s["by_cluster"].items():
            lines.append(
                f"| `{s['label']}` | {cid} | {d['n']} | {d['cluster']} | {d['level']} | {d['step_tol3']} |"
            )

    # Calibration κ
    lines.append("\n## 4. Calibration κ (judge vs human, cluster label)\n")
    lines.append("| Evaluator | n | accuracy | Cohen's κ | Threshold (plan) |")
    lines.append("|---|---|---|---|---|")
    for row in kappa_rows:
        kappa_val = row["kappa"]
        lines.append(
            f"| `{row['label']}` | {row['n']} | {row['accuracy']} | "
            f"{kappa_val if kappa_val is not None else '—'} | κ ≥ 0.70 |"
        )

    # Prediction distribution vs GT
    lines.append("\n## 5. Prediction distribution vs ground truth\n")
    for s in scores:
        lines.append(f"\n### `{s['label']}`")
        lines.append("| cluster | GT | predicted |")
        lines.append("|---|---|---|")
        keys = sorted(set(s["gt_cluster_distribution"]) | set(s["predicted_cluster_distribution"]))
        for k in keys:
            lines.append(
                f"| {k or 'UNASSIGNED'} | {s['gt_cluster_distribution'].get(k, 0)} | "
                f"{s['predicted_cluster_distribution'].get(k, 0)} |"
            )

    # Source-of-truth paths
    lines.append("\n## 6. Source runs\n")
    for s in scores:
        lines.append(f"- `{s['label']}` → `{s['source_path']}` (n={s['n_cases']})")

    lines.append("\n---\n")
    lines.append("_Tolerance convention: origin-step match allows ±3 steps (headline) or exact (stress metric). "
                 "P3 late-symptom fidelity counts a prediction as faithful only if the predicted step is at or "
                 "earlier than the gt origin + 3 — i.e. the evaluator pointed at the root rather than the late "
                 "symptom._\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="eval", help="Primary split to score.")
    parser.add_argument("--runs", nargs="*", default=None,
                        help="Explicit per_case.jsonl paths (overrides auto-discover).")
    parser.add_argument("--labels", nargs="*", default=None,
                        help="Labels aligned with --runs.")
    parser.add_argument(
        "--calibration-split", default="calibration",
        help="Split name used for κ calibration (auto-discovered alongside primary).",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "docs" / "reports" / "step4_results.md"),
    )
    args = parser.parse_args()

    # Resolve primary-split runs
    if args.runs:
        if args.labels and len(args.labels) != len(args.runs):
            print("ERROR: --labels length must match --runs", file=sys.stderr)
            return 1
        runs = [
            (args.labels[i] if args.labels else Path(p).parent.name, Path(p).resolve())
            for i, p in enumerate(args.runs)
        ]
    else:
        runs = auto_discover(args.split)
        if not runs:
            print(f"ERROR: no runs auto-discovered for split={args.split}", file=sys.stderr)
            return 1
    print(f"[Phase D] {len(runs)} runs for split={args.split}:")
    for lbl, p in runs:
        print(f"  {lbl:30s} {p.relative_to(REPO_ROOT)}")

    # Build source map from the evalset's with_gt file
    evalset_path = REPO_ROOT / "data" / "evalsets" / f"{args.split}.with_gt.evalset.json"
    evalset = json.loads(evalset_path.read_text())
    source_by_id = {
        c["eval_id"]: source_of(c["eval_id"])
        for c in evalset["eval_cases"]
    }

    scores = [score_run(label, Path(path).resolve(), source_by_id) for label, path in runs]

    # Calibration κ
    cal_runs = auto_discover(args.calibration_split)
    cal_source_by_id = {}
    cal_path = REPO_ROOT / "data" / "evalsets" / f"{args.calibration_split}.with_gt.evalset.json"
    if cal_path.exists():
        cal_source_by_id = {
            c["eval_id"]: source_of(c["eval_id"])
            for c in json.loads(cal_path.read_text())["eval_cases"]
        }
    kappa_rows: list[dict] = []
    for lbl, path in cal_runs:
        cal = score_run(lbl, path, cal_source_by_id)
        recs = cal["records"]
        gt = [r["gt_cluster"] for r in recs if r["gt_cluster"] and r["predicted_cluster"]]
        pr = [r["predicted_cluster"] for r in recs if r["gt_cluster"] and r["predicted_cluster"]]
        kappa = cohen_kappa(gt, pr)
        acc = round(sum(1 for a, b in zip(gt, pr) if a == b) / max(1, len(gt)), 3)
        kappa_rows.append(
            {"label": lbl, "n": len(gt), "accuracy": acc, "kappa": kappa}
        )

    # Strip `records` before JSON serialization
    for s in scores:
        s.pop("records", None)

    out = render_markdown(args.split, scores, kappa_rows)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out)
    print(f"\nWrote scorecard: {out_path.resolve().relative_to(REPO_ROOT)}")

    # Also emit a machine-readable sidecar
    side = out_path.with_suffix(".json")
    side.write_text(json.dumps({"scores": scores, "kappa": kappa_rows}, indent=2))
    print(f"Wrote JSON sidecar: {side.resolve().relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
