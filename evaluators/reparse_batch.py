"""Reparse an existing predictions.jsonl into per_case.jsonl + summary.json."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EVALUATORS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALUATORS_DIR.parent
sys.path.insert(0, str(EVALUATORS_DIR))

from common import resolve_evalset_path, rubric_file  # noqa: E402
import batch_utils as bu  # noqa: E402

CLUSTER_LEVEL = {
    cid: ("node" if cid.startswith("N") else "process")
    for cid in ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
}
CLUSTER_PRIORITY = ["N5", "N4", "N3", "N2", "N1", "P4", "P3", "P2", "P1"]


def _predict_cluster_phase_b(verdicts: dict[str, str]) -> tuple[str | None, bool]:
    no_ids = [rid for rid, v in verdicts.items() if v == "no"]
    if not no_ids:
        return None, True
    for cid in CLUSTER_PRIORITY:
        if cid in no_ids:
            return cid, False
    return no_ids[0], False


def reparse_phase_b(predictions_path: Path, evalset_path: Path, rubric_ids: list[str]) -> dict:
    cases = json.loads(evalset_path.read_text())["eval_cases"]
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
    return _summary_from_records(records, evalset_path)


def reparse_phase_c(predictions_path: Path, evalset_path: Path) -> dict:
    cases = json.loads(evalset_path.read_text())["eval_cases"]
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
    return _summary_from_records_c(records, evalset_path)


def _summary_from_records(records: list[dict], evalset_path: Path) -> dict:
    errors = [r for r in records if r.get("error")]
    return {
        "evalset": str(evalset_path),
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(sum(1 for r in records if r.get("predicted_cluster") == r["gt_cluster"]) / max(1, len(records)), 3),
        "level_accuracy": round(sum(1 for r in records if r.get("predicted_level") == r["gt_level"]) / max(1, len(records)), 3),
        "reparsed": True,
    }


def _summary_from_records_c(records: list[dict], evalset_path: Path) -> dict:
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
    summary = {
        "evalset": str(evalset_path),
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(sum(1 for r in records if cluster_match(r)) / max(1, len(records)), 3),
        "level_accuracy": round(sum(1 for r in records if level_match(r)) / max(1, len(records)), 3),
        "origin_step_tol0": round(sum(1 for r in records if step_within(r, 0)) / max(1, len(records)), 3),
        "origin_step_tol3": round(sum(1 for r in records if step_within(r, 3)) / max(1, len(records)), 3),
        "reparsed": True,
    }
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
    p.add_argument("--evalset", default=None)
    p.add_argument("--split", default=None)
    p.add_argument("--data-dir", default=None)
    args = p.parse_args()

    predictions = Path(args.predictions).resolve()
    if not predictions.exists():
        print(f"ERROR: {predictions} not found", file=sys.stderr)
        return 1

    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else None
    split = args.split or infer_split_from_path(predictions)
    evalset_path = (
        Path(args.evalset).expanduser().resolve()
        if args.evalset
        else resolve_evalset_path(evalset=None, split=split, with_gt=True, data_dir=data_dir)
    )

    if args.phase == "b":
        rubric_ids = [r["rubric_id"] for r in json.loads(rubric_file().read_text())["rubrics"]]
        summary = reparse_phase_b(predictions, evalset_path, rubric_ids)
    else:
        summary = reparse_phase_c(predictions, evalset_path)

    summary_path = predictions.parent / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Reparsed {predictions.parent}/")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
