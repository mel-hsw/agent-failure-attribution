"""Phase C.3 — ConstraintGroundedAttribution via two-pass Vertex batch.

Implements the AgentRx-style evidence-grounded judgment loop:

    Pass 0 (Python, no LLM) — run TrajectoryReplayer's Tier-1 static
        constraints (S4, S5-heuristic, S6-heuristic, S8, S9) and collect the
        static violation events.

    Pass 1 (Vertex batch, one request per trajectory) — LLM synthesizes the
        task-specific dynamic constraints D1-D9 from the GAIA task prompt
        AND evaluates them against the trajectory in a single structured-JSON
        response. Combining synthesis and evaluation into one call halves
        LLM cost versus the plan's two-call design without losing the
        per-task adaptation (the prompt forces the judge to first enumerate
        applicable constraints before scoring, which is functionally
        equivalent to synthesize-then-evaluate).

    Pass 2 (Vertex batch, one request per trajectory) — given task +
        trajectory + merged violation log (static + dynamic) + taxonomy,
        emit the final attribution JSON (same schema as AllAtOnce). The
        violation log is presented as "evidence" the judge can cite or
        override; the judge is explicitly told the log is heuristic.

Output artifacts under `outputs/phase_c/constraint_grounded/<split>/<run_id>/`:
    input_constraints.jsonl, predictions_constraints.jsonl,
    violation_logs.jsonl,    input_attribution.jsonl,
    predictions_attribution.jsonl, per_case.jsonl, summary.json

Ablation: pass `--no-violation-log` to run only Pass 2 without the evidence
log. Matches the §9 ablation in step4_plan.md.

Usage:
    python3 scripts/phase_c_constraint_grounded.py --split dev --limit 3
    python3 scripts/phase_c_constraint_grounded.py --split eval
    python3 scripts/phase_c_constraint_grounded.py --split eval --no-violation-log
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_c" / "constraint_grounded"

DEFAULT_BUCKET = "agenttracebucket"
DEFAULT_GCS_PREFIX = "phase_c/constraint_grounded"

CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_IDS}

CLUSTER_SIGNATURES = {
    "N1": "Hallucination / factual fabrication — the final response asserts a specific factual claim that is not grounded in any tool output the agent actually obtained.",
    "N2": "Code implementation bug — an agent-written code block executed without crashing but produced a wrong result due to logic errors.",
    "N3": "Tool execution or retrieval failure — a tool call was structurally correct but the environment failed (4xx/5xx, timeout, empty result), and the agent proceeded with degraded information.",
    "N4": "Wrong tool selection — the agent selected a tool whose purpose is mismatched to the subtask despite an appropriate tool being available.",
    "N5": "Invalid tool parameters / input — the agent called an appropriate tool with malformed or mis-scoped arguments.",
    "P1": "Improper task decomposition / bad plan — the plan itself is structurally wrong such that the task could not succeed even if every step executed perfectly.",
    "P2": "Progress misassessment — the agent misjudged its own state (declared the task complete while missing information, terminated before verification).",
    "P3": "Cascading error — an earlier origin error was carried forward without re-verification.",
    "P4": "Constraint ignorance / unchecked assumption — the agent drew a conclusion without checking a specific constraint the task stated or implied.",
}

DYNAMIC_CONSTRAINTS = {
    "D1": "Final-answer format matches the task-specified format (int / list / string / yes-no).",
    "D2": "If the task references a time frame, the trajectory contains verification of temporal validity.",
    "D3": "If the task references a specific source (Wikipedia, a URL, a named database), the trajectory accesses it.",
    "D4": "All sub-questions in multi-part tasks are addressed.",
    "D5": "Task-referenced files or URLs are accessed and return non-empty content.",
    "D6": "Task-forbidden actions do not occur.",
    "D7": "Final reasoning claims are backed by prior tool outputs (hallucination check).",
    "D8": "Numerical computations have an explicit verification step.",
    "D9": "The plan enumerated at run start is followed or explicitly revised.",
}

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


def build_trajectory_block(eval_case: dict) -> str:
    history = eval_case["metadata"]["trajectory"]
    lines = []
    for i, msg in enumerate(history):
        author = msg.get("name") or msg.get("role") or "agent"
        content = _truncate(_content_str(msg))
        lines.append(f"### Step {i} — author={author}\n{content}")
    return "\n\n".join(lines)


def _extract_task(eval_case: dict) -> str:
    conv = eval_case.get("conversation", [])
    if conv:
        parts = conv[0].get("user_content", {}).get("parts", [])
        if parts and parts[0].get("text"):
            return parts[0]["text"]
    history = eval_case["metadata"]["trajectory"]
    return _content_str(history[0]) if history else ""


# ---------------------------------------------------------------------------
# Pass 1 — dynamic constraint synthesis + evaluation


DYNAMIC_SYSTEM = """You are a constraint checker for a pre-recorded GAIA multi-agent trajectory. Your job is to (1) decide which of the 9 dynamic constraints below apply to THIS task, (2) evaluate each applicable constraint against the trajectory, and (3) emit a structured list of constraint events.

**Dynamic constraint catalogue:**
{dynamic_catalogue}

**Verdict values:**
- "CLEAR_PASS" — the constraint is applicable AND satisfied.
- "CLEAR_FAIL" — the constraint is applicable AND violated.
- "UNCLEAR" — you cannot tell from the trajectory.
- "NOT_APPLICABLE" — the task does not invoke this constraint (e.g. D2 for a task with no time frame).

For each constraint, also emit the step index at which the verdict was decided (0 if the verdict is about the final answer, or the earliest step that demonstrates the violation for CLEAR_FAIL).

Output contract: a JSON object with EXACTLY this shape (no extras, no missing):

{{
  "constraint_events": [
    {{
      "constraint_id": "<D1..D9>",
      "applicable": <true or false>,
      "verdict": "<CLEAR_PASS | CLEAR_FAIL | UNCLEAR | NOT_APPLICABLE>",
      "step": <integer step index or null>,
      "evidence": "<1-3 sentence justification citing step indices>"
    }},
    ...
  ]
}}

Emit one entry per dynamic constraint D1..D9, in that order. Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.
"""


def dynamic_system_prompt() -> str:
    block = "\n".join(f"- **{cid}** — {desc}" for cid, desc in DYNAMIC_CONSTRAINTS.items())
    return DYNAMIC_SYSTEM.format(dynamic_catalogue=block)


def build_dynamic_user_prompt(eval_case: dict) -> str:
    tid = eval_case["eval_id"]
    task = _extract_task(eval_case)
    traj = build_trajectory_block(eval_case)
    return (
        f"**Trajectory id:** {tid}\n\n"
        f"**User task:**\n{task}\n\n"
        f"**Trajectory steps:**\n{traj}\n\n"
        "Evaluate D1..D9 and return the JSON object now.\n"
    )


def build_dynamic_request(system_prompt: str, user_prompt: str) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }


# ---------------------------------------------------------------------------
# Pass 2 — final attribution grounded in the merged violation log


ATTRIBUTION_SYSTEM = """You are a failure-attribution judge for a pre-recorded GAIA multi-agent trajectory. The trajectory has already failed. Identify the EARLIEST step at which the failure enters the trajectory and classify it against the 9-cluster taxonomy.

**The 9-cluster taxonomy (node-level = single-step; process-level = multi-step/structural):**
{clusters}

**Evidence provided:** You are given a VIOLATION LOG that lists constraint events flagged by a heuristic checker. The log is indicative, not authoritative — you must decide whether each entry reflects the true failure origin or is a downstream symptom. Cite log rows you agree with; override them when the trajectory contradicts them.

**Disambiguation tips:**
- If the agent has no tools, N3/N4/N5 cannot apply.
- If the agent wrote no code, N2 cannot apply.
- P3 requires a specific earlier wrong value that propagates — prefer the origin cluster at the origin step over P3 at the symptom step.
- P4 vs N1: P4 is an unchecked constraint on a real retrieved value; N1 is a fabricated value.
- P1 vs P2: P1 is "the plan was wrong from the start"; P2 is "the plan was fine but the agent misjudged where it stood."

**Output contract:** Return a JSON object with EXACTLY these keys (no extras, no missing):

{{
  "reasoning": "<walk through the evidence — cite both log rows and step indices in the trajectory>",
  "cited_log_rows": [<integer row indices into the violation log you relied on; empty list if none>],
  "evidence_steps": [<1-5 integer step indices>],
  "predicted_origin_step": <0-indexed integer>,
  "predicted_cluster": "<one of: N1 N2 N3 N4 N5 P1 P2 P3 P4>",
  "predicted_level": "<node or process; N* -> node, P* -> process>",
  "confidence": <float 0.0-1.0>,
  "unassignable": <true or false>,
  "unassignable_reason": "<if unassignable=true, explain; else empty string>"
}}

Emit reasoning FIRST. Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.
"""


def attribution_system_prompt() -> str:
    block = "\n".join(f"- **{cid}** — {sig}" for cid, sig in CLUSTER_SIGNATURES.items())
    return ATTRIBUTION_SYSTEM.format(clusters=block)


def build_attribution_user_prompt(eval_case: dict, violation_log_md: str | None) -> str:
    tid = eval_case["eval_id"]
    task = _extract_task(eval_case)
    traj = build_trajectory_block(eval_case)
    log_section = (
        f"**Violation log (indexed):**\n{violation_log_md}\n\n"
        if violation_log_md is not None
        else "**Violation log:** _ablation mode — no log provided._\n\n"
    )
    return (
        f"**Trajectory id:** {tid}\n\n"
        f"**User task:**\n{task}\n\n"
        f"{log_section}"
        f"**Trajectory steps:**\n{traj}\n\n"
        "Return your JSON attribution now.\n"
    )


def build_attribution_request(system_prompt: str, user_prompt: str) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }


# ---------------------------------------------------------------------------
# Violation log merging


def render_merged_log(static_events: list[dict], dynamic_events: list[dict]) -> str:
    """Deterministic Markdown table so the judge can cite rows by index."""
    rows: list[dict] = []
    for e in static_events:
        rows.append(
            {
                "source": "static",
                "step": e.get("step"),
                "constraint_id": e.get("constraint_id"),
                "verdict": e.get("verdict"),
                "evidence": e.get("evidence", ""),
            }
        )
    # Only surface dynamic events where the verdict is informative.
    for e in dynamic_events:
        if e.get("verdict") in ("CLEAR_FAIL", "UNCLEAR"):
            rows.append(
                {
                    "source": "dynamic",
                    "step": e.get("step"),
                    "constraint_id": e.get("constraint_id"),
                    "verdict": e.get("verdict"),
                    "evidence": e.get("evidence", ""),
                }
            )
    if not rows:
        return "_No constraint violations flagged._"
    lines = [
        "| row | source | step | constraint | verdict | evidence |",
        "|---|---|---|---|---|---|",
    ]
    for idx, r in enumerate(rows):
        ev = (r["evidence"] or "").replace("|", "\\|").replace("\n", " ")
        if len(ev) > 240:
            ev = ev[:240] + "..."
        lines.append(
            f"| {idx} | {r['source']} | {r['step']} | {r['constraint_id']} | {r['verdict']} | {ev} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Driver


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "calibration", "eval"), default="dev")
    parser.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default=DEFAULT_GCS_PREFIX)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--no-violation-log",
        action="store_true",
        help="Ablation: run Pass 2 only, without the violation log (no Pass 0 or Pass 1).",
    )
    parser.add_argument(
        "--step-budget",
        type=int,
        default=30,
        help="S9 per-author step budget threshold.",
    )
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    project = os.environ["GOOGLE_CLOUD_PROJECT"]

    evalset_path = EVALSET_DIR / f"{args.split}.with_gt.evalset.json"
    if not evalset_path.exists():
        print(f"ERROR: {evalset_path} not found", file=sys.stderr)
        return 1
    evalset = json.loads(evalset_path.read_text())
    cases = evalset["eval_cases"]
    if args.limit:
        cases = cases[: args.limit]

    import batch_utils as bu
    import trajectory_replayer as tr
    from google import genai

    client = genai.Client(vertexai=True, project=project, location="global")
    run_id = bu.new_run_id(f"phase-c-cg-{args.split}")
    out_dir = OUTPUT_DIR / args.split / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"Phase C ConstraintGrounded | split={args.split} | n={len(cases)} | "
        f"model={args.judge_model} | ablation={args.no_violation_log}"
    )
    print(f"Run dir: {out_dir}")

    def on_state(state, elapsed):
        print(f"  [{elapsed}s] {state}")

    # -----------------------------------------------------------------
    # Pass 0 — static constraints (always run; skipped in ablation)
    static_logs_by_id: dict[str, list[dict]] = {}
    if not args.no_violation_log:
        print("\n[Pass 0] Running TrajectoryReplayer (static constraints)...")
        for case in cases:
            history = case["metadata"]["trajectory"]
            events = tr.replay(history, step_budget=args.step_budget)
            static_logs_by_id[case["eval_id"]] = [e.to_dict() for e in events]
        n_flagged = sum(1 for v in static_logs_by_id.values() if v)
        print(f"  Static events across corpus: {sum(len(v) for v in static_logs_by_id.values())} "
              f"({n_flagged}/{len(cases)} trajectories flagged)")

    # -----------------------------------------------------------------
    # Pass 1 — dynamic constraints (Vertex batch; skipped in ablation)
    dynamic_logs_by_id: dict[str, list[dict]] = {cid["eval_id"]: [] for cid in cases}
    if not args.no_violation_log:
        print("\n[Pass 1] Submitting dynamic-constraint batch...")
        dyn_sys = dynamic_system_prompt()
        dyn_requests = [
            bu.BatchRequest(
                key=c["eval_id"],
                request_body=build_dynamic_request(dyn_sys, build_dynamic_user_prompt(c)),
            )
            for c in cases
        ]
        dyn_input = out_dir / "input_constraints.jsonl"
        dyn_output = out_dir / "predictions_constraints.jsonl"
        bu.write_jsonl(dyn_requests, dyn_input)
        gcs_dyn_input = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/constraints_input.jsonl"
        gcs_dyn_output = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/constraints_output"
        bu.upload_to_gcs(dyn_input, gcs_dyn_input, project=project)
        print(f"  Uploaded constraint batch input -> {gcs_dyn_input}")
        job = bu.submit_and_wait(
            client=client,
            model=args.judge_model,
            src_uri=gcs_dyn_input,
            dest_uri=gcs_dyn_output,
            poll_interval_s=20,
            on_state_change=on_state,
        )
        if not str(job.state).endswith("SUCCEEDED"):
            print(f"  Pass 1 job failed: {getattr(job, 'error', None)}", file=sys.stderr)
            return 2
        downloaded = bu.download_output_jsonl(gcs_dyn_output, dyn_output, project=project)
        if not downloaded:
            print(f"  ERROR: no predictions under {gcs_dyn_output}", file=sys.stderr)
            return 3
        print(f"  Downloaded constraint predictions -> {dyn_output}")

        # Vertex batch does NOT preserve input row order — align by trajectory_id
        # embedded in each prompt (see batch_utils.make_trajectory_id_extractor).
        by_key = bu.parse_output_by_key(dyn_output, bu.make_trajectory_id_extractor())
        for case in cases:
            resp, err = by_key.get(case["eval_id"], (None, "no output row"))
            if err or resp is None:
                continue
            text = bu.extract_text(resp)
            if not text:
                continue
            try:
                parsed = json.loads(text)
                events = parsed.get("constraint_events") or []
                dynamic_logs_by_id[case["eval_id"]] = events
            except json.JSONDecodeError:
                # Leave empty; the attribution pass still sees static events.
                continue
        with (out_dir / "violation_logs.jsonl").open("w") as f:
            for c in cases:
                cid = c["eval_id"]
                f.write(
                    json.dumps(
                        {
                            "trajectory_id": cid,
                            "static_events": static_logs_by_id.get(cid, []),
                            "dynamic_events": dynamic_logs_by_id.get(cid, []),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    # -----------------------------------------------------------------
    # Pass 2 — final attribution (Vertex batch; always run)
    print("\n[Pass 2] Submitting attribution batch...")
    attr_sys = attribution_system_prompt()
    attr_requests = []
    for c in cases:
        if args.no_violation_log:
            log_md: str | None = None
        else:
            log_md = render_merged_log(
                static_logs_by_id.get(c["eval_id"], []),
                dynamic_logs_by_id.get(c["eval_id"], []),
            )
        attr_requests.append(
            bu.BatchRequest(
                key=c["eval_id"],
                request_body=build_attribution_request(
                    attr_sys, build_attribution_user_prompt(c, log_md)
                ),
            )
        )

    attr_input = out_dir / "input_attribution.jsonl"
    attr_output = out_dir / "predictions_attribution.jsonl"
    bu.write_jsonl(attr_requests, attr_input)
    gcs_attr_input = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/attribution_input.jsonl"
    gcs_attr_output = f"gs://{args.bucket}/{args.gcs_prefix}/{run_id}/attribution_output"
    bu.upload_to_gcs(attr_input, gcs_attr_input, project=project)
    print(f"  Uploaded attribution batch input -> {gcs_attr_input}")
    job = bu.submit_and_wait(
        client=client,
        model=args.judge_model,
        src_uri=gcs_attr_input,
        dest_uri=gcs_attr_output,
        poll_interval_s=20,
        on_state_change=on_state,
    )
    if not str(job.state).endswith("SUCCEEDED"):
        print(f"  Pass 2 job failed: {getattr(job, 'error', None)}", file=sys.stderr)
        return 2
    downloaded = bu.download_output_jsonl(gcs_attr_output, attr_output, project=project)
    if not downloaded:
        print(f"  ERROR: no predictions under {gcs_attr_output}", file=sys.stderr)
        return 3
    print(f"  Downloaded attribution predictions -> {attr_output}")

    # -----------------------------------------------------------------
    # Parse Pass 2, write per_case + summary
    # Vertex batch does NOT preserve input row order — align by trajectory_id.
    per_case_path = out_dir / "per_case.jsonl"
    records: list[dict] = []
    by_key = bu.parse_output_by_key(attr_output, bu.make_trajectory_id_extractor())
    with per_case_path.open("w") as f:
        for case in cases:
            cid = case["eval_id"]
            gt = case["metadata"].get("gt", {})
            base = {
                "trajectory_id": cid,
                "gt_cluster": gt.get("proposed_cluster"),
                "gt_level": gt.get("proposed_level"),
                "gt_origin_step": gt.get("critical_failure_step"),
                "static_events": static_logs_by_id.get(cid, []),
                "dynamic_events": dynamic_logs_by_id.get(cid, []),
            }
            resp, err = by_key.get(cid, (None, "no output row"))
            if err or resp is None:
                rec = {**base, "prediction": None, "error": err or "no response"}
            else:
                text = bu.extract_text(resp)
                if not text:
                    rec = {**base, "prediction": None, "error": "no text in response"}
                else:
                    try:
                        parsed = json.loads(text)
                        pc = parsed.get("predicted_cluster")
                        if pc in CLUSTER_LEVEL:
                            parsed["predicted_level"] = CLUSTER_LEVEL[pc]
                        rec = {**base, "prediction": parsed, "error": None}
                    except json.JSONDecodeError as e:
                        rec = {
                            **base,
                            "prediction": None,
                            "error": f"JSONDecodeError: {e}",
                            "raw_text": text[:500],
                        }
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Metrics
    errors = [r for r in records if r.get("error")]
    successful = [r for r in records if r.get("prediction")]

    def cluster_match(r):
        return (r.get("prediction") or {}).get("predicted_cluster") == r["gt_cluster"]

    def level_match(r):
        return (r.get("prediction") or {}).get("predicted_level") == r["gt_level"]

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

    confusion: defaultdict = defaultdict(Counter)
    for r in records:
        pred = (r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED"
        confusion[r["gt_cluster"]][pred] += 1

    # Log-usage metric: did the judge cite any violation-log row?
    if args.no_violation_log:
        log_citation_rate = None
    else:
        cited = sum(
            1
            for r in successful
            if ((r.get("prediction") or {}).get("cited_log_rows") or [])
        )
        log_citation_rate = round(cited / max(1, len(successful)), 3)

    summary = {
        "split": args.split,
        "judge_model": args.judge_model,
        "run_id": run_id,
        "ablation_no_violation_log": args.no_violation_log,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "origin_step_tol0": round(step_t0 / max(1, len(records)), 3),
        "origin_step_tol3": round(step_t3 / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "log_citation_rate": log_citation_rate,
        "static_event_count": sum(len(v) for v in static_logs_by_id.values()),
        "dynamic_event_count": sum(len(v) for v in dynamic_logs_by_id.values()),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(((r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED") for r in records)
        ),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Phase C ConstraintGrounded Summary ({args.split}) ===")
    print(f"  Cases: {summary['n_cases']}  Errors: {summary['errors']}")
    print(f"  Cluster accuracy: {summary['cluster_accuracy']}")
    print(f"  Level accuracy:   {summary['level_accuracy']}")
    print(f"  Origin-step tol-3/tol-0: {summary['origin_step_tol3']} / {summary['origin_step_tol0']}")
    print(f"  Unassignable:     {summary['unassignable_rate']}")
    if log_citation_rate is not None:
        print(f"  Log citation rate: {log_citation_rate}")
    print(f"  Outputs: {out_dir}/")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
