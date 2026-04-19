"""Phase C.1 prompt-improvement SMOKE TEST (v3 prompt).

v3 changes from v2:
  - Removes `no_failure` (eval set is confirmed-failure-only; unassignable
    remains for truly uncoverable failure modes).
  - Adds a mandatory two-pass origin-attribution procedure (forward: flag
    symptom steps; backward: trace flagged values upstream to find origin).
  - Adds a P3 confidence-rule: confidence ≤0.65 when propagation chain is
    implicit; higher only when later steps literally refer back.
  - Reasoning contract for P3 asks for origin / propagation / symptom step
    separately and a counterfactual on the origin step.

Output: outputs/phase_c/all_at_once/dev_v3/per_case.jsonl

Usage:
    python3 scripts/phase_c_all_at_once_v3_smoke.py
    python3 scripts/phase_c_all_at_once_v3_smoke.py --limit 3
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
OUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "all_at_once" / "dev_v3"

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]


def build_system_prompt() -> str:
    return """You are a failure-attribution judge for multi-agent GAIA trajectories. Each trajectory is a pre-recorded sequence of steps (one model turn or tool call per step). Your job is to identify WHERE the failure originated and WHICH failure mode it is.

All trajectories in this evaluation set are confirmed failures. no_failure is not a valid output. If you cannot identify a specific cluster, set unassignable: true instead.

**The 9-option taxonomy (node-level = single-step; process-level = multi-step/structural):**
- **N1** — Hallucination / factual fabrication — the final response asserts a specific factual claim (name, number, date, identifier, URL, quotation) that is not grounded in any tool output or retrieved source the agent actually obtained. The agent invented the value.
- **N2** — Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors (wrong algorithm, off-by-one indexing, incorrect aggregation, mishandled null/NaN/empty edge cases). Visible in the code body itself.
- **N3** — Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty/malformed result, context-limit cut-off), and the agent proceeded with degraded information or gave up. The fault is in the environment, not the agent's reasoning.
- **N4** — Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask (e.g., generic web search when a specific API was available, OCR on text, summarizer when extraction was needed), despite an appropriate tool being available. The failure is the selection decision, not the execution.
- **N5** — Invalid tool parameters / input — the agent called an appropriate tool with malformed, missing, or mis-scoped arguments (wrong file path, placeholder like 'example_id', schema violation, bad query string). The tool choice was right; the arguments were wrong.
- **P1** — Improper task decomposition / bad plan — the plan itself is structurally wrong (skipped required step, wrong ordering, wrong goal, infeasible methodology) such that the task could not succeed even if every individual step executed perfectly.
- **P2** — Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification, misread a tool output as confirming the answer when it did not). A self-monitoring/reflection failure.
- **P3** — Cascading error (explicit propagation) — an earlier origin error was carried forward by later agents or steps without re-verification, and the final wrong answer traces explicitly to the earlier step. The late symptom has an earlier identifiable root cause, and the reasoning trace makes the propagation chain VISIBLE (later steps refer back to the upstream value).
- **P4** — Constraint ignorance / unchecked assumption — the agent accepted a value or drew a conclusion without checking a specific constraint the task stated or implied (year, units, scope, 'as of', 'excluding X'). The plan was otherwise reasonable; one specific verification step was skipped.

**STAGED DECISION PROCESS (mandatory, in order):**

Step 1 — Two-pass origin attribution (do this before committing to any cluster):

PASS 1 (forward): Read the trace sequentially. Flag every step where an output, parameter, or state value appears incorrect, inconsistent with prior results, or misaligned with the task goal. These are SYMPTOM steps — mark them but do not classify them as the origin yet.

PASS 2 (backward): For each symptom step, trace the flagged value upstream. At each prior step ask: was this value passed from earlier, or first introduced here? The ORIGIN step is the earliest step where the bad value entered the trajectory — either generated incorrectly by the model, returned incorrectly by a tool, or introduced from invalid prior state.

Classification rules:
— ORIGIN: bad value does not appear in any prior step, OR a prior step produced a valid value that this step transformed incorrectly, OR a tool returned a bad value that was trusted and propagated.
— PROPAGATION: step passed through a bad value it received without generating it.
— SYMPTOM: step where the failure became observable, but the bad value was introduced earlier.

Record the ORIGIN step as predicted_origin_step. If origin and symptom are the same step, that is a node-level failure. If they differ, that is a strong signal of P3.

Step 2 — Decide predicted_level: is this a node failure (single-step localised error), or a process failure (multi-step structural or cumulative pattern)? Commit to level BEFORE picking cluster.

Step 3 — Pick predicted_cluster from the signatures that match your chosen level:
— If level=node: N1, N2, N3, N4, or N5.
— If level=process: P1, P2, P3, or P4.

This staging forces you to engage the node-vs-process distinction explicitly before cluster selection.

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- **P3 rule:** pick P3 when the reasoning trace makes the propagation chain EXPLICIT — later steps or agents refer back to an earlier value ("using the X from step Y", "following the method from the previous step", "based on Expert_A's earlier finding") AND the final wrong answer traces through that chain. The node-level event is the origin STEP, but the cluster label is P3 because the failure mode is propagation, not the origin event. If the origin is a hallucination that is never re-used downstream, pick N1 instead of P3.
- **P1 vs N1:** N1 is a specific fabricated factual claim in the final answer. P1 is an architecturally infeasible plan — if the plan routes a subtask to a tool that can't do it, requires information not available, or misreads the task from the start, it's P1 even if the specific wrong answer looks like a made-up fact.
- **N4 vs P1:** if the plan is otherwise sound but one specific tool call picked the wrong tool, it's N4. If the plan's decomposition architecturally routes a subtask to an inappropriate tool/agent, it's P1.
- **P4 vs N1:** P4 is an unchecked constraint on a real value (wrong year, wrong scope); N1 is a fabricated value.
- **P1 vs P2:** P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."
- **P3 confidence rule:** P3 requires multi-span reasoning by definition. Assign confidence ≤0.65 when the propagation chain is implicit — later steps use the upstream value without explicitly referencing it. Assign higher confidence only when later steps literally refer back to the earlier step's value. Include a counterfactual in reasoning: what specific change to the origin step would have produced the correct answer.

**Output contract:** Return a JSON object with EXACTLY these keys (no extras, no missing):

{
  "reasoning": "<walk through the steps you examined, what evidence you found, and which top 2-3 clusters you considered before picking. Reference step indices explicitly. For P3, identify the origin step, the propagation path, and the symptom step separately.>",
  "evidence_steps": [<1-5 integer step indices you cited>],
  "predicted_level": "<node or process — decide THIS FIRST>",
  "predicted_cluster": "<one of: N1, N2, N3, N4, N5, P1, P2, P3, P4>",
  "predicted_origin_step": <0-indexed integer>,
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false; true ONLY if failure is present but the 9 clusters don't cover it>,
  "unassignable_reason": "<if unassignable=true, explain; else empty string>"
}

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
    print(f"Phase C.1 v3 smoke | dev | n={len(cases)} | model={args.judge_model}")
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
            parsed = json.loads(resp.text)
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
        conf = p.get("confidence", "?")
        print(f"  [{i+1}/{len(cases)}] {tid[:42]:42s} gt={rec['gt_cluster']:4s}@step{rec['gt_origin_step']:2} pred={pred_c}@step{pred_s} conf={conf} ({elapsed}s)")

    with per_case_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = [r for r in records if r["error"] is None]
    cluster_correct = sum(1 for r in ok if (r["prediction"] or {}).get("predicted_cluster") == r["gt_cluster"])
    level_correct = sum(1 for r in ok if (r["prediction"] or {}).get("predicted_level") == r["gt_level"])
    n = len(records)
    print(f"\n=== v3 Smoke Summary (n={n}) ===")
    print(f"  errors: {n - len(ok)}")
    print(f"  cluster_acc: {cluster_correct}/{n}")
    print(f"  level_acc:   {level_correct}/{n}")


if __name__ == "__main__":
    main()
