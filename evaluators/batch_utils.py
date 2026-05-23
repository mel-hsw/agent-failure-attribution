"""Shared helpers for Vertex batch-prediction runs.

Vertex batch-prediction on Gemini takes a GCS JSONL input, each line a
`{"request": {...}}` object. Output is a JSONL with `{"request": ..., "response": ...}`
lines (or `{"status": "..."}` for per-row errors). See
`scripts/test_batch_gemini_3_1.py` for the validated end-to-end shape.

This module factors out the common workflow so phase_b / phase_c runners can
stay focused on prompt construction and result parsing.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from google.cloud import storage


@dataclass
class BatchRequest:
    """One element of the batch. `request_body` is the full Vertex Gemini request
    (contents/system_instruction/generation_config). `key` is how we match the
    response row back to our trajectory id after the batch returns."""

    key: str
    request_body: dict


def write_jsonl(requests: Sequence[BatchRequest], local_path: Path) -> None:
    """Serialize requests to local JSONL. `key` is stashed into the `labels`
    field on each request so it round-trips via the Vertex API."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with local_path.open("w") as f:
        for br in requests:
            # Vertex batch returns the input "request" unchanged in each output
            # row, so we can recover key by embedding it in the request body
            # under a custom field the API preserves. The simplest stable option
            # is to put it in the `labels` sub-object — not all Gemini configs
            # honor that. Safer: embed key in the system_instruction prefix or
            # use row-index matching. We use row-index matching (see parse_output).
            f.write(json.dumps({"request": br.request_body}) + "\n")


def upload_to_gcs(local_path: Path, gcs_uri: str, project: str) -> None:
    client = storage.Client(project=project)
    bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(local_path)


def download_output_jsonl(gcs_output_prefix: str, local_path: Path, project: str) -> Path | None:
    """Vertex writes output under `<dest>/prediction-model-<timestamp>/predictions.jsonl`.
    Find the latest predictions.jsonl and download it."""
    client = storage.Client(project=project)
    bucket_name, prefix = gcs_output_prefix.replace("gs://", "").split("/", 1)
    bucket = client.bucket(bucket_name)
    predictions_blobs = [b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith("predictions.jsonl")]
    if not predictions_blobs:
        return None
    latest = max(predictions_blobs, key=lambda b: b.time_created)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    latest.download_to_filename(local_path)
    return local_path


def submit_and_wait(
    client,
    model: str,
    src_uri: str,
    dest_uri: str,
    poll_interval_s: int = 20,
    on_state_change: Callable[[str, int], None] | None = None,
) -> object:
    """Submit a batch job, poll until it reaches a terminal state, return the job.
    `client` is a google.genai.Client in Vertex mode."""
    from google.genai import types as gt

    job = client.batches.create(
        model=model,
        src=src_uri,
        config=gt.CreateBatchJobConfig(dest=dest_uri),
    )
    last_state = None
    t0 = time.time()
    while True:
        job = client.batches.get(name=job.name)
        state = str(job.state)
        if state != last_state:
            elapsed = int(time.time() - t0)
            if on_state_change:
                on_state_change(state, elapsed)
            last_state = state
        if state.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
            return job
        time.sleep(poll_interval_s)


def parse_output_rows(local_output_path: Path) -> Iterable[tuple[int, dict | None, str | None]]:
    """Yield (row_index, response_dict, error_msg) for each line in the predictions
    JSONL. NOTE: Vertex batch does NOT preserve input row order in the output;
    row_index is just the line position in the output file, not the original
    input row. For matching back to cases, use parse_output_by_key instead."""
    with local_output_path.open() as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            status = row.get("status") or ""
            response = row.get("response")
            if status and status != "":
                yield i, None, status
            elif response:
                yield i, response, None
            else:
                yield i, None, f"unknown row shape: {list(row.keys())}"


def _extract_request_user_text(row: dict) -> str | None:
    try:
        return row["request"]["contents"][0]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None


def parse_output_by_key(
    local_output_path: Path,
    extract_key: Callable[[str], str | None],
) -> dict[str, tuple[dict | None, str | None]]:
    """Parse the output JSONL and return a dict keyed by whatever `extract_key`
    returns when applied to each request's user text.

    This is the correct way to align batch predictions back to input cases —
    Vertex does not preserve input row order, but each output row carries its
    full request inline, so we can recover the key we embedded in the prompt.

    Returns: {key -> (response_dict_or_None, error_msg_or_None)}.
    Rows whose key cannot be extracted are silently skipped (caller is
    expected to notice missing keys and treat them as "no output row").
    """
    out: dict[str, tuple[dict | None, str | None]] = {}
    with local_output_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            user_text = _extract_request_user_text(row) or ""
            key = extract_key(user_text)
            if key is None:
                continue
            status = row.get("status") or ""
            response = row.get("response")
            if status and status != "":
                out[key] = (None, status)
            elif response:
                out[key] = (response, None)
            else:
                out[key] = (None, f"unknown row shape: {list(row.keys())}")
    return out


def make_trajectory_id_extractor():
    """Extract `<tid>` from prompts that contain `**Trajectory id:** <tid>`."""
    import re

    pat = re.compile(r"\*\*Trajectory id:\*\*\s*(\S+)")

    def extract(user_text: str) -> str | None:
        m = pat.search(user_text)
        return m.group(1) if m else None

    return extract


def extract_text(response: dict) -> str | None:
    """Pull the assistant text out of a Vertex Gemini response dict."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
        for p in parts:
            if "text" in p:
                return p["text"]
    except (KeyError, IndexError, TypeError):
        pass
    return None


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
