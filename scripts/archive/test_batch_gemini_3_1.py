"""Validate Vertex batch prediction for gemini-3.1-pro-preview.

Writes a 1-request JSONL, uploads to gs://agenttracebucket/test_batch/input.jsonl,
submits a batch job, polls, and prints the result. Purpose: confirm the
input/output schema and supported location before refactoring phase_b/c runners.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# Force global location for gemini-3.1-pro-preview (verified by test_gemini_3_1_pro.py).
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from google import genai
from google.cloud import storage

BUCKET = "agenttracebucket"
TEST_PREFIX = "test_batch"
INPUT_BLOB = f"{TEST_PREFIX}/input.jsonl"
OUTPUT_PREFIX = f"{TEST_PREFIX}/output"

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]


def write_input_jsonl(local_path: Path):
    """Write one trivial batch request. Format from Vertex batch prediction docs."""
    req = {
        "request": {
            "contents": [
                {"role": "user", "parts": [{"text": "Reply with exactly: 'batch call OK'."}]}
            ],
            "generation_config": {"temperature": 0.0},
        }
    }
    local_path.write_text(json.dumps(req) + "\n")


def upload_to_gcs(local_path: Path, gcs_uri: str):
    client = storage.Client(project=PROJECT)
    bucket_name, blob_name = gcs_uri.replace("gs://", "").split("/", 1)
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(local_path)
    print(f"Uploaded {local_path} -> {gcs_uri}")


def download_output(gcs_uri: str, local_path: Path):
    client = storage.Client(project=PROJECT)
    bucket_name, prefix = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = client.bucket(bucket_name)
    # Batch writes predictions.jsonl under the output prefix.
    blobs = list(bucket.list_blobs(prefix=prefix))
    print(f"Output blobs under {gcs_uri}:")
    for b in blobs:
        print(f"  {b.name}  ({b.size} bytes)")
    if not blobs:
        print("  (no blobs yet)")
        return
    # Download the first predictions file.
    for b in blobs:
        if b.name.endswith(".jsonl") and "predictions" in b.name:
            b.download_to_filename(local_path)
            print(f"Downloaded {b.name} -> {local_path}")
            return local_path
    print("No predictions.jsonl found; downloading first jsonl")
    for b in blobs:
        if b.name.endswith(".jsonl"):
            b.download_to_filename(local_path)
            return local_path


def main():
    # 1. Write + upload input.
    local_input = REPO_ROOT / "outputs" / "test_batch" / "input.jsonl"
    local_input.parent.mkdir(parents=True, exist_ok=True)
    write_input_jsonl(local_input)
    upload_to_gcs(local_input, f"gs://{BUCKET}/{INPUT_BLOB}")

    # 2. Submit batch.
    client = genai.Client(vertexai=True, project=PROJECT, location="global")
    print(f"Submitting batch: model=gemini-3.1-pro-preview, location=global, src=gs://{BUCKET}/{INPUT_BLOB}")
    from google.genai import types as gt
    job = client.batches.create(
        model="gemini-3.1-pro-preview",
        src=f"gs://{BUCKET}/{INPUT_BLOB}",
        config=gt.CreateBatchJobConfig(dest=f"gs://{BUCKET}/{OUTPUT_PREFIX}"),
    )
    print(f"Job created: {job.name}")
    print(f"Initial state: {job.state}")

    # 3. Poll.
    t0 = time.time()
    while True:
        job = client.batches.get(name=job.name)
        elapsed = int(time.time() - t0)
        print(f"  [{elapsed}s] state={job.state}")
        if str(job.state).endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
            break
        time.sleep(15)

    print(f"\nFinal state: {job.state}")
    if str(job.state).endswith("FAILED"):
        print(f"Error: {getattr(job, 'error', None)}")
        return 1

    # 4. Download output.
    local_output = REPO_ROOT / "outputs" / "test_batch" / "predictions.jsonl"
    download_output(f"gs://{BUCKET}/{OUTPUT_PREFIX}", local_output)
    if local_output.exists():
        print("\n--- predictions.jsonl ---")
        print(local_output.read_text())


if __name__ == "__main__":
    main()
