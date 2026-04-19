"""Phase C.2 — BinarySearchAttribution.

Localizes the origin step via log-bisection over the trajectory. At each
midpoint k the judge is asked a single yes/no: "By step k (inclusive), has
the trajectory diverged from the task goal?" A `yes` narrows the search to
[lo, k]; a `no` narrows it to [k+1, hi]. When lo == hi, that step is the
predicted origin. A final structured-JSON call then classifies the
localized step's cluster, level, and confidence.

Binary search is inherently sequential per trajectory (each decision depends
on the previous), so this runner uses `google.genai` async in online mode
with a semaphore bounding cross-trajectory parallelism. It does NOT go
through Vertex batch.

Per trajectory cost: roughly ceil(log2(n_steps)) + 1 judge calls. For a
median-length trajectory in this corpus (~10 steps) that's ~5 calls; for
the long W&W tail (>100 steps) it's ~8. Classification call always 1.

Usage:
    python3 scripts/phase_c_binary_search.py --split dev --limit 2
    python3 scripts/phase_c_binary_search.py --split eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "binary_search"

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
LEVELS = ["node", "process"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_IDS}

# Shared signatures with phase_c_all_at_once — kept in this file so each Phase C
# evaluator is self-contained and can be diffed against in isolation.
CLUSTER_SIGNATURES = {
    "N1": "Hallucination / factual fabrication — the final response asserts a specific factual claim (name, number, date, identifier, URL, quotation) that is not grounded in any tool output or retrieved source the agent actually obtained.",
    "N2": "Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors (wrong algorithm, off-by-one indexing, incorrect aggregation, mishandled null/NaN/empty edge cases).",
    "N3": "Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty/malformed result, context-limit cut-off), and the agent proceeded with degraded information or gave up.",
    "N4": "Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask (e.g., generic web search when a specific API was available), despite an appropriate tool being available.",
    "N5": "Invalid tool parameters / input — the agent called an appropriate tool with malformed, missing, or mis-scoped arguments (wrong file path, placeholder like 'example_id', schema violation, bad query string).",
    "P1": "Improper task decomposition / bad plan — the plan itself is structurally wrong (skipped required step, wrong ordering, wrong goal, infeasible methodology) such that the task could not succeed even if every individual step executed perfectly.",
    "P2": "Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification, misread a tool output as confirming the answer when it did not).",
    "P3": "Cascading error (explicit propagation) — an earlier origin error was carried forward by later agents or steps without re-verification, and the final wrong answer traces explicitly to the earlier step.",
    "P4": "Constraint ignorance / unchecked assumption — the agent accepted a value or drew a conclusion without checking a specific constraint the task stated or implied (year, units, scope, 'as of', 'excluding X').",
}

# Per-step cap to keep prompts under the Gemini 2.5 context ceiling even when
# individual steps are huge (W&W orchestrator ledgers occasionally blow past
# 20k chars). Matches phase_c_all_at_once for consistency.
MAX_STEP_CHARS = 4000


def _truncate(content: str, limit: int = MAX_STEP_CHARS) -> str:
    if len(content) <= limit:
        return content
    head = content[: limit // 2]
    tail = content[-(limit // 2) :]
    return f"{head}\n... [truncated {len(content) - limit} chars] ...\n{tail}"


def _content_str(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    return json.dumps(c, ensure_ascii=False)


def build_trajectory_block(history: list[dict], lo: int, hi: int) -> str:
    """Render steps [lo, hi] (inclusive) with step index + author headers."""
    lines = []
    for i in range(lo, hi + 1):
        msg = history[i]
        author = msg.get("name") or msg.get("role") or "agent"
        content = _truncate(_content_str(msg))
        lines.append(f"### Step {i} — author={author}\n{content}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Prompts


BISECTION_SYSTEM = """You are a bisection judge for a pre-recorded failed GAIA multi-agent trajectory. The trajectory has already been confirmed to fail overall. Your job is binary: by the end of the specified inclusive prefix, has the trajectory ALREADY diverged from the path to the correct answer?

"Diverged" means: an error has been introduced that, if not corrected, prevents the trajectory from reaching the correct answer. The error may be a wrong fact, a bad plan decision, a mis-selected tool, a tool failure that was accepted, a false progress claim, or an unchecked constraint.

Do NOT say "yes" just because the task is not yet complete in the prefix. The prefix can be fine-so-far even if the work is unfinished; only say "yes" if something the agent DID in the prefix has already broken the path to the correct answer.

Output contract: a JSON object with EXACTLY these keys (no extras, no missing):

{
  "reasoning": "<2-4 sentences citing specific step indices>",
  "diverged": <true or false>
}

Do not wrap the JSON in markdown code fences. Do not add any text before or after.
"""


def _cluster_block() -> str:
    return "\n".join(f"- **{cid}** — {sig}" for cid, sig in CLUSTER_SIGNATURES.items())


CLASSIFICATION_SYSTEM_TEMPLATE = """You are a failure-attribution judge for a pre-recorded GAIA multi-agent trajectory. A prior bisection pass has already localized the suspected origin step. Your job: confirm the origin step and classify the failure against the 9-cluster taxonomy.

**Taxonomy (node-level = single-step; process-level = multi-step/structural):**
{clusters}

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- P3 requires a specific earlier wrong value that propagates. If the origin is a hallucination that downstream steps echo, prefer N1 at the origin step over P3 at the symptom step.
- P4 vs N1: P4 is an unchecked constraint on a real retrieved value; N1 is a fabricated value.
- P1 vs P2: P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."

Output contract: a JSON object with EXACTLY these keys (no extras, no missing):

{{
  "reasoning": "<walk through the cited origin step and its neighbors; explain why the cluster fits>",
  "evidence_steps": [<1-5 integer step indices you cited>],
  "predicted_origin_step": <0-indexed integer; may confirm the bisected step or adjust by +/- up to the provided window>,
  "predicted_cluster": "<one of: N1 N2 N3 N4 N5 P1 P2 P3 P4>",
  "predicted_level": "<node or process; N* -> node, P* -> process>",
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false>,
  "unassignable_reason": "<if unassignable, explain; else empty string>"
}}

Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.
"""


# ---------------------------------------------------------------------------
# LLM calls


async def judge_bisection(client, model: str, task: str, history: list[dict], k: int) -> dict:
    """Ask the judge: has the trajectory diverged by step k (inclusive)?"""
    user = (
        f"**User task:**\n{task}\n\n"
        f"**Trajectory steps 0..{k} (inclusive):**\n"
        f"{build_trajectory_block(history, 0, k)}\n\n"
        f"Has the trajectory already diverged by end of step {k}? Return JSON.\n"
    )
    from google.genai import types as gt

    resp = await client.aio.models.generate_content(
        model=model,
        contents=[gt.Content(role="user", parts=[gt.Part(text=user)])],
        config=gt.GenerateContentConfig(
            system_instruction=BISECTION_SYSTEM,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    text = resp.text or ""
    return json.loads(text)


async def judge_classify(
    client, model: str, task: str, history: list[dict], localized_step: int, window: int = 3
) -> dict:
    """After localization, classify the failure at the localized step."""
    from google.genai import types as gt

    lo = max(0, localized_step - window)
    hi = min(len(history) - 1, localized_step + window)
    ctx_block = build_trajectory_block(history, lo, hi)

    user = (
        f"**User task:**\n{task}\n\n"
        f"**Bisection-localized origin step:** {localized_step}\n"
        f"**Window shown (steps {lo}..{hi}):**\n{ctx_block}\n\n"
        "Confirm or adjust the origin step, then classify. Return JSON.\n"
    )
    sys_prompt = CLASSIFICATION_SYSTEM_TEMPLATE.format(clusters=_cluster_block())

    resp = await client.aio.models.generate_content(
        model=model,
        contents=[gt.Content(role="user", parts=[gt.Part(text=user)])],
        config=gt.GenerateContentConfig(
            system_instruction=sys_prompt,
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    text = resp.text or ""
    return json.loads(text)


# ---------------------------------------------------------------------------
# Per-trajectory driver


def _extract_task(eval_case: dict) -> str:
    """Prefer the synthesized user_content from Phase A; fall back to step 0."""
    conv = eval_case.get("conversation", [])
    if conv:
        parts = conv[0].get("user_content", {}).get("parts", [])
        if parts:
            t = parts[0].get("text", "")
            if t:
                return t
    history = eval_case["metadata"]["trajectory"]
    return _content_str(history[0]) if history else ""


async def run_case(client, model: str, eval_case: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        history = eval_case["metadata"]["trajectory"]
        task = _extract_task(eval_case)
        tid = eval_case["eval_id"]
        gt = eval_case["metadata"].get("gt", {})
        base = {
            "trajectory_id": tid,
            "gt_cluster": gt.get("proposed_cluster"),
            "gt_level": gt.get("proposed_level"),
            "gt_origin_step": gt.get("critical_failure_step"),
            "n_steps": len(history),
        }
        t0 = time.time()

        if len(history) < 2:
            return {
                **base,
                "prediction": None,
                "bisection_log": [],
                "n_bisection_calls": 0,
                "error": "trajectory too short for bisection",
                "elapsed_s": round(time.time() - t0, 2),
            }

        # Binary search over step indices [lo, hi]. Invariant: the origin is
        # somewhere in [lo, hi]. `yes` at k means origin <= k (narrow hi to k);
        # `no` at k means origin > k (narrow lo to k+1). We skip step 0 as a
        # candidate origin because step 0 is the user prompt itself in both AEB
        # and W&W formats (the agent hasn't acted yet).
        lo, hi = 1, len(history) - 1
        bisection_log: list[dict] = []
        try:
            while lo < hi:
                mid = (lo + hi) // 2
                result = await judge_bisection(client, model, task, history, mid)
                diverged = bool(result.get("diverged"))
                bisection_log.append(
                    {
                        "step": mid,
                        "lo_before": lo,
                        "hi_before": hi,
                        "diverged": diverged,
                        "reasoning": result.get("reasoning"),
                    }
                )
                if diverged:
                    hi = mid
                else:
                    lo = mid + 1
            localized = lo
            classification = await judge_classify(client, model, task, history, localized)
            # Sanity-normalize level
            pc = classification.get("predicted_cluster")
            if pc in CLUSTER_LEVEL:
                classification["predicted_level"] = CLUSTER_LEVEL[pc]
            return {
                **base,
                "bisected_origin_step": localized,
                "n_bisection_calls": len(bisection_log),
                "bisection_log": bisection_log,
                "prediction": classification,
                "error": None,
                "elapsed_s": round(time.time() - t0, 2),
            }
        except Exception as e:
            return {
                **base,
                "bisected_origin_step": None,
                "n_bisection_calls": len(bisection_log),
                "bisection_log": bisection_log,
                "prediction": None,
                "error": f"{type(e).__name__}: {e}",
                "elapsed_s": round(time.time() - t0, 2),
            }


async def run_split(
    split: str,
    judge_model: str,
    parallelism: int,
    limit: int | None,
) -> int:
    evalset_path = EVALSET_DIR / f"{split}.with_gt.evalset.json"
    if not evalset_path.exists():
        print(f"ERROR: {evalset_path} not found", file=sys.stderr)
        return 1
    evalset = json.loads(evalset_path.read_text())
    cases = evalset["eval_cases"]
    if limit:
        cases = cases[:limit]

    from google import genai

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    client = genai.Client(vertexai=True, project=project, location="global")

    print(f"Phase C BinarySearch | split={split} | n={len(cases)} | model={judge_model} | parallelism={parallelism}")

    run_id = f"phase-c-bs-{split}-{time.strftime('%Y%m%dT%H%M%S')}"
    out_dir = OUTPUT_DIR / split / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    per_case_path = out_dir / "per_case.jsonl"

    sem = asyncio.Semaphore(parallelism)
    tasks = [run_case(client, judge_model, c, sem) for c in cases]

    t0 = time.time()
    done = 0
    records: list[dict] = []
    with per_case_path.open("w") as f:
        for fut in asyncio.as_completed(tasks):
            r = await fut
            records.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            done += 1
            pred_cluster = (r.get("prediction") or {}).get("predicted_cluster")
            status = "OK" if r["error"] is None else f"ERR({r['error'][:60]})"
            print(
                f"  [{done}/{len(cases)}] {r['trajectory_id']}: "
                f"bs_step={r.get('bisected_origin_step')} pred={pred_cluster} "
                f"gt={r['gt_cluster']}@{r['gt_origin_step']} "
                f"calls={r['n_bisection_calls']}+1 ({status}, {r['elapsed_s']}s)"
            )

    elapsed = time.time() - t0

    # Summary
    errors = [r for r in records if r.get("error")]

    def cluster_match(r):
        p = r.get("prediction") or {}
        return p.get("predicted_cluster") == r["gt_cluster"]

    def level_match(r):
        p = r.get("prediction") or {}
        return p.get("predicted_level") == r["gt_level"]

    def step_within(r, tol, key):
        p = r.get("prediction") or {}
        gt = r.get("gt_origin_step")
        val = r.get(key) if key == "bisected_origin_step" else p.get("predicted_origin_step")
        if gt is None or val is None:
            return False
        return abs(int(val) - int(gt)) <= tol

    correct_cluster = sum(1 for r in records if cluster_match(r))
    correct_level = sum(1 for r in records if level_match(r))
    bs_step_t0 = sum(1 for r in records if step_within(r, 0, "bisected_origin_step"))
    bs_step_t3 = sum(1 for r in records if step_within(r, 3, "bisected_origin_step"))
    clf_step_t0 = sum(1 for r in records if step_within(r, 0, "predicted_origin_step"))
    clf_step_t3 = sum(1 for r in records if step_within(r, 3, "predicted_origin_step"))
    unassignable = sum(
        1 for r in records if (r.get("prediction") or {}).get("unassignable")
    )

    confusion: defaultdict = defaultdict(Counter)
    for r in records:
        pred = (r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED"
        confusion[r["gt_cluster"]][pred] += 1

    total_calls = sum(r["n_bisection_calls"] + (1 if r.get("prediction") else 0) for r in records)
    mean_calls = total_calls / max(1, len(records))

    summary = {
        "split": split,
        "judge_model": judge_model,
        "run_id": run_id,
        "n_cases": len(records),
        "wall_time_s": round(elapsed, 1),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "origin_step_tol0_bisected": round(bs_step_t0 / max(1, len(records)), 3),
        "origin_step_tol3_bisected": round(bs_step_t3 / max(1, len(records)), 3),
        "origin_step_tol0_classified": round(clf_step_t0 / max(1, len(records)), 3),
        "origin_step_tol3_classified": round(clf_step_t3 / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "mean_judge_calls_per_case": round(mean_calls, 2),
        "expected_log2_calls": round(
            sum(math.ceil(math.log2(max(2, r["n_steps"]))) for r in records) / max(1, len(records)),
            2,
        ),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(((r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED") for r in records)
        ),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Phase C BinarySearch Summary ({split}) ===")
    print(f"  Cases: {summary['n_cases']}  Errors: {summary['errors']}  Wall: {summary['wall_time_s']}s")
    print(f"  Cluster accuracy: {summary['cluster_accuracy']}")
    print(f"  Level accuracy:   {summary['level_accuracy']}")
    print(f"  Origin-step (bisected)   tol-3/tol-0: {summary['origin_step_tol3_bisected']} / {summary['origin_step_tol0_bisected']}")
    print(f"  Origin-step (classified) tol-3/tol-0: {summary['origin_step_tol3_classified']} / {summary['origin_step_tol0_classified']}")
    print(f"  Mean judge calls/case: {summary['mean_judge_calls_per_case']} (expected ~{summary['expected_log2_calls']})")
    print(f"  Outputs: {out_dir}/")
    return 0 if not errors else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "calibration", "eval"), default="dev")
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

    return asyncio.run(
        run_split(args.split, args.judge_model, args.parallelism, args.limit)
    )


if __name__ == "__main__":
    sys.exit(main())
