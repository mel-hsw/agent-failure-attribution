"""Phase C.1 v3 — AllAtOnceAttribution with refined prompt, via Vertex batch.

v3 prompt changes vs v1:
  - Explicit statement that eval set is confirmed-failure-only (no_failure
    not offered).
  - Two-pass origin attribution procedure (forward: flag symptoms; backward:
    trace upstream to origin).
  - Staged decision: level FIRST, then cluster.
  - P3 rule rewritten: pick P3 when propagation chain is EXPLICIT; cluster
    label is P3 even if origin step's event is node-level.
  - Added P1-vs-N1, N4-vs-P1, P4-vs-N1, P1-vs-P2 disambiguation rules.
  - P3 confidence rule: ≤0.65 when propagation is implicit.
  - Counterfactual requirement in P3 reasoning.

Output: outputs/phase_c/all_at_once_v3/<split>/<run_id>/
GCS prefix: phase_c/all_at_once_v3/ (separate from v1's phase_c/all_at_once/)

Usage:
    python3 scripts/phase_c_all_at_once_v3.py --split dev
    python3 scripts/phase_c_all_at_once_v3.py --split eval
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "all_at_once_v3"

DEFAULT_BUCKET = "agenttracebucket"
DEFAULT_GCS_PREFIX = "phase_c/all_at_once_v3"

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
LEVELS = ["node", "process"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_IDS}

CLUSTER_SIGNATURES = {
    "N1": "Hallucination / factual fabrication — the final response asserts a specific factual claim (name, number, date, identifier, URL, quotation) that is not grounded in any tool output or retrieved source the agent actually obtained. The agent invented the value.",
    "N2": "Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors (wrong algorithm, off-by-one indexing, incorrect aggregation, mishandled null/NaN/empty edge cases). Visible in the code body itself.",
    "N3": "Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty/malformed result, context-limit cut-off), and the agent proceeded with degraded information or gave up. The fault is in the environment, not the agent's reasoning.",
    "N4": "Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask (e.g., generic web search when a specific API was available, OCR on text, summarizer when extraction was needed), despite an appropriate tool being available. The failure is the selection decision, not the execution.",
    "N5": "Invalid tool parameters / input — the agent called an appropriate tool with malformed, missing, or mis-scoped arguments (wrong file path, placeholder like 'example_id', schema violation, bad query string). The tool choice was right; the arguments were wrong.",
    "P1": "Improper task decomposition / bad plan — the plan itself is structurally wrong (skipped required step, wrong ordering, wrong goal, infeasible methodology) such that the task could not succeed even if every individual step executed perfectly.",
    "P2": "Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification, misread a tool output as confirming the answer when it did not). A self-monitoring/reflection failure.",
    "P3": "Cascading error (explicit propagation) — an earlier origin error (often N1/N2/N3) was carried forward by later agents or steps without re-verification, and the final wrong answer traces explicitly to the earlier step. The late symptom has an earlier identifiable root cause.",
    "P4": "Constraint ignorance / unchecked assumption — the agent accepted a value or drew a conclusion without checking a specific constraint the task stated or implied (year, units, scope, 'as of', 'excluding X'). The plan was otherwise reasonable; one specific verification step was skipped.",
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reasoning": {"type": "STRING"},
        "evidence_steps": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "predicted_origin_step": {"type": "INTEGER"},
        "predicted_cluster": {"type": "STRING", "enum": CLUSTER_IDS},
        "predicted_level": {"type": "STRING", "enum": LEVELS},
        "confidence": {"type": "NUMBER"},
        "unassignable": {"type": "BOOLEAN"},
        "unassignable_reason": {"type": "STRING"},
    },
    "required": [
        "reasoning",
        "evidence_steps",
        "predicted_origin_step",
        "predicted_cluster",
        "predicted_level",
        "confidence",
        "unassignable",
        "unassignable_reason",
    ],
}


def build_system_prompt() -> str:
    sig_block = "\n".join(f"- **{cid}** — {sig}" for cid, sig in CLUSTER_SIGNATURES.items())
    return f"""You are a failure-attribution judge for multi-agent GAIA trajectories. Each trajectory is a pre-recorded sequence of steps (one model turn or tool call per step). Your job is to identify WHERE the failure originated and WHICH failure mode it is.

All trajectories in this evaluation set are confirmed failures. no_failure is not a valid output. If you cannot identify a specific cluster, set unassignable: true instead.

**The 9-option taxonomy (node-level = single-step; process-level = multi-step/structural):**
{sig_block}

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

{{
  "reasoning": "<walk through the steps you examined, what evidence you found, and which top 2-3 clusters you considered before picking. Reference step indices explicitly. For P3, identify the origin step, the propagation path, and the symptom step separately.>",
  "evidence_steps": [<1-5 integer step indices you cited>],
  "predicted_level": "<node or process — decide THIS FIRST>",
  "predicted_cluster": "<one of: {", ".join(CLUSTER_IDS)}>",
  "predicted_origin_step": <0-indexed integer>,
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false; true ONLY if failure is present but the 9 clusters don't cover it>,
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
        f"**User task (as given to the agent system):**\n{task}\n\n"
        f"**Trajectory steps:**\n{trajectory}\n\n"
        "Return your JSON attribution now.\n"
    )


def build_request(system_prompt: str, user_prompt: str, temperature: float = 0.0) -> dict:
    """Vertex batch Gemini request shape.

    Vertex batch's proto parser rejects `responseSchema` with nested enum
    (2026-04-19; gemini-3.1-pro-preview in global). Workaround: use
    `responseMimeType: application/json` only and enforce schema shape via
    prompt discipline. See phase_b_batch.py for the same rationale.
    """
    return {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }


def _slugify_model(model: str) -> str:
    """`gemini-3.1-pro-preview` -> `gemini-3-1-pro-preview` (filesystem-safe)."""
    return model.replace(".", "-").replace("/", "-")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "calibration", "eval"), default="dev")
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="Sampling temperature (0.0 default; try 0.3 for self-consistency-ish runs)")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default=DEFAULT_GCS_PREFIX,
                        help="GCS path prefix. Default writes all runs under the same prefix; "
                             "pass a model-specific prefix to separate outputs by judge model.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    project = os.environ["GOOGLE_CLOUD_PROJECT"]

    # Load cases
    evalset_path = EVALSET_DIR / f"{args.split}.with_gt.evalset.json"
    if not evalset_path.exists():
        print(f"ERROR: {evalset_path} not found", file=sys.stderr)
        return 1
    evalset = json.loads(evalset_path.read_text())
    cases = evalset["eval_cases"]
    if args.limit:
        cases = cases[: args.limit]
    print(f"Phase C AllAtOnce | split={args.split} | n={len(cases)} | model={args.judge_model}")

    # Build requests (row index will match case index).
    import batch_utils as bu

    sys_prompt = build_system_prompt()
    requests = [
        bu.BatchRequest(
            key=c["eval_id"],
            request_body=build_request(sys_prompt, build_user_prompt(c), temperature=args.temperature),
        )
        for c in cases
    ]

    # Include model slug + temperature in the run_id so multiple judge/temp
    # combos don't overwrite each other; also segregate the output dir by
    # model slug so at-a-glance browsing stays sane.
    model_slug = _slugify_model(args.judge_model)
    run_id = bu.new_run_id(f"phase-c-{args.split}-{model_slug}-t{args.temperature:.2f}")
    out_dir = OUTPUT_DIR / model_slug / args.split / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    local_input = out_dir / "input.jsonl"
    local_output = out_dir / "predictions.jsonl"
    bu.write_jsonl(requests, local_input)
    print(f"Wrote {len(requests)} requests to {local_input}")

    gcs_input = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/input.jsonl"
    gcs_output_prefix = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/output"
    bu.upload_to_gcs(local_input, gcs_input, project=project)
    print(f"Uploaded -> {gcs_input}")

    # Submit + poll
    from google import genai

    client = genai.Client(vertexai=True, project=project, location="global")

    def on_state(state, elapsed):
        print(f"  [{elapsed}s] {state}")

    job = bu.submit_and_wait(
        client=client,
        model=args.judge_model,
        src_uri=gcs_input,
        dest_uri=gcs_output_prefix,
        poll_interval_s=20,
        on_state_change=on_state,
    )
    final_state = str(job.state)
    print(f"Job final state: {final_state}")
    if not final_state.endswith("SUCCEEDED"):
        print(f"Job error: {getattr(job, 'error', None)}", file=sys.stderr)
        return 2

    # Download + parse
    downloaded = bu.download_output_jsonl(gcs_output_prefix, local_output, project=project)
    if not downloaded:
        print(f"ERROR: no predictions.jsonl under {gcs_output_prefix}", file=sys.stderr)
        return 3
    print(f"Downloaded predictions -> {local_output}")

    # Vertex batch does NOT preserve input row order — align by trajectory_id
    # embedded in each prompt.
    per_case_path = out_dir / "per_case.jsonl"
    records = []
    by_key = bu.parse_output_by_key(local_output, bu.make_trajectory_id_extractor())
    if len(by_key) != len(cases):
        print(f"WARN: got {len(by_key)} output rows but submitted {len(cases)} requests", file=sys.stderr)

    with per_case_path.open("w") as f:
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
                rec = {**base, "prediction": None, "error": "no output row"}
            else:
                response, err = match
                if err:
                    rec = {**base, "prediction": None, "error": err}
                else:
                    text = bu.extract_text(response)
                    if not text:
                        rec = {**base, "prediction": None, "error": "no text in response"}
                    else:
                        try:
                            parsed = json.loads(text)
                            parsed["predicted_level"] = CLUSTER_LEVEL.get(
                                parsed.get("predicted_cluster"), parsed.get("predicted_level")
                            )
                            rec = {**base, "prediction": parsed, "error": None}
                        except json.JSONDecodeError as e:
                            rec = {**base, "prediction": None, "error": f"JSONDecodeError: {e}", "raw_text": text[:500]}
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary
    errors = [r for r in records if r.get("error")]
    successful = [r for r in records if r.get("prediction")]

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
        "split": args.split,
        "judge_model": args.judge_model,
        "temperature": args.temperature,
        "run_id": run_id,
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
        "gcs_input": gcs_input,
        "gcs_output_prefix": gcs_output_prefix,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Phase C AllAtOnce Summary ({args.split}) ===")
    print(f"  Cases: {summary['n_cases']}  Errors: {summary['errors']}")
    print(f"  Cluster accuracy: {summary['cluster_accuracy']}")
    print(f"  Level accuracy:   {summary['level_accuracy']}")
    print(f"  Origin-step tol-3: {summary['origin_step_tol3']}")
    print(f"  Origin-step tol-0: {summary['origin_step_tol0']}")
    print(f"  Outputs: {out_dir}/")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
