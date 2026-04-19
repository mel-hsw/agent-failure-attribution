"""Phase C.1 prompt-improvement SMOKE TEST (v2 prompt).

Runs sync (not batch) against dev split to quickly A/B the v2 prompt
against the baseline. Writes output to outputs/phase_c/all_at_once/dev_v2/.

Changes from baseline (phase_c_all_at_once.py):
  1. Staged decision: judge picks predicted_level FIRST, then commits to cluster.
  2. `no_failure` added to predicted_cluster enum — judge can say "I don't
     see a failure in this trajectory" without being forced to confabulate.
  3. P3 disambiguation rewritten to match dataset's actual P3 labels:
     pick P3 when propagation is visible in the reasoning trace, even if
     the origin step's event is node-level.
  4. P1-vs-N1 and N4-vs-P1 disambiguation added.

Usage:
    python3 scripts/phase_c_all_at_once_v2_smoke.py        # dev smoke, 5 cases
    python3 scripts/phase_c_all_at_once_v2_smoke.py --limit 3  # 3 cases only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALSET = REPO_ROOT / "data" / "evalsets" / "dev.with_gt.evalset.json"
OUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "all_at_once" / "dev_v2"

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4", "no_failure"]

CLUSTER_SIGNATURES = {
    "N1": "Hallucination / factual fabrication — the final response asserts a specific factual claim (name, number, date, identifier, URL, quotation) that is not grounded in any tool output or retrieved source the agent actually obtained. The agent invented the value.",
    "N2": "Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors (wrong algorithm, off-by-one indexing, incorrect aggregation, mishandled null/NaN/empty edge cases). Visible in the code body itself.",
    "N3": "Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty/malformed result, context-limit cut-off), and the agent proceeded with degraded information or gave up. The fault is in the environment, not the agent's reasoning.",
    "N4": "Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask (e.g., generic web search when a specific API was available, OCR on text, summarizer when extraction was needed), despite an appropriate tool being available. The failure is the selection decision, not the execution.",
    "N5": "Invalid tool parameters / input — the agent called an appropriate tool with malformed, missing, or mis-scoped arguments (wrong file path, placeholder like 'example_id', schema violation, bad query string). The tool choice was right; the arguments were wrong.",
    "P1": "Improper task decomposition / bad plan — the plan itself is structurally wrong (skipped required step, wrong ordering, wrong goal, infeasible methodology) such that the task could not succeed even if every individual step executed perfectly.",
    "P2": "Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification, misread a tool output as confirming the answer when it did not). A self-monitoring/reflection failure.",
    "P3": "Cascading error (explicit propagation) — an earlier origin error was carried forward by later agents or steps without re-verification, and the final wrong answer traces explicitly to the earlier step. The late symptom has an earlier identifiable root cause, and the reasoning trace makes the propagation chain VISIBLE (later steps refer back to the upstream value).",
    "P4": "Constraint ignorance / unchecked assumption — the agent accepted a value or drew a conclusion without checking a specific constraint the task stated or implied (year, units, scope, 'as of', 'excluding X'). The plan was otherwise reasonable; one specific verification step was skipped.",
    "no_failure": "No failure detected. The trajectory appears to have completed the task correctly — the final answer is reasonable, grounded in tool outputs, and matches the task requirements. Use sparingly; if there's any clear failure, pick one of the 9 clusters instead.",
}


def build_system_prompt() -> str:
    sig_block = "\n".join(f"- **{cid}** — {sig}" for cid, sig in CLUSTER_SIGNATURES.items())
    return f"""You are a failure-attribution judge for multi-agent GAIA trajectories. Each trajectory is a pre-recorded sequence of steps (one model turn or tool call per step). Your job is to identify WHERE the failure originated and WHICH failure mode it is — or whether no failure is present.

**The 10-option taxonomy (node-level = single-step; process-level = multi-step/structural; plus no_failure):**
{sig_block}

**Your task:** identify the EARLIEST step at which the failure enters the trajectory — not the step at which the wrong final answer becomes visible. For cascading failures (P3), the origin is the earlier step where the bad value was produced, not the final step where it surfaces.

**STAGED DECISION PROCESS (mandatory):**
1. **First, decide `predicted_level`**: is this a `node` failure (single-step localized error), a `process` failure (multi-step structural or cumulative pattern), OR is there `no_failure` (trajectory succeeded)? Commit to level BEFORE picking cluster.
2. **Then, pick `predicted_cluster`** from the signatures that match your chosen level:
   - If level=node: N1, N2, N3, N4, or N5.
   - If level=process: P1, P2, P3, or P4.
   - If level=no_failure: predicted_cluster must be "no_failure".

This staging forces you to engage the node-vs-process distinction explicitly. A common failure mode is picking a cluster first and letting level follow — avoid that.

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- **P3 rule (REWRITTEN):** pick P3 when the reasoning trace makes the propagation chain EXPLICIT — later steps or agents refer back to an earlier value ("using the X from step Y", "following the method from the previous step", "based on Expert_A's earlier finding") AND the final wrong answer traces through that chain. The node-level event is the origin STEP, but the cluster label is P3 because the failure mode is propagation, not the origin event. If the origin is a hallucination that is never re-used downstream, pick N1 instead of P3.
- **P1 vs N1:** N1 is a specific fabricated factual claim in the final answer. P1 is an architecturally infeasible plan — if the plan routes a subtask to a tool that can't do it, requires information not available, or misreads the task from the start, it's P1 even if the specific wrong answer looks like a made-up fact.
- **N4 vs P1:** if the plan is otherwise sound but one specific tool call picked the wrong tool, it's N4. If the plan's decomposition architecturally routes a subtask to an inappropriate tool/agent, it's P1.
- **P4 vs N1:** P4 is an unchecked constraint on a real value (wrong year, wrong scope); N1 is a fabricated value.
- **P1 vs P2:** P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."
- **no_failure is a real option** — use it if the trajectory's final answer is correct, grounded in tool outputs, and matches the task. Don't force a failure label if you don't see one.

**Output contract:** Return a JSON object with EXACTLY these keys (no extras, no missing):

{{
  "reasoning": "<walk through the steps you examined, what evidence you found, and which top 2-3 clusters you considered before picking. Reference step indices explicitly.>",
  "evidence_steps": [<1-5 integer step indices you cited>],
  "predicted_level": "<node, process, or no_failure — decide THIS FIRST>",
  "predicted_cluster": "<one of: N1, N2, N3, N4, N5, P1, P2, P3, P4, no_failure>",
  "predicted_origin_step": <0-indexed integer; use 0 if no_failure>,
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false; true ONLY if failure is present but the 9 clusters don't cover it — this is now rare because `no_failure` handles the other case>,
  "unassignable_reason": "<if unassignable=true, explain; else empty string>"
}}

Emit reasoning FIRST (before committing to a cluster). Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.
"""


def build_trajectory_block(eval_case: dict) -> str:
    history = eval_case["metadata"]["trajectory"]
    lines = []
    for i, msg in enumerate(history):
        author = msg.get("name") or msg.get("role") or "agent"
        content = msg.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if len(content) > 4000:
            content = content[:2000] + "\n... [truncated] ...\n" + content[-1500:]
        lines.append(f"### Step {i} — author={author}\n{content}")
    return "\n\n".join(lines)


def build_user_prompt(eval_case: dict) -> str:
    tid = eval_case["eval_id"]
    task = ""
    conv = eval_case.get("conversation", [])
    if conv:
        parts = conv[0].get("user_content", {}).get("parts", [])
        if parts:
            task = parts[0].get("text", "")
    trajectory = build_trajectory_block(eval_case)
    return (
        f"**Trajectory id:** {tid}\n\n"
        f"**User task:**\n{task}\n\n"
        f"**Trajectory steps:**\n{trajectory}\n\n"
        "Return your JSON attribution now.\n"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

    from google import genai
    from google.genai import types as gt

    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location="global",
    )

    evalset = json.loads(EVALSET.read_text())
    cases = evalset["eval_cases"]
    if args.limit:
        cases = cases[: args.limit]

    sys_prompt = build_system_prompt()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    per_case_path = OUT_DIR / "per_case.jsonl"
    print(f"Phase C.1 v2 smoke | dev | n={len(cases)} | model={args.judge_model}")
    print(f"System prompt length: {len(sys_prompt)}")
    print(f"Output: {per_case_path}")

    records = []
    for i, case in enumerate(cases):
        tid = case["eval_id"]
        t0 = time.time()
        try:
            resp = client.models.generate_content(
                model=args.judge_model,
                contents=build_user_prompt(case),
                config=gt.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            text = resp.text
            parsed = json.loads(text)
            elapsed = round(time.time() - t0, 1)
            gt_meta = case["metadata"].get("gt", {})
            rec = {
                "trajectory_id": tid,
                "elapsed_s": elapsed,
                "prediction": parsed,
                "gt_cluster": gt_meta.get("proposed_cluster"),
                "gt_level": gt_meta.get("proposed_level"),
                "gt_origin_step": gt_meta.get("critical_failure_step"),
                "error": None,
            }
        except Exception as e:
            elapsed = round(time.time() - t0, 1)
            gt_meta = case["metadata"].get("gt", {})
            rec = {
                "trajectory_id": tid,
                "elapsed_s": elapsed,
                "prediction": None,
                "gt_cluster": gt_meta.get("proposed_cluster"),
                "gt_level": gt_meta.get("proposed_level"),
                "gt_origin_step": gt_meta.get("critical_failure_step"),
                "error": f"{type(e).__name__}: {e}",
            }
        records.append(rec)
        p = rec.get("prediction") or {}
        pred_c = p.get("predicted_cluster") or "ERR"
        pred_s = p.get("predicted_origin_step", "?")
        print(f"  [{i+1}/{len(cases)}] {tid[:42]:42s} gt={rec['gt_cluster']:4s}@step{rec['gt_origin_step']:2} pred={pred_c}@step{pred_s} ({elapsed}s)")

    with per_case_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Quick summary
    ok = [r for r in records if r["error"] is None]
    cluster_correct = sum(1 for r in ok if (r["prediction"] or {}).get("predicted_cluster") == r["gt_cluster"])
    level_correct = sum(1 for r in ok if (r["prediction"] or {}).get("predicted_level") == r["gt_level"])
    n = len(records)
    print(f"\n=== v2 Smoke Summary (n={n}) ===")
    print(f"  errors: {n - len(ok)}")
    print(f"  cluster_acc: {cluster_correct}/{n}")
    print(f"  level_acc:   {level_correct}/{n}")


if __name__ == "__main__":
    main()
