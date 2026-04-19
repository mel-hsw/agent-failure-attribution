"""Reparse an existing predictions.jsonl into per_case.jsonl + summary.json.

Use case: recover from the row-order bug (Vertex batch scrambles input→output
order; early runs used row-index matching and produced mis-aligned per_case
files). The raw predictions.jsonl is fine — each row carries its full request,
so we can re-align by the trajectory_id embedded in the prompt.

Usage:
    python3 scripts/reparse_batch.py --phase b --predictions <path-to-predictions.jsonl>
    python3 scripts/reparse_batch.py --phase c --predictions <path> --split eval

The script will:
  - Load the eval set for the split (to get ground truth)
  - Parse predictions.jsonl via trajectory_id matching
  - Emit per_case.jsonl and summary.json next to the predictions file
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import batch_utils as bu  # noqa: E402

EVALSET_DIR = REPO_ROOT / "data" / "evalsets"
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]}
CLUSTER_PRIORITY = ["N5", "N4", "N3", "N2", "N1", "P4", "P3", "P2", "P1"]


def _predict_cluster_phase_b(verdicts: dict[str, str]) -> tuple[str | None, bool]:
    no_ids = [rid for rid, v in verdicts.items() if v == "no"]
    if not no_ids:
        return None, True
    for cid in CLUSTER_PRIORITY:
        if cid in no_ids:
            return cid, False
    return no_ids[0], False


def reparse_phase_b(predictions_path: Path, split: str, rubric_ids: list[str]) -> dict:
    evalset = json.loads((EVALSET_DIR / f"{split}.with_gt.evalset.json").read_text())
    cases = evalset["eval_cases"]
    by_key = bu.parse_output_by_key(predictions_path, bu.make_trajectory_id_extractor())

    records = []
    for case in cases:
        tid = case["eval_id"]
        match = by_key.get(tid)
        gt = case["metadata"].get("gt", {})
        base = {
            "trajectory_id": tid,
            "gt_cluster": gt.get("proposed_cluster"),
            "gt_level": gt.get("proposed_level"),
            "gt_origin_step": gt.get("critical_failure_step"),
        }
        if match is None:
            records.append({**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": "no output row"})
            continue
        response, err = match
        if err:
            records.append({**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": err})
            continue
        text = bu.extract_text(response)
        if not text:
            records.append({**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": "no text in response"})
            continue
        try:
            parsed = json.loads(text)
            verdicts = {rid: parsed[rid]["verdict"] for rid in rubric_ids if rid in parsed}
            rationales = {rid: parsed[rid]["rationale"] for rid in rubric_ids if rid in parsed}
            pred_c, unass = _predict_cluster_phase_b(verdicts)
            records.append({
                **base,
                "verdicts": verdicts,
                "rationales": rationales,
                "predicted_cluster": pred_c,
                "predicted_level": CLUSTER_LEVEL.get(pred_c),
                "unassignable": unass,
                "error": None,
            })
        except (KeyError, json.JSONDecodeError) as e:
            records.append({**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": f"{type(e).__name__}: {e}", "raw_text": text[:500]})

    out_dir = predictions_path.parent
    (out_dir / "per_case.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")

    errors = [r for r in records if r.get("error")]
    correct_cluster = sum(1 for r in records if r.get("predicted_cluster") == r["gt_cluster"])
    correct_level = sum(1 for r in records if r.get("predicted_level") == r["gt_level"])
    unassignable = sum(1 for r in records if r.get("unassignable"))
    confusion = defaultdict(Counter)
    for r in records:
        confusion[r["gt_cluster"]][r.get("predicted_cluster") or "UNASSIGNED"] += 1

    summary = {
        "split": split,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(Counter(r.get("predicted_cluster") or "UNASSIGNED" for r in records)),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "reparsed": True,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def reparse_phase_c(predictions_path: Path, split: str) -> dict:
    evalset = json.loads((EVALSET_DIR / f"{split}.with_gt.evalset.json").read_text())
    cases = evalset["eval_cases"]
    by_key = bu.parse_output_by_key(predictions_path, bu.make_trajectory_id_extractor())

    records = []
    for case in cases:
        tid = case["eval_id"]
        match = by_key.get(tid)
        gt = case["metadata"].get("gt", {})
        base = {
            "trajectory_id": tid,
            "gt_cluster": gt.get("proposed_cluster"),
            "gt_level": gt.get("proposed_level"),
            "gt_origin_step": gt.get("critical_failure_step"),
        }
        if match is None:
            records.append({**base, "prediction": None, "error": "no output row"})
            continue
        response, err = match
        if err:
            records.append({**base, "prediction": None, "error": err})
            continue
        text = bu.extract_text(response)
        if not text:
            records.append({**base, "prediction": None, "error": "no text in response"})
            continue
        try:
            parsed = json.loads(text)
            parsed["predicted_level"] = CLUSTER_LEVEL.get(parsed.get("predicted_cluster"), parsed.get("predicted_level"))
            records.append({**base, "prediction": parsed, "error": None})
        except json.JSONDecodeError as e:
            records.append({**base, "prediction": None, "error": f"JSONDecodeError: {e}", "raw_text": text[:500]})

    out_dir = predictions_path.parent
    (out_dir / "per_case.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n")

    def cluster_match(r):
        p = r.get("prediction") or {}
        return p.get("predicted_cluster") == r["gt_cluster"]

    def level_match(r):
        p = r.get("prediction") or {}
        return p.get("predicted_level") == r["gt_level"]

    def step_within(r, tol):
        p = r.get("prediction") or {}
        gt = r.get("gt_origin_step")
        if gt is None or p.get("predicted_origin_step") is None:
            return False
        return abs(int(p["predicted_origin_step"]) - int(gt)) <= tol

    errors = [r for r in records if r.get("error")]
    successful = [r for r in records if r.get("prediction")]
    correct_cluster = sum(1 for r in records if cluster_match(r))
    correct_level = sum(1 for r in records if level_match(r))
    step_t0 = sum(1 for r in records if step_within(r, 0))
    step_t3 = sum(1 for r in records if step_within(r, 3))
    unassignable = sum(1 for r in successful if (r["prediction"] or {}).get("unassignable"))
    confusion = defaultdict(Counter)
    for r in records:
        pred = (r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED"
        confusion[r["gt_cluster"]][pred] += 1

    summary = {
        "split": split,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "origin_step_tol0": round(step_t0 / max(1, len(records)), 3),
        "origin_step_tol3": round(step_t3 / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(((r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED") for r in records)
        ),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "reparsed": True,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def infer_split_from_path(path: Path) -> str:
    for part in path.parts:
        if part in ("dev", "eval", "calibration"):
            return part
    raise ValueError(f"Can't infer split from {path}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=("b", "c"), required=True)
    p.add_argument("--predictions", required=True, help="Path to predictions.jsonl")
    p.add_argument("--split", default=None, help="dev/calibration/eval (inferred from path if not provided)")
    args = p.parse_args()

    predictions = Path(args.predictions).resolve()
    if not predictions.exists():
        print(f"ERROR: {predictions} not found", file=sys.stderr)
        return 1
    split = args.split or infer_split_from_path(predictions)

    if args.phase == "b":
        rubric_ids = [r["rubric_id"] for r in json.loads((REPO_ROOT / "data/rubrics/option_b_rubric.json").read_text())["rubrics"]]
        summary = reparse_phase_b(predictions, split, rubric_ids)
    else:
        summary = reparse_phase_c(predictions, split)

    print(f"Reparsed {predictions.parent}/")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
