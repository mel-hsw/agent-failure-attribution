"""Render a human-readable side-by-side review of Phase B and Phase C dev smoke.

Prints for each dev case:
  - Ground truth (cluster @ step, source, level, task summary)
  - Phase B: predicted cluster, per-rubric verdicts, rationales for any 'no'
  - Phase C: predicted cluster, origin step, confidence, full reasoning, evidence_steps
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALSET = REPO_ROOT / "data" / "evalsets" / "dev.with_gt.evalset.json"


def latest(pattern: str) -> Path:
    paths = sorted(glob.glob(str(REPO_ROOT / pattern)))
    if not paths:
        raise FileNotFoundError(pattern)
    return Path(paths[-1])


def load_jsonl(path: Path) -> dict[str, dict]:
    return {json.loads(l)["trajectory_id"]: json.loads(l) for l in open(path)}


def main():
    b_path = latest("outputs/phase_b_batch/dev/*/per_case.jsonl")
    c_path = latest("outputs/phase_c/all_at_once/dev/*/per_case.jsonl")
    print(f"Phase B file: {b_path}")
    print(f"Phase C file: {c_path}")

    b = load_jsonl(b_path)
    c = load_jsonl(c_path)

    evalset = json.loads(EVALSET.read_text())
    for case in evalset["eval_cases"]:
        tid = case["eval_id"]
        gt = case["metadata"].get("gt", {})
        task = case["conversation"][0].get("user_content", {}).get("parts", [{}])[0].get("text", "")[:300]
        print("\n" + "=" * 100)
        print(f"CASE {tid}")
        print(f"  GT: cluster={gt.get('proposed_cluster')} level={gt.get('proposed_level')} origin_step={gt.get('critical_failure_step')}")
        print(f"  Source: {gt.get('source')}  | Trajectory length: {len(case['metadata']['trajectory'])} steps")
        print(f"  Task: {task}{'...' if len(task) == 300 else ''}")

        print("\n-- Phase B (rubric baseline) --")
        br = b.get(tid, {})
        print(f"  predicted: {br.get('predicted_cluster')}  level: {br.get('predicted_level')}  unassignable: {br.get('unassignable')}")
        verdicts = br.get("verdicts", {})
        rationales = br.get("rationales", {})
        for rid, v in verdicts.items():
            marker = "NO " if v == "no" else "yes"
            print(f"    [{marker}] {rid}: {rationales.get(rid, '')[:300]}")

        print("\n-- Phase C (all-at-once) --")
        cr = c.get(tid, {})
        pred = cr.get("prediction") or {}
        print(f"  predicted: {pred.get('predicted_cluster')}  level: {pred.get('predicted_level')}  origin_step: {pred.get('predicted_origin_step')}  confidence: {pred.get('confidence')}")
        print(f"  evidence_steps: {pred.get('evidence_steps')}")
        if pred.get("unassignable"):
            print(f"  unassignable_reason: {pred.get('unassignable_reason')}")
        reasoning = pred.get("reasoning", "")
        print(f"  reasoning:")
        for line in reasoning.split("\n"):
            print(f"    {line}")


if __name__ == "__main__":
    main()
