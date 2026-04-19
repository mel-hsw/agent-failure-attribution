"""Resume / harvest helper for Phase C runs whose local pollers died mid-job.

When a `phase_c_*` Python script is SIGTERM'd during `submit_and_wait`, the
Vertex batch job it submitted is unaffected — it continues server-side. This
script reconnects to already-submitted batches by checking the GCS output
prefixes embedded in the run directory name, then downloads predictions and
produces the missing local artifacts.

Two modes:

  --mode constraint_grounded RUN_DIR
      Resume a `phase_c_constraint_grounded.py` run directory. Handles both
      full runs (needs Pass 1 predictions, then submits Pass 2 locally if
      not yet done) and ablation runs (only Pass 2 input exists).

  --mode all_at_once RUN_DIR
      Resume a `phase_c_all_at_once.py` run directory. One batch, one set of
      predictions.

Usage:
    python3 scripts/phase_c_resume.py --mode constraint_grounded \\
        outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-20260419T025815-48bbec
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

DEFAULT_BUCKET = "agenttracebucket"
CLUSTER_IDS = ["N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"]
CLUSTER_LEVEL = {cid: ("node" if cid.startswith("N") else "process") for cid in CLUSTER_IDS}


def infer_gcs_prefix(run_dir: Path) -> str:
    """Map a local run dir to the GCS object prefix the original script used."""
    parts = run_dir.parts
    # e.g. outputs/phase_c/constraint_grounded/eval/<run_id>
    if "phase_c" in parts:
        phase_idx = parts.index("phase_c")
        component = parts[phase_idx + 1]
        run_id = parts[-1]
        if component == "constraint_grounded":
            return f"phase_c/constraint_grounded/{run_id}"
        if component == "all_at_once":
            return f"phase_c/all_at_once/{run_id}"
    raise RuntimeError(f"Can't infer GCS prefix from {run_dir}")


def _poll_gcs_predictions(output_prefix: str, project: str, max_wait_s: int = 10800, interval: int = 45) -> Path:
    """Wait for a predictions.jsonl to appear under the given GCS prefix."""
    from google.cloud import storage

    client = storage.Client(project=project)
    bucket_name, prefix = output_prefix.replace("gs://", "").split("/", 1)
    bucket = client.bucket(bucket_name)
    t0 = time.time()
    last_msg = None
    while time.time() - t0 < max_wait_s:
        blobs = [b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith("predictions.jsonl")]
        if blobs:
            latest = max(blobs, key=lambda b: b.time_created)
            print(f"  Found predictions at gs://{bucket_name}/{latest.name}")
            return latest
        msg = f"  waiting for predictions under {output_prefix} (elapsed {int(time.time()-t0)}s)"
        if msg != last_msg:
            print(msg)
            last_msg = msg
        time.sleep(interval)
    raise TimeoutError(f"No predictions.jsonl under {output_prefix} after {max_wait_s}s")


def _download(blob, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(local_path)


# ---------------------------------------------------------------------------
# Mode: all_at_once


def resume_all_at_once(run_dir: Path, bucket: str, project: str) -> int:
    import batch_utils as bu
    import importlib

    phase_c_all_at_once = importlib.import_module("phase_c_all_at_once")

    gcs_prefix = infer_gcs_prefix(run_dir)
    gcs_output = f"gs://{bucket}/{gcs_prefix}/output"
    local_output = run_dir / "predictions.jsonl"

    if not local_output.exists():
        print(f"Polling Vertex output at {gcs_output}")
        blob = _poll_gcs_predictions(gcs_output, project)
        _download(blob, local_output)
        print(f"Downloaded -> {local_output}")
    else:
        print(f"Predictions already local: {local_output}")

    # Determine which split this is from run_dir path
    split = run_dir.parent.name  # .../all_at_once/<split>/<run_id>
    evalset_path = REPO_ROOT / "data" / "evalsets" / f"{split}.with_gt.evalset.json"
    cases = json.loads(evalset_path.read_text())["eval_cases"]
    rows = list(bu.parse_output_rows(local_output))

    per_case_path = run_dir / "per_case.jsonl"
    records: list[dict] = []
    rows_by_idx = {i: (resp, err) for i, resp, err in rows}
    with per_case_path.open("w") as f:
        for i, case in enumerate(cases):
            gt = case["metadata"].get("gt", {})
            base = {
                "trajectory_id": case["eval_id"],
                "gt_cluster": gt.get("proposed_cluster"),
                "gt_level": gt.get("proposed_level"),
                "gt_origin_step": gt.get("critical_failure_step"),
            }
            resp, err = rows_by_idx.get(i, (None, "no output row"))
            if err or resp is None:
                rec = {**base, "prediction": None, "error": err or "no response"}
            else:
                text = bu.extract_text(resp)
                if not text:
                    rec = {**base, "prediction": None, "error": "no text"}
                else:
                    try:
                        parsed = json.loads(text)
                        pc = parsed.get("predicted_cluster")
                        if pc in CLUSTER_LEVEL:
                            parsed["predicted_level"] = CLUSTER_LEVEL[pc]
                        rec = {**base, "prediction": parsed, "error": None}
                    except json.JSONDecodeError as e:
                        rec = {**base, "prediction": None, "error": f"JSONDecodeError: {e}", "raw_text": text[:500]}
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _write_summary_all_at_once(run_dir, records, split)
    return 0


def _write_summary_all_at_once(run_dir: Path, records: list[dict], split: str) -> None:
    errors = [r for r in records if r.get("error")]

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

    summary = {
        "split": split,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(sum(cluster_match(r) for r in records) / max(1, len(records)), 3),
        "level_accuracy": round(sum(level_match(r) for r in records) / max(1, len(records)), 3),
        "origin_step_tol0": round(sum(step_within(r, 0) for r in records) / max(1, len(records)), 3),
        "origin_step_tol3": round(sum(step_within(r, 3) for r in records) / max(1, len(records)), 3),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(((r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED") for r in records)
        ),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Summary: {summary['n_cases']} cases, cluster={summary['cluster_accuracy']}, level={summary['level_accuracy']}, tol-3={summary['origin_step_tol3']}, errors={summary['errors']}")


# ---------------------------------------------------------------------------
# Mode: constraint_grounded


def resume_constraint_grounded(run_dir: Path, bucket: str, project: str) -> int:
    import batch_utils as bu
    import trajectory_replayer as tr
    import phase_c_constraint_grounded as cg
    from google import genai

    split = run_dir.parent.name
    evalset_path = REPO_ROOT / "data" / "evalsets" / f"{split}.with_gt.evalset.json"
    cases = json.loads(evalset_path.read_text())["eval_cases"]

    has_constraint_input = (run_dir / "input_constraints.jsonl").exists()
    has_attribution_input = (run_dir / "input_attribution.jsonl").exists()
    has_constraint_preds = (run_dir / "predictions_constraints.jsonl").exists()
    has_attribution_preds = (run_dir / "predictions_attribution.jsonl").exists()

    ablation_mode = has_attribution_input and not has_constraint_input
    print(f"Mode: {'ABLATION (Pass 2 only)' if ablation_mode else 'FULL (Pass 1 + Pass 2)'}")

    gcs_prefix = infer_gcs_prefix(run_dir)

    # ---------------------------------------------------------------- Pass 1
    dynamic_logs_by_id: dict[str, list[dict]] = {c["eval_id"]: [] for c in cases}
    static_logs_by_id: dict[str, list[dict]] = {c["eval_id"]: [] for c in cases}

    if not ablation_mode:
        # Static constraints (always re-run locally; it's cheap)
        print("[Pass 0] Running static constraints...")
        for c in cases:
            static_logs_by_id[c["eval_id"]] = [
                e.to_dict() for e in tr.replay(c["metadata"]["trajectory"], step_budget=30)
            ]
        n_flagged = sum(1 for v in static_logs_by_id.values() if v)
        print(f"  Static events: {sum(len(v) for v in static_logs_by_id.values())} across {n_flagged}/{len(cases)} cases")

        if not has_constraint_preds:
            gcs_output = f"gs://{bucket}/{gcs_prefix}/constraints_output"
            print(f"[Pass 1] Polling Vertex output {gcs_output}")
            blob = _poll_gcs_predictions(gcs_output, project)
            _download(blob, run_dir / "predictions_constraints.jsonl")

        rows = list(bu.parse_output_rows(run_dir / "predictions_constraints.jsonl"))
        rows_by_idx = {i: (resp, err) for i, resp, err in rows}
        for i, case in enumerate(cases):
            resp, err = rows_by_idx.get(i, (None, "no output row"))
            if err or resp is None:
                continue
            text = bu.extract_text(resp)
            if not text:
                continue
            try:
                parsed = json.loads(text)
                dynamic_logs_by_id[case["eval_id"]] = parsed.get("constraint_events") or []
            except json.JSONDecodeError:
                continue

        (run_dir / "violation_logs.jsonl").write_text(
            "\n".join(
                json.dumps(
                    {
                        "trajectory_id": c["eval_id"],
                        "static_events": static_logs_by_id[c["eval_id"]],
                        "dynamic_events": dynamic_logs_by_id[c["eval_id"]],
                    },
                    ensure_ascii=False,
                )
                for c in cases
            )
            + "\n"
        )

    # ---------------------------------------------------------------- Pass 2
    if not has_attribution_preds:
        if not has_attribution_input:
            # Build Pass 2 input (full mode, post Pass 1)
            print("[Pass 2] Building attribution batch input...")
            attr_sys = cg.attribution_system_prompt()
            attr_requests = []
            for c in cases:
                log_md = cg.render_merged_log(
                    static_logs_by_id[c["eval_id"]],
                    dynamic_logs_by_id[c["eval_id"]],
                )
                attr_requests.append(
                    bu.BatchRequest(
                        key=c["eval_id"],
                        request_body=cg.build_attribution_request(
                            attr_sys, cg.build_attribution_user_prompt(c, log_md)
                        ),
                    )
                )
            attr_input = run_dir / "input_attribution.jsonl"
            bu.write_jsonl(attr_requests, attr_input)
            gcs_attr_input = f"gs://{bucket}/{gcs_prefix}/attribution_input.jsonl"
            gcs_attr_output = f"gs://{bucket}/{gcs_prefix}/attribution_output"
            bu.upload_to_gcs(attr_input, gcs_attr_input, project=project)
            print(f"  Uploaded -> {gcs_attr_input}")
            client = genai.Client(vertexai=True, project=project, location="global")
            job = bu.submit_and_wait(
                client=client,
                model="gemini-3.1-pro-preview",
                src_uri=gcs_attr_input,
                dest_uri=gcs_attr_output,
                poll_interval_s=30,
                on_state_change=lambda s, e: print(f"  [{e}s] {s}"),
            )
            if not str(job.state).endswith("SUCCEEDED"):
                print(f"  Pass 2 failed: {getattr(job, 'error', None)}", file=sys.stderr)
                return 2

        # Download predictions (attribution submitted either above or originally)
        gcs_attr_output = f"gs://{bucket}/{gcs_prefix}/attribution_output"
        print(f"[Pass 2] Polling Vertex output {gcs_attr_output}")
        blob = _poll_gcs_predictions(gcs_attr_output, project)
        _download(blob, run_dir / "predictions_attribution.jsonl")

    # ---------------------------------------------------------------- Parse
    rows = list(bu.parse_output_rows(run_dir / "predictions_attribution.jsonl"))
    rows_by_idx = {i: (resp, err) for i, resp, err in rows}
    per_case_path = run_dir / "per_case.jsonl"
    records: list[dict] = []
    with per_case_path.open("w") as f:
        for i, case in enumerate(cases):
            cid = case["eval_id"]
            gt = case["metadata"].get("gt", {})
            base = {
                "trajectory_id": cid,
                "gt_cluster": gt.get("proposed_cluster"),
                "gt_level": gt.get("proposed_level"),
                "gt_origin_step": gt.get("critical_failure_step"),
                "static_events": static_logs_by_id[cid],
                "dynamic_events": dynamic_logs_by_id[cid],
            }
            resp, err = rows_by_idx.get(i, (None, "no output row"))
            if err or resp is None:
                rec = {**base, "prediction": None, "error": err or "no response"}
            else:
                text = bu.extract_text(resp)
                if not text:
                    rec = {**base, "prediction": None, "error": "no text"}
                else:
                    try:
                        parsed = json.loads(text)
                        pc = parsed.get("predicted_cluster")
                        if pc in CLUSTER_LEVEL:
                            parsed["predicted_level"] = CLUSTER_LEVEL[pc]
                        rec = {**base, "prediction": parsed, "error": None}
                    except json.JSONDecodeError as e:
                        rec = {**base, "prediction": None, "error": f"JSONDecodeError: {e}", "raw_text": text[:500]}
            records.append(rec)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _write_summary_cg(run_dir, records, split, ablation=ablation_mode,
                     static_events=static_logs_by_id, dynamic_events=dynamic_logs_by_id)
    return 0


def _write_summary_cg(run_dir: Path, records: list[dict], split: str, ablation: bool,
                      static_events: dict, dynamic_events: dict) -> None:
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

    log_citation_rate = None
    if not ablation:
        cited = sum(
            1 for r in successful
            if ((r.get("prediction") or {}).get("cited_log_rows") or [])
        )
        log_citation_rate = round(cited / max(1, len(successful)), 3)

    summary = {
        "split": split,
        "ablation_no_violation_log": ablation,
        "n_cases": len(records),
        "errors": len(errors),
        "cluster_accuracy": round(sum(cluster_match(r) for r in records) / max(1, len(records)), 3),
        "level_accuracy": round(sum(level_match(r) for r in records) / max(1, len(records)), 3),
        "origin_step_tol0": round(sum(step_within(r, 0) for r in records) / max(1, len(records)), 3),
        "origin_step_tol3": round(sum(step_within(r, 3) for r in records) / max(1, len(records)), 3),
        "log_citation_rate": log_citation_rate,
        "static_event_count": sum(len(v) for v in static_events.values()),
        "dynamic_event_count": sum(len(v) for v in dynamic_events.values()),
        "gt_cluster_distribution": dict(Counter(r["gt_cluster"] for r in records)),
        "predicted_cluster_distribution": dict(
            Counter(((r.get("prediction") or {}).get("predicted_cluster") or "UNASSIGNED") for r in records)
        ),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Summary: {summary['n_cases']} cases, cluster={summary['cluster_accuracy']}, level={summary['level_accuracy']}, "
          f"tol-3={summary['origin_step_tol3']}, errors={summary['errors']}, ablation={ablation}")


# ---------------------------------------------------------------------------
# Entrypoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="Path to run dir under outputs/phase_c/*/")
    parser.add_argument("--mode", choices=("constraint_grounded", "all_at_once"), required=True)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    project = os.environ["GOOGLE_CLOUD_PROJECT"]

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"ERROR: {run_dir} does not exist", file=sys.stderr)
        return 1

    if args.mode == "constraint_grounded":
        return resume_constraint_grounded(run_dir, args.bucket, project)
    return resume_all_at_once(run_dir, args.bucket, project)


if __name__ == "__main__":
    sys.exit(main())
