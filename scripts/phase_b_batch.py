"""Phase B — off-the-shelf rubric-based baseline via Vertex batch.

Honors the spirit of ADK's `rubric_based_final_response_quality_v1`: the
judge evaluates 9 yes/no rubrics (one per cluster) against a trajectory,
and the predicted cluster is derived from the verdict pattern. Differences
from `phase_b_rubric_baseline.py`:

- Does NOT use ADK's rubric framework at all. The rubric prompt is emitted
  by us directly, so we can use Vertex batch (ADK's evaluator goes through
  its own LLM client wiring and doesn't expose a batch hook).
- Uses the **positive-correctness polarity** established in the 2026-04-19
  polarity-fix decision (see PROJECT.md): `Verdict: yes` = this failure did
  NOT occur, `Verdict: no` = this failure DID occur. Prediction = argmin.
- Uses structured JSON output instead of Property/Evidence/Rationale/Verdict
  prose, because once we control the prompt we might as well get a clean
  result shape. The "off-the-shelf baseline" framing still holds — the judge
  is still yes/no per rubric, with no step/confidence/origin emitted, so the
  gap to Phase C is still the same "what attribution looks like when the
  evaluator can directly emit structured attribution" comparison.

Usage:
    python3 scripts/phase_b_batch.py --split dev --limit 5
    python3 scripts/phase_b_batch.py --split eval
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
RUBRIC_FILE = REPO_ROOT / "data" / "rubrics" / "option_b_rubric.json"
OUTPUT_DIR = REPO_ROOT / "outputs" / "phase_b_batch"

DEFAULT_BUCKET = "agenttracebucket"
DEFAULT_GCS_PREFIX = "phase_b/batch"

# Same priority order as phase_b_rubric_baseline.py (see PROJECT.md 2026-04-19).
CLUSTER_PRIORITY = ["N5", "N4", "N3", "N2", "N1", "P4", "P3", "P2", "P1"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_PRIORITY}


def load_rubrics() -> list[dict]:
    data = json.loads(RUBRIC_FILE.read_text())
    return data["rubrics"]


def build_response_schema(rubric_ids: list[str]) -> dict:
    """One verdict + rationale per rubric. Vertex batch requires OpenAPI 3.0
    schema with UPPERCASE type tokens (STRING not string), so we emit in that
    form — this matches what `google.genai.types.Schema.model_dump()` produces."""
    return {
        "type": "OBJECT",
        "properties": {
            rid: {
                "type": "OBJECT",
                "properties": {
                    "rationale": {"type": "STRING"},
                    "verdict": {"type": "STRING", "enum": ["yes", "no"]},
                },
                "required": ["rationale", "verdict"],
            }
            for rid in rubric_ids
        },
        "required": rubric_ids,
    }


def build_system_prompt(rubrics: list[dict]) -> str:
    rubric_block = "\n".join(
        f"- **{r['rubric_id']}**: {r['rubric_content']['text_property']}"
        for r in rubrics
    )
    rubric_ids = [r["rubric_id"] for r in rubrics]
    example_shape = "{\n" + ",\n".join(
        f'  "{rid}": {{"rationale": "<your reasoning>", "verdict": "yes" or "no"}}' for rid in rubric_ids
    ) + "\n}"
    return f"""You are a correctness-property judge evaluating a pre-recorded multi-agent GAIA trajectory. For each rubric below, decide whether the stated positive correctness property HOLDS for this trajectory.

**Polarity convention:** Each rubric is phrased so that `verdict: "yes"` means "the property holds" (the trajectory is clean on that dimension). `verdict: "no"` means "the property is violated" (the trajectory exhibits that failure mode). Set `verdict: "yes"` when the property is clearly met OR when the property is not applicable to this trajectory (e.g., a code-block property when the agent wrote no code). Set `verdict: "no"` ONLY when the trajectory demonstrably violates the property.

**Rubrics to evaluate:**
{rubric_block}

**Output contract:** Return a JSON object with EXACTLY these top-level keys (one per rubric id above): {rubric_ids}. Each value is an object with keys `rationale` (string) and `verdict` (the literal string "yes" or "no", no other values). Emit `rationale` first, then `verdict`. Do not wrap the JSON in markdown code fences. Do not add any text before or after the JSON object.

**Output shape example:**
{example_shape}
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
        "Return your JSON verdicts now.\n"
    )


def build_request(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Vertex batch Gemini request shape.

    Note: Vertex batch's proto parser chokes on `responseSchema` with nested
    enum values (as of 2026-04-19, gemini-3.1-pro-preview in `global`). The
    error message is misleading — it claims `properties[0].properties[1].enum[0]`
    but the offset always points into the user content, suggesting a parser
    bug that over-consumes after nested enum. Workaround: drop responseSchema
    and rely on prompt discipline + `responseMimeType: application/json` to
    get structured output. The schema stays in the system prompt as guidance.
    """
    return {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }


def predict_cluster(verdicts: dict[str, str]) -> tuple[str | None, bool]:
    """Return (predicted_cluster, unassignable).

    Positive-correctness polarity: `no` verdict = failure exhibited.
    Predicted cluster = rubric with a `no` verdict (argmin). Ties broken by
    CLUSTER_PRIORITY. Unassignable if all verdicts are `yes`.
    """
    no_ids = [rid for rid, v in verdicts.items() if v == "no"]
    if not no_ids:
        return None, True
    for cid in CLUSTER_PRIORITY:
        if cid in no_ids:
            return cid, False
    return no_ids[0], False


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

    evalset_path = EVALSET_DIR / f"{args.split}.with_gt.evalset.json"
    if not evalset_path.exists():
        print(f"ERROR: {evalset_path} not found", file=sys.stderr)
        return 1
    evalset = json.loads(evalset_path.read_text())
    cases = evalset["eval_cases"]
    if args.limit:
        cases = cases[: args.limit]

    rubrics = load_rubrics()
    rubric_ids = [r["rubric_id"] for r in rubrics]
    schema = build_response_schema(rubric_ids)
    sys_prompt = build_system_prompt(rubrics)
    print(f"Phase B batch | split={args.split} | n={len(cases)} | model={args.judge_model} | rubrics={rubric_ids}")

    import batch_utils as bu

    requests = [
        bu.BatchRequest(
            key=c["eval_id"],
            request_body=build_request(sys_prompt, build_user_prompt(c), schema),
        )
        for c in cases
    ]

    run_id = bu.new_run_id(f"phase-b-{args.split}")
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

    downloaded = bu.download_output_jsonl(gcs_output_prefix, local_output, project=project)
    if not downloaded:
        print(f"ERROR: no predictions.jsonl under {gcs_output_prefix}", file=sys.stderr)
        return 3
    print(f"Downloaded predictions -> {local_output}")

    # Vertex batch does NOT preserve input row order — align output rows back
    # to cases by the trajectory id embedded in each prompt.
    by_key = bu.parse_output_by_key(local_output, bu.make_trajectory_id_extractor())
    per_case_path = out_dir / "per_case.jsonl"
    records = []
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
                rec = {**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": "no output row"}
            else:
                response, err = match
                if err:
                    rec = {**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": err}
                else:
                    text = bu.extract_text(response)
                    if not text:
                        rec = {**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": "no text in response"}
                    else:
                        try:
                            parsed = json.loads(text)
                            verdicts = {rid: parsed[rid]["verdict"] for rid in rubric_ids if rid in parsed}
                            rationales = {rid: parsed[rid]["rationale"] for rid in rubric_ids if rid in parsed}
                            pred_c, unass = predict_cluster(verdicts)
                            rec = {
                                **base,
                                "verdicts": verdicts,
                                "rationales": rationales,
                                "predicted_cluster": pred_c,
                                "predicted_level": CLUSTER_LEVEL.get(pred_c),
                                "unassignable": unass,
                                "error": None,
                            }
                        except (KeyError, json.JSONDecodeError) as e:
                            rec = {**base, "verdicts": {}, "rationales": {}, "predicted_cluster": None, "predicted_level": None, "unassignable": True, "error": f"{type(e).__name__}: {e}", "raw_text": text[:500]}
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary
    errors = [r for r in records if r.get("error")]
    correct_cluster = sum(1 for r in records if r.get("predicted_cluster") == r["gt_cluster"])
    correct_level = sum(1 for r in records if r.get("predicted_level") == r["gt_level"])
    unassignable = sum(1 for r in records if r.get("unassignable"))

    confusion = defaultdict(Counter)
    for r in records:
        confusion[r["gt_cluster"]][r.get("predicted_cluster") or "UNASSIGNED"] += 1

    summary = {
        "split": args.split,
        "judge_model": args.judge_model,
        "run_id": run_id,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(correct_cluster / max(1, len(records)), 3),
        "level_accuracy": round(correct_level / max(1, len(records)), 3),
        "unassignable_rate": round(unassignable / max(1, len(records)), 3),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(Counter(r.get("predicted_cluster") or "UNASSIGNED" for r in records)),
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "gcs_input": gcs_input,
        "gcs_output_prefix": gcs_output_prefix,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n=== Phase B Batch Summary ({args.split}) ===")
    print(f"  Cases: {summary['n_cases']}  Errors: {summary['errors']}")
    print(f"  Cluster accuracy: {summary['cluster_accuracy']}")
    print(f"  Level accuracy:   {summary['level_accuracy']}")
    print(f"  Unassignable:     {summary['unassignable_rate']}")
    print(f"  Outputs: {out_dir}/")
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
