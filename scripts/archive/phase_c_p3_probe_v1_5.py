"""P3-targeted prompt probe: v1 prompt with a rewritten P3 rule + one example.

Runs SYNC (not batch) on the 8 gt=P3 cases in the eval split to measure whether
the prompt change moves P3 cluster accuracy off 0/8. If it does, we run the
same prompt on the full eval to see net impact on cluster accuracy.

Changes from v1:
  - REMOVED v1's P3 rule that told the judge to "prefer N1 at origin step
    over P3 at symptom step" (actively anti-P3).
  - ADDED a "consumption" criterion: P3 when ≥2 steps act on the faulty
    value, not just when the origin step generated it.
  - ADDED one concrete P3 example.

Everything else is identical to v1.

Output: outputs/phase_c/p3_probe_v1_5/per_case.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# Reuse v1's trajectory / user prompt builders
from phase_c_all_at_once import (  # noqa: E402
    build_trajectory_block,
    build_user_prompt,
)

EVALSET = REPO_ROOT / "data" / "evalsets" / "eval.with_gt.evalset.json"
V1_PER_CASE = REPO_ROOT / "outputs" / "phase_c" / "all_at_once" / "eval" / "phase-c-eval-20260419T021854-9714af" / "per_case.jsonl"
OUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "p3_probe_v1_5"
MODEL = "gemini-3.1-pro-preview"
TEMPERATURE = 0.0

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
CLUSTER_SIGNATURES = {
    "N1": "Hallucination / factual fabrication — the final response asserts a specific factual claim (name, number, date, identifier, URL, quotation) that is not grounded in any tool output or retrieved source the agent actually obtained. The agent invented the value.",
    "N2": "Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors (wrong algorithm, off-by-one indexing, incorrect aggregation, mishandled null/NaN/empty edge cases). Visible in the code body itself.",
    "N3": "Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty/malformed result, context-limit cut-off), and the agent proceeded with degraded information or gave up. The fault is in the environment, not the agent's reasoning.",
    "N4": "Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask (e.g., generic web search when a specific API was available, OCR on text, summarizer when extraction was needed), despite an appropriate tool being available. The failure is the selection decision, not the execution.",
    "N5": "Invalid tool parameters / input — the agent called an appropriate tool with malformed, missing, or mis-scoped arguments (wrong file path, placeholder like 'example_id', schema violation, bad query string). The tool choice was right; the arguments were wrong.",
    "P1": "Improper task decomposition / bad plan — the plan itself is structurally wrong (skipped required step, wrong ordering, wrong goal, infeasible methodology) such that the task could not succeed even if every individual step executed perfectly.",
    "P2": "Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification, misread a tool output as confirming the answer when it did not). A self-monitoring/reflection failure.",
    "P3": "Cascading error (explicit propagation) — an earlier origin error was carried forward by later agents or steps without re-verification, and the final wrong answer traces explicitly to the earlier step. The late symptom has an earlier identifiable root cause.",
    "P4": "Constraint ignorance / unchecked assumption — the agent accepted a value or drew a conclusion without checking a specific constraint the task stated or implied (year, units, scope, 'as of', 'excluding X'). The plan was otherwise reasonable; one specific verification step was skipped.",
}


def build_system_prompt() -> str:
    sig_block = "\n".join(f"- **{cid}** — {sig}" for cid, sig in CLUSTER_SIGNATURES.items())
    return f"""You are a failure-attribution judge for multi-agent GAIA trajectories. Each trajectory is a pre-recorded sequence of steps (one model turn or tool call per step). The trajectory has already failed — your job is to identify WHERE the failure originated and WHICH failure mode it is.

**The 9-cluster taxonomy (node-level = single-step; process-level = multi-step/structural):**
{sig_block}

**Your task:** identify the EARLIEST step at which the failure enters the trajectory — not the step at which the wrong final answer becomes visible. For cascading failures (P3), the origin is the earlier step where the bad value was produced, not the final step where it surfaces.

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- **P3 rule (REVISED):** P3 applies when an early wrong value (tool failure, code bug, memory over-simplification, fabricated fact, etc.) is CONSUMED by later steps — another agent references it, copies its method, builds on its result, or treats it as ground truth. If two or more steps act on the faulty value, the cluster is P3 (not the origin event's node cluster), because the failure mode is propagation. If only the origin agent uses the value directly in its own final answer with no downstream consumption, pick the origin event's cluster instead.

  **Concrete P3 example:** Step 2: memory module summarizes search results as "no progress made." Step 5: planning module reads this summary and abandons the task. → Origin step = 2 (memory over-simplification). Cluster = **P3** because step 5 consumed the bad summary. If step 5 had independently redone the search instead of trusting step 2, the cluster would just be N1/N2/N3 at step 2 with no P3 label.

- P4 vs N1: P4 is an unchecked constraint on a real value (wrong year, wrong scope); N1 is a fabricated value.
- P1 vs P2: P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."

**Output contract:** Return a JSON object with EXACTLY these keys (no extras, no missing):

{{
  "reasoning": "<walk through the steps you examined, what evidence you found, and why you picked the cluster. Reference step indices explicitly. If you picked P3, name the origin step, the consuming step(s), and quote the consumption evidence.>",
  "evidence_steps": [<1-5 integer step indices you cited>],
  "predicted_origin_step": <0-indexed integer>,
  "predicted_cluster": "<one of: {", ".join(CLUSTER_IDS)}>",
  "predicted_level": "<node or process; derive: N* -> node, P* -> process>",
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false; true ONLY if the 9 clusters genuinely don't cover this failure — rare>,
  "unassignable_reason": "<if unassignable=true, explain; else empty string>"
}}

Emit reasoning FIRST (before committing to a cluster). Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.
"""


def main():
    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

    # Load v1 predictions to compare against
    v1_recs = {json.loads(l)["trajectory_id"]: json.loads(l) for l in V1_PER_CASE.open()}

    # Pick the 8 gt=P3 eval cases
    evalset = json.loads(EVALSET.read_text())
    p3_cases = [c for c in evalset["eval_cases"] if c["metadata"]["gt"]["proposed_cluster"] == "P3"]
    print(f"P3 cases to probe: {len(p3_cases)}")

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location="global",
    )
    sys_prompt = build_system_prompt()
    print(f"v1.5 system prompt length: {len(sys_prompt)} (v1 was 4735)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "per_case.jsonl"
    records = []

    cluster_correct_v1 = 0
    cluster_correct_v15 = 0
    tol3_v1 = 0
    tol3_v15 = 0

    for case in p3_cases:
        tid = case["eval_id"]
        gt = case["metadata"]["gt"]
        gt_step = int(gt["critical_failure_step"])
        t0 = time.time()
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=build_user_prompt(case),
                config=genai_types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    response_mime_type="application/json",
                    temperature=TEMPERATURE,
                ),
            )
            parsed = json.loads(resp.text)
            error = None
        except Exception as e:
            parsed = None
            error = f"{type(e).__name__}: {e}"
        elapsed = round(time.time() - t0, 1)

        v1_pred = (v1_recs.get(tid, {}).get("prediction") or {})
        v1_c = v1_pred.get("predicted_cluster")
        v1_s = v1_pred.get("predicted_origin_step")
        v15_c = (parsed or {}).get("predicted_cluster")
        v15_s = (parsed or {}).get("predicted_origin_step")

        if v1_c == "P3":
            cluster_correct_v1 += 1
        if v15_c == "P3":
            cluster_correct_v15 += 1
        if v1_s is not None and abs(int(v1_s) - gt_step) <= 3:
            tol3_v1 += 1
        if v15_s is not None and abs(int(v15_s) - gt_step) <= 3:
            tol3_v15 += 1

        print(f"{tid[:50]:50s}")
        print(f"  gt=P3@{gt_step}  v1: {v1_c}@{v1_s}  v1.5: {v15_c}@{v15_s}  ({elapsed}s)")
        records.append({
            "trajectory_id": tid,
            "gt_step": gt_step,
            "v1_cluster": v1_c,
            "v1_step": v1_s,
            "v15_cluster": v15_c,
            "v15_step": v15_s,
            "v15_reasoning": (parsed or {}).get("reasoning", "")[:400],
            "elapsed_s": elapsed,
            "error": error,
        })

    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(p3_cases)
    print(f"\n=== P3 Probe Summary (n={n}) ===")
    print(f"  Cluster correct (P3):  v1={cluster_correct_v1}/{n}  v1.5={cluster_correct_v15}/{n}")
    print(f"  Tol-3 (origin step):   v1={tol3_v1}/{n}  v1.5={tol3_v15}/{n}")
    print(f"  Output: {out_path}")


if __name__ == "__main__":
    main()
