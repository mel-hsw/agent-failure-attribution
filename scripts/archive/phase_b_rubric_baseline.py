"""Phase B — Off-the-shelf ADK rubric-based baseline.

Runs the built-in `rubric_based_final_response_quality_v1` evaluator on a
pre-recorded EvalSet with our 9-cluster rubric (one yes/no rubric per
cluster). Because our trajectories come pre-recorded from AEB / W&W, we
bypass the `adk eval` CLI (which wants a live agent to replay against) and
construct the Evaluator directly, then call `evaluate_invocations`.

For each eval case we:
  1. Reconstruct a single ADK `Invocation` from the case's history. Multi-
     agent W&W roles are flattened into `intermediate_data.tool_uses` so
     the judge has visible "steps" in the prompt's <response_steps> block.
  2. Attach the 9 rubrics to the invocation (per-invocation rubrics are
     what the evaluator expects — see `actual_invocation.rubrics` in
     rubric_based_final_response_quality_v1.py).
  3. Call `evaluate_invocations([inv])` and collect per-rubric scores.
  4. Pick the predicted cluster: highest rubric score, ties broken by a
     fixed priority order. Record unassignable if all rubrics score 0.

Outputs (under outputs/phase_b/<split>/):
  - per_case.jsonl — one line per trajectory with full rubric scores,
    predicted cluster, ground-truth cluster, raw rationales.
  - summary.json   — aggregate accuracy, per-cluster confusion, wall-time,
    estimated sample count.

Authentication
--------------
Reads credentials from the repo-local .env file (if present) before
touching ADK. Supports:
  - GEMINI_API_KEY / GOOGLE_API_KEY (AI Studio; simplest)
  - GOOGLE_GENAI_USE_VERTEXAI=1 + GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION
    (plus `gcloud auth application-default login` on the host)

Usage:
    python3 scripts/phase_b_rubric_baseline.py --split dev --num-samples 1
    python3 scripts/phase_b_rubric_baseline.py --split eval --num-samples 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"
RUBRIC_FILE = REPO_ROOT / "data" / "rubrics" / "option_b_rubric.json"
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_b"

# Tie-break order when multiple rubrics score the same. Node-level clusters
# are generally more specific than process-level; within a level, rarer
# clusters come first so they're not masked by a broad-signature false positive.
CLUSTER_PRIORITY = ["N5", "N4", "N3", "N2", "N1", "P4", "P3", "P2", "P1"]


def load_env() -> None:
    """Load .env from repo root if present; warn if no credentials found."""
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"Loaded .env from {env_path}")
    else:
        print("No .env file found — relying on shell environment.")

    using_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    if using_vertex:
        needed = ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION")
        missing = [k for k in needed if not os.environ.get(k)]
        if missing:
            print(f"WARN: Vertex AI mode but missing env: {missing}", file=sys.stderr)
        else:
            print(f"Auth mode: Vertex AI (project={os.environ['GOOGLE_CLOUD_PROJECT']}, location={os.environ['GOOGLE_CLOUD_LOCATION']})")
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        print("Auth mode: AI Studio (GEMINI_API_KEY)")
    else:
        print("WARN: no Gemini credentials detected; the evaluator will fail at first judge call.", file=sys.stderr)


def load_rubrics():
    """Deferred ADK import so load_env runs first."""
    from google.adk.evaluation.eval_rubrics import Rubric, RubricContent

    data = json.loads(RUBRIC_FILE.read_text())
    rubrics = [
        Rubric(
            rubric_id=r["rubric_id"],
            rubric_content=RubricContent(text_property=r["rubric_content"]["text_property"]),
            type=r.get("type", "FINAL_RESPONSE_QUALITY"),
            description=r.get("description"),
        )
        for r in data["rubrics"]
    ]
    return rubrics


def build_invocation(eval_case: dict, rubrics: list):
    """Construct an ADK Invocation from an eval case's metadata.trajectory.

    Strategy: the first user message becomes user_content; the last
    substantive message becomes final_response; intermediate messages are
    flattened into intermediate_data.tool_uses so the judge's prompt shows
    them in the <response_steps> block. Multi-agent role/name pairs are
    preserved by prefixing the tool name with the author.
    """
    from google.adk.evaluation.eval_case import IntermediateData, Invocation
    from google.genai import types as gt

    history = eval_case["metadata"]["trajectory"]
    tid = eval_case["eval_id"]

    # Echo what the converter already synthesized into conversation[0].
    base_inv = eval_case["conversation"][0]
    user_text = base_inv["user_content"]["parts"][0].get("text", "")
    final_text = (base_inv.get("final_response") or {"parts": [{"text": ""}]})["parts"][0].get("text", "")

    # Build synthetic FunctionCall / FunctionResponse pairs so the judge's
    # prompt renders the intermediate messages as <response_steps>. Each
    # step becomes one call + one response. Multi-agent authorship is
    # surfaced in the tool name. Skip index 0 (user_content) and the last
    # message (final_response) to avoid double-counting.
    intermediates = history[1:-1] if len(history) >= 2 else []
    tool_uses: list = []
    tool_responses: list = []
    for i, msg in enumerate(intermediates):
        author = msg.get("name") or msg.get("role") or "agent"
        content = msg.get("content")
        content_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        step_id = f"step_{i + 1}"
        tool_name = f"{step_id}__{author}"[:60]  # keep short — FunctionCall.name is bounded
        tool_uses.append(
            gt.FunctionCall(id=step_id, name=tool_name, args={"step_index": i + 1, "author": author})
        )
        tool_responses.append(
            gt.FunctionResponse(id=step_id, name=tool_name, response={"text": content_text})
        )

    # Rubrics live on the criterion (registered via build_evaluator); per-
    # invocation rubrics would duplicate them and trip ADK's uniqueness check.
    return Invocation(
        invocation_id=f"{tid}-inv-0",
        user_content=gt.Content(parts=[gt.Part(text=user_text or "")], role="user"),
        final_response=gt.Content(parts=[gt.Part(text=final_text or "")], role="model"),
        intermediate_data=IntermediateData(
            tool_uses=tool_uses,
            tool_responses=tool_responses,
            intermediate_responses=[],
        ),
    )


def build_evaluator(judge_model: str, num_samples: int, rubrics):
    from google.adk.evaluation.eval_metrics import (
        EvalMetric,
        JudgeModelOptions,
        RubricsBasedCriterion,
    )
    from google.adk.evaluation.rubric_based_final_response_quality_v1 import (
        RubricBasedFinalResponseQualityV1Evaluator,
    )

    # ADK's RubricBasedEvaluator asserts rubrics are non-empty on the
    # criterion. Rubrics on the invocation override per-case, but the
    # criterion still needs the full set registered.
    criterion = RubricsBasedCriterion(
        threshold=0.5,
        rubrics=rubrics,
        judge_model_options=JudgeModelOptions(
            judge_model=judge_model,
            num_samples=num_samples,
        ),
    )
    metric = EvalMetric(
        metric_name="rubric_based_final_response_quality_v1",
        threshold=0.5,
        criterion=criterion,
    )
    return RubricBasedFinalResponseQualityV1Evaluator(eval_metric=metric)


def extract_rubric_scores(eval_result) -> dict[str, float]:
    """Walk evaluation_result.per_invocation_results and pull rubric scores."""
    out: dict[str, float] = {}
    per_inv = getattr(eval_result, "per_invocation_results", None) or []
    for r in per_inv:
        for rs in (getattr(r, "rubric_scores", None) or []):
            if rs.rubric_id and rs.score is not None:
                out[rs.rubric_id] = float(rs.score)
    return out


def predict_cluster(rubric_scores: dict[str, float]) -> tuple[str | None, float, bool]:
    """Pick the predicted cluster under positive-correctness polarity.

    Each rubric is phrased so `Verdict: yes` (score 1.0) means "this failure
    did NOT occur" and `Verdict: no` (score 0.0) means "this failure DID
    occur". The predicted cluster is the one scoring lowest (argmin). Ties
    among 0.0-scorers are broken by CLUSTER_PRIORITY.

    Returns (cluster_id, min_score, unassignable). Unassignable=True means
    every rubric scored 1.0 (judge saw no failure signature at all).
    """
    if not rubric_scores:
        return None, 1.0, True
    min_score = min(rubric_scores.values())
    if min_score >= 1.0:
        return None, min_score, True
    winners = [c for c, s in rubric_scores.items() if s == min_score]
    for cid in CLUSTER_PRIORITY:
        if cid in winners:
            return cid, min_score, False
    return winners[0], min_score, False


async def run_case(evaluator, eval_case: dict, rubrics, semaphore):
    async with semaphore:
        inv = build_invocation(eval_case, rubrics)
        t0 = time.time()
        try:
            result = await evaluator.evaluate_invocations(actual_invocations=[inv])
            scores = extract_rubric_scores(result)
            predicted, min_score, unassignable = predict_cluster(scores)
            # Surface rationales from the result for inspection.
            rationales = {}
            for pir in (getattr(result, "per_invocation_results", None) or []):
                for rs in (getattr(pir, "rubric_scores", None) or []):
                    if rs.rationale:
                        rationales[rs.rubric_id] = rs.rationale
            return {
                "trajectory_id": eval_case["eval_id"],
                "elapsed_s": round(time.time() - t0, 2),
                "rubric_scores": scores,
                "rationales": rationales,
                "predicted_cluster": predicted,
                "predicted_min_score": min_score,
                "unassignable": unassignable,
                "gt_cluster": eval_case["metadata"].get("gt", {}).get("proposed_cluster"),
                "gt_level": eval_case["metadata"].get("gt", {}).get("proposed_level"),
                "error": None,
            }
        except Exception as e:
            return {
                "trajectory_id": eval_case["eval_id"],
                "elapsed_s": round(time.time() - t0, 2),
                "rubric_scores": {},
                "rationales": {},
                "predicted_cluster": None,
                "predicted_min_score": 1.0,
                "unassignable": True,
                "gt_cluster": eval_case["metadata"].get("gt", {}).get("proposed_cluster"),
                "gt_level": eval_case["metadata"].get("gt", {}).get("proposed_level"),
                "error": f"{type(e).__name__}: {e}",
            }


async def run_split(split: str, judge_model: str, num_samples: int, parallelism: int, limit: int | None):
    evalset_path = EVALSET_DIR / f"{split}.with_gt.evalset.json"
    if not evalset_path.exists():
        print(f"ERROR: {evalset_path} not found; run Phase A first", file=sys.stderr)
        return 1

    evalset = json.loads(evalset_path.read_text())
    cases = evalset["eval_cases"]
    if limit:
        cases = cases[:limit]
    print(f"Running Phase B on {len(cases)} cases from {split}.")

    rubrics = load_rubrics()
    evaluator = build_evaluator(judge_model, num_samples, rubrics)
    print(f"Judge: {judge_model} (num_samples={num_samples}), rubrics: {[r.rubric_id for r in rubrics]}")

    semaphore = asyncio.Semaphore(parallelism)
    t0 = time.time()
    tasks = [run_case(evaluator, c, rubrics, semaphore) for c in cases]

    out_dir = OUTPUT_DIR / split
    out_dir.mkdir(parents=True, exist_ok=True)
    per_case_path = out_dir / "per_case.jsonl"

    done = 0
    with per_case_path.open("w") as f:
        for fut in asyncio.as_completed(tasks):
            r = await fut
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            done += 1
            status = "OK" if r["error"] is None else f"ERR({r['error'][:60]})"
            print(f"  [{done}/{len(cases)}] {r['trajectory_id']}: pred={r['predicted_cluster']} gt={r['gt_cluster']} ({status}, {r['elapsed_s']}s)")

    elapsed = time.time() - t0

    # Summary
    records = [json.loads(l) for l in open(per_case_path)]
    errors = [r for r in records if r["error"]]
    correct_cluster = sum(1 for r in records if r["predicted_cluster"] == r["gt_cluster"])
    correct_level = sum(
        1 for r in records
        if r["predicted_cluster"] and r["gt_level"]
        and (r["predicted_cluster"][0].lower() == ("n" if r["gt_level"] == "node" else "p"))
    )
    unassignable = sum(1 for r in records if r["unassignable"])

    confusion = defaultdict(Counter)
    for r in records:
        confusion[r["gt_cluster"]][r["predicted_cluster"] or "UNASSIGNED"] += 1

    summary = {
        "split": split,
        "judge_model": judge_model,
        "num_samples": num_samples,
        "n_cases": len(records),
        "wall_time_s": round(elapsed, 1),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(Counter(r["predicted_cluster"] or "UNASSIGNED" for r in records)),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Summary ({split}) ===")
    print(f"  Wall time: {summary['wall_time_s']}s")
    print(f"  Errors: {summary['errors']}")
    print(f"  Cluster accuracy: {summary['cluster_accuracy']}")
    print(f"  Level accuracy:   {summary['level_accuracy']}")
    print(f"  Unassignable:     {summary['unassignable_rate']}")
    print(f"  Outputs: {out_dir}/")
    return 0 if not errors else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "calibration", "eval"), default="dev")
    parser.add_argument("--judge-model", default="gemini-2.5-flash",
                        help="ADK-resolved judge model string")
    parser.add_argument("--num-samples", type=int, default=1,
                        help="Judge samples per invocation (ADK default is 5)")
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="Cap number of cases (debugging)")
    args = parser.parse_args()

    load_env()
    return asyncio.run(run_split(args.split, args.judge_model, args.num_samples, args.parallelism, args.limit))


if __name__ == "__main__":
    sys.exit(main())
