"""Phase C.1 — AllAtOnceAttribution via Vertex batch prediction.

One structured-JSON judgment per trajectory. All requests submitted as a
single Vertex batch job against `gemini-3.1-pro-preview` in the `global`
location (the preview model is not served from regional endpoints).

Output schema (per `response_schema`):
    {
      reasoning, evidence_steps, predicted_origin_step,
      predicted_cluster, predicted_level, confidence,
      unassignable, unassignable_reason
    }

Flow:
    1. Build one batch request per eval case (system prompt + trajectory block).
    2. Upload JSONL to gs://<bucket>/phase_c/all_at_once/<run_id>/input.jsonl.
    3. Submit batch job; poll until SUCCEEDED.
    4. Download predictions.jsonl; align rows to cases by input order.
    5. Write per_case.jsonl + summary.json in the same shape Phase B uses.

Usage:
    python3 scripts/phase_c_all_at_once.py --split dev --limit 5
    python3 scripts/phase_c_all_at_once.py --split eval
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
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "all_at_once"

DEFAULT_BUCKET = "agenttracebucket"
DEFAULT_GCS_PREFIX = "phase_c/all_at_once"

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
    return f"""You are a failure-attribution judge for multi-agent GAIA trajectories. Each trajectory is a pre-recorded sequence of steps (one model turn or tool call per step). The trajectory has already failed — your job is to identify WHERE the failure originated and WHICH failure mode it is.

**The 9-cluster taxonomy (node-level = single-step; process-level = multi-step/structural):**
{sig_block}

**Your task:** identify the EARLIEST step at which the failure enters the trajectory — not the step at which the wrong final answer becomes visible. For cascading failures (P3), the origin is the earlier step where the bad value was produced, not the final step where it surfaces.

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- P3 requires a specific earlier wrong value that propagates — not just "late symptom." If the origin is a hallucination that is then echoed downstream, prefer N1 at the origin step over P3 at the symptom step (the dataset labels the origin cluster, not the propagation).
- P4 vs N1: P4 is an unchecked constraint on a real value (wrong year, wrong scope); N1 is a fabricated value.
- P1 vs P2: P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."

**Output contract:** Return a JSON object with EXACTLY these keys (no extras, no missing):

{{
  "reasoning": "<walk through the steps you examined, what evidence you found, and why you picked the cluster. Reference step indices explicitly.>",
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


def build_request(system_prompt: str, user_prompt: str) -> dict:
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
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "calibration", "eval"), default="dev")
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default=DEFAULT_GCS_PREFIX)
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
            request_body=build_request(sys_prompt, build_user_prompt(c)),
        )
        for c in cases
    ]

    run_id = bu.new_run_id(f"phase-c-{args.split}")
    out_dir = OUTPUT_DIR / args.split / run_id
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
