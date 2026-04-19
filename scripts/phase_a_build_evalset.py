"""Phase A — Build ADK-compatible EvalSet files.

Reads split files produced by phase_a_split.py and emits ADK EvalSet JSON
files. Each split produces two artifacts:

  data/evalsets/{split}.evalset.json           # judge-visible (no gt)
  data/evalsets/{split}.with_gt.evalset.json   # scoring-side (includes gt)

Design notes
------------
ADK's native `Invocation` shape (user_content + final_response + tool_uses)
does not cleanly represent multi-agent W&W conversations where messages
alternate between a manager, a computer terminal, and several named experts.
Rather than lossily collapse the trajectory into ADK Invocations, we:

  1. Synthesize ONE minimal Invocation per trajectory so the EvalSet is
     valid ADK JSON and the built-in evaluators (rubric_based_...,
     final_response_match_v2) have the surface they expect:
        - user_content    <- first `user` message in history
        - final_response  <- last non-terminator message in history
  2. Stash the FULL native trajectory under `eval_case.metadata.trajectory`
     so our custom Evaluators (AllAtOnce, BinarySearch, ConstraintGrounded)
     can read it verbatim via TrajectoryReplayer.
  3. For `*.with_gt.evalset.json`, also stash the `gt` block under
     `eval_case.metadata.gt`. The no-gt file omits this key entirely.

ADK is documented to ignore unknown fields at load (see adk_eval_suite_notes.md),
so extra metadata keys are safe.

Usage:
    python3 scripts/phase_a_build_evalset.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLIT_DIR = REPO_ROOT / "data" / "splits"
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"

SPLITS = ("dev", "calibration", "eval")

TERMINATOR_TOKENS = {"TERMINATE", "TERMINATE.", "[TERMINATE]"}


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def first_user_message(history: list[dict]) -> str:
    for msg in history:
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
    # Fallback: first message content.
    if history:
        return str(history[0].get("content") or "")
    return ""


def final_response_text(history: list[dict]) -> str:
    """Last substantive message, skipping trailing 'TERMINATE' tokens."""
    for msg in reversed(history):
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        if stripped in TERMINATOR_TOKENS:
            continue
        return content
    return ""


def content_block(text: str, role: str) -> dict:
    """ADK Content shape: {parts: [{text}], role}."""
    return {"parts": [{"text": text or ""}], "role": role}


def build_eval_case(clean_rec: dict, gt_rec: dict | None, now: float) -> dict:
    """Produce one EvalCase. If gt_rec is None, no gt block is attached."""
    tid = clean_rec["trajectory_id"]
    history = clean_rec["history"]

    invocation = {
        "invocation_id": f"{tid}-inv-0",
        "user_content": content_block(first_user_message(history), role="user"),
        "final_response": content_block(final_response_text(history), role="model"),
        "intermediate_data": {
            "tool_uses": [],
            "intermediate_responses": [],
        },
        "creation_timestamp": now,
    }

    metadata = {
        "source": clean_rec.get("source"),
        "llm": clean_rec.get("llm"),
        "agent_role": clean_rec.get("agent_role"),
        "gaia_question_id": clean_rec.get("gaia_question_id") or clean_rec.get("gaia_question_id_prefix"),
        # Full native trajectory for TrajectoryReplayer-style custom evaluators.
        "trajectory": history,
        "trajectory_metadata": clean_rec.get("metadata") or {},
    }
    if gt_rec is not None:
        metadata["gt"] = gt_rec["gt"]

    return {
        "eval_id": tid,
        "conversation": [invocation],
        "session_input": {
            "app_name": "failure_attribution_eval",
            "user_id": "mel",
            "state": {},
        },
        "creation_timestamp": now,
        "metadata": metadata,
    }


def build_eval_set(
    eval_set_id: str,
    clean_records: list[dict],
    gt_records: list[dict] | None,
    now: float,
) -> dict:
    if gt_records is not None:
        gt_by_id = {r["trajectory_id"]: r for r in gt_records}
        cases = [build_eval_case(r, gt_by_id[r["trajectory_id"]], now) for r in clean_records]
    else:
        cases = [build_eval_case(r, None, now) for r in clean_records]

    return {
        "eval_set_id": eval_set_id,
        "name": eval_set_id,
        "description": f"Failure-attribution EvalSet — {eval_set_id}",
        "eval_cases": cases,
        "creation_timestamp": now,
    }


def main() -> int:
    EVALSET_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()

    total_cases = 0
    for split in SPLITS:
        clean_path = SPLIT_DIR / f"{split}_clean.jsonl"
        gt_path = SPLIT_DIR / f"{split}.jsonl"
        if not clean_path.exists() or not gt_path.exists():
            print(f"ERROR: missing split files for {split}; run phase_a_split.py first", file=sys.stderr)
            return 1

        clean_records = load_jsonl(clean_path)
        gt_records = load_jsonl(gt_path)
        assert len(clean_records) == len(gt_records), f"{split}: clean/gt count mismatch"

        # Judge-visible EvalSet (no gt).
        judge_set = build_eval_set(f"gaia_failure_attribution_{split}", clean_records, None, now)
        judge_path = EVALSET_DIR / f"{split}.evalset.json"
        judge_path.write_text(json.dumps(judge_set, ensure_ascii=False, indent=2))

        # Scoring-side EvalSet (gt included in metadata).
        score_set = build_eval_set(f"gaia_failure_attribution_{split}_with_gt", clean_records, gt_records, now)
        score_path = EVALSET_DIR / f"{split}.with_gt.evalset.json"
        score_path.write_text(json.dumps(score_set, ensure_ascii=False, indent=2))

        print(f"{split}: {len(clean_records)} cases -> {judge_path.name}, {score_path.name}")
        total_cases += len(clean_records)

    print(f"\nTotal cases: {total_cases}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
