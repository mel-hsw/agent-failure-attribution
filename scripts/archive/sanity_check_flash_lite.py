"""Sanity-check: pick 5 random eval cases, run them SYNC (not batch) with the
same prompt + model + temperature, and compare to what the batch produced.

If sync ≈ batch, the batch is running correctly and flash-lite's 20% is real.
If sync ≠ batch, there's a bug in the batch flow.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phase_c_all_at_once_v3 import build_system_prompt, build_user_prompt  # noqa: E402

EVALSET = REPO_ROOT / "data" / "evalsets" / "eval.with_gt.evalset.json"
BATCH_PER_CASE = sorted(
    (REPO_ROOT / "outputs" / "phase_c" / "all_at_once_v3" / "gemini-3-1-flash-lite-preview" / "eval").glob("*/per_case.jsonl")
)[-1]
MODEL = "gemini-3.1-flash-lite-preview"
TEMPERATURE = 0.3
N_SAMPLES = 5
SEED = 42


def main():
    load_dotenv(REPO_ROOT / ".env")
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

    # Load batch results (already mis-alignment-fixed)
    batch_records = {json.loads(l)["trajectory_id"]: json.loads(l) for l in BATCH_PER_CASE.open()}
    print(f"Loaded {len(batch_records)} batch records from {BATCH_PER_CASE.relative_to(REPO_ROOT)}")

    # Pick 5 random eval cases
    evalset = json.loads(EVALSET.read_text())
    cases = evalset["eval_cases"]
    rng = random.Random(SEED)
    sample = rng.sample(cases, N_SAMPLES)
    print(f"Sampled {N_SAMPLES} cases (seed={SEED})")

    # Run sync for each, compare to batch record
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location="global",
    )
    sys_prompt = build_system_prompt()

    print(f"\n{'='*100}")
    print(f"Running {N_SAMPLES} cases sync | model={MODEL} | temp={TEMPERATURE}")
    print(f"{'='*100}\n")

    matches = 0
    for case in sample:
        tid = case["eval_id"]
        batch_rec = batch_records.get(tid)
        batch_pred = (batch_rec or {}).get("prediction") or {}
        gt = case["metadata"].get("gt", {})

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
            sync_pred = json.loads(resp.text)
        except Exception as e:
            sync_pred = {"error": f"{type(e).__name__}: {e}"}
        elapsed = round(time.time() - t0, 1)

        batch_c = batch_pred.get("predicted_cluster")
        batch_s = batch_pred.get("predicted_origin_step")
        sync_c = sync_pred.get("predicted_cluster")
        sync_s = sync_pred.get("predicted_origin_step")
        match = batch_c == sync_c
        if match:
            matches += 1

        print(f"--- {tid} ---")
        print(f"  gt:    {gt.get('proposed_cluster')}@{gt.get('critical_failure_step')}")
        print(f"  batch: {batch_c}@{batch_s} conf={batch_pred.get('confidence')}")
        print(f"  sync:  {sync_c}@{sync_s} conf={sync_pred.get('confidence')} ({elapsed}s)")
        if sync_pred.get("error"):
            print(f"  sync ERROR: {sync_pred['error'][:200]}")
        print(f"  cluster match: {'✓' if match else '✗'}")
        print()

    print(f"Sync ≈ batch cluster agreement: {matches}/{N_SAMPLES}")
    print()
    print("Interpretation:")
    print(f"  - 5/5: batch is deterministic at temp={TEMPERATURE}, running exactly as sync. Flash-lite 20% is real.")
    print(f"  - 3-4/5: plausible sampling variance at temp=0.3 (some non-determinism in thinking/top-k).")
    print(f"  - <=2/5: batch and sync are diverging meaningfully — investigate.")


if __name__ == "__main__":
    main()
