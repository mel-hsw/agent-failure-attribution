# Failure Attribution Experiment — Agent Handover

_Last updated: 2026-04-19. Written so a fresh agent can pick up Phase B (and beyond) without re-deriving context from the full transcript._

For the stable project contract read `CLAUDE.md`. For the canonical evolving state read `docs/PROJECT.md`. This handover focuses on **what's done, what's blocked, and exactly how to resume**.

---

## 1. Project in one paragraph

We're evaluating whether Google ADK's evaluation suite can correctly identify the **failure origin** on pre-recorded multi-agent trajectories from the GAIA benchmark. Ground truth lives in a 9-cluster taxonomy (N1-N5 node-level, P1-P4 process-level). The experiment runs in four phases: **A** (data adapter: clean, split, wrap in ADK EvalSets), **B** (off-the-shelf baseline using the built-in `rubric_based_final_response_quality_v1` evaluator), **C** (three custom evaluators — AllAtOnceAttribution, BinarySearchAttribution, ConstraintGroundedAttribution — plus a TrajectoryReplayer constraint checker), **D** (three-part scorecard: origin-step match, cluster/level match, late-symptom fidelity; stratified by source and cluster; κ calibration check).

---

## 2. Canonical dataset — read this before you touch anything

- Pre-patch source: `data/consolidated/gaia_consolidated.jsonl` (154 records).
- Cluster-review patch list: `data/consolidated/cluster_review_patch.jsonl` (49 entries: 27 cluster reassignments + 14 DROP + 8 FLAG).
- Reviewed source of truth: `data/consolidated/gaia_consolidated_reviewed.jsonl` (154 records with `review_status`, `review_original_cluster`, `review_reason`).
- **Active post-patch dataset: 133 records = 154 − 14 DROP − 7 FLAG.** (The patch file holds 8 FLAG entries but one is a no-op on an already-DROPped record. `phase_a_verify.py` encodes this as `EXPECTED_POST_PATCH_TOTAL = 133`.)
- Phase A outputs live under `data/consolidated/gaia_consolidated_{clean,with_gt}.jsonl`, `data/splits/{dev,calibration,eval}{,_clean}.jsonl`, and `data/evalsets/{dev,calibration,eval}{,.with_gt}.evalset.json`.

> ⚠️ **Regenerate Phase A outputs before Phase B runs.** An earlier Phase A pass emitted 134 records; the full record-by-record review added one more FLAG, dropping to 133. Re-run the whole Phase A pipeline via `python3 scripts/phase_a_verify.py` (it re-runs clean → split → build_evalset and then asserts the 133-record invariant end to end).

Post-patch cluster distribution (133 active, canonical): P1=32, P2=23, N2=16, P4=15, N1=13, N3=11, N5=8, P3=8, N4=7. Split after seed 20260418: dev=5, calibration=5, eval=123.

---

## 3. Phase A — done, but verify before using

Files in `scripts/`:
- `phase_a_clean.py` — strips 8 annotation keys (`ground_truth`, `critical_failure_step`, `critical_failure_module`, `raw_failure_type`, `failure_reasoning_text`, `proposed_cluster`, `proposed_cluster_label`, `proposed_level`) and the `won` metadata key from the reviewed source; emits `gaia_consolidated_clean.jsonl` and `gaia_consolidated_with_gt.jsonl`. Critical change: `apply_cluster_patches()` treats `new_cluster == "DROP"` and `"FLAG"` as **record-removing sentinels**, not cluster labels.
- `phase_a_split.py` — stratified round-robin split by `(source × cluster)`, seed `20260418`, dev=5, calibration=5, eval=rest. Writes the 6 split files + `data/splits/split_manifest.json`.
- `phase_a_build_evalset.py` — wraps each split as an ADK EvalSet. Because multi-agent W&W trajectories don't fit ADK's single-agent Invocation schema, the converter preserves the full native trajectory in `eval_case.metadata.trajectory` and synthesizes a minimal Invocation from `(first user message, last non-terminator message)` so built-in evaluators still work.
- `phase_a_verify.py` — end-to-end check. Re-runs the three scripts, then validates counts, stripped annotations, regex leakage scan, disjoint splits, all 9 clusters in `eval`, and gt-presence parity between judge-visible and with_gt EvalSets.

**To bring Phase A up to date:** `python3 scripts/phase_a_verify.py` from the repo root. Must exit 0 and print `=== Phase A verification PASSED ===`.

---

## 4. Phase B — ready to run, BLOCKED on auth

### What's built

- `data/rubrics/option_b_rubric.json` — **9 rubrics, one per cluster**. Each is a `FINAL_RESPONSE_QUALITY` yes/no rubric where "yes" = trajectory exhibits that failure mode. Design note inside the file: step4_plan §6 asked for a single rubric emitting structured JSON, but ADK's built-in prompt template has a hardwired Property/Evidence/Rationale/Verdict form that can't emit structured JSON, so the honest off-the-shelf baseline uses 9 rubrics + argmax. Structured-JSON attribution moves to Phase C's `AllAtOnceAttribution` custom evaluator.
- `scripts/phase_b_rubric_baseline.py` — async runner. Loads `.env`, detects auth mode (Vertex vs AI Studio), builds `RubricBasedFinalResponseQualityV1Evaluator`, reconstructs an ADK `Invocation` per eval case, calls `evaluate_invocations`, and writes `outputs/phase_b/<split>/{per_case.jsonl, summary.json}`. Predicted cluster = argmax of yes-scores; ties broken by fixed priority `["N5","N4","N3","N2","N1","P4","P3","P2","P1"]`; "unassignable" when every rubric scores 0. CLI: `--split`, `--judge-model` (default `gemini-2.5-flash`), `--num-samples` (default 1), `--parallelism` (default 4), `--limit`.

### ADK API gotchas already fixed (don't re-hit these)

- Rubrics must be attached to the **criterion**, not to the Invocation — passing them on both trips `Rubric with rubric_id 'X' already exists`.
- `IntermediateData` is imported from `google.adk.evaluation.eval_case`, not `eval_metrics`. There is no `ToolUse` class — use `google.genai.types.FunctionCall` + `FunctionResponse` pairs (that's the actual `IntermediateData` schema).
- The sandbox is behind a SOCKS proxy; `pip install "httpx[socks]" socksio --break-system-packages` is required once per fresh environment.
- `RubricsBasedCriterion` asserts rubrics are non-empty — `phase_b_rubric_baseline.build_evaluator(judge_model, num_samples, rubrics)` threads them through.

### Current blocker

Smoke test on 1 dev case fails at the judge call with `DefaultCredentialsError`. The `.env` currently contains **both** `GEMINI_API_KEY=...` (line 1) **and** `GOOGLE_GENAI_USE_VERTEXAI=1` + `GOOGLE_CLOUD_PROJECT=agentevaluationtest` + `GOOGLE_CLOUD_LOCATION=us-central1` (lines 3-5). Because ADK checks `GOOGLE_GENAI_USE_VERTEXAI` first, it tries Vertex AI Application Default Credentials, which aren't present in the sandbox.

### How to resume Phase B (exact steps)

1. **Decide auth mode with Mel.** She said "start with Option 1 to make sure it works, then switch to Option 2 for the full experiment."
   - **Option 1 (AI Studio) — for smoke test.** Edit `.env` so the Vertex lines are commented out or removed, leaving only `GEMINI_API_KEY=<key from https://aistudio.google.com/apikey>`. Confirm the current key on line 1 is still valid (it was set during the previous session; if it's rotated, ask for a new one).
   - **Option 2 (Vertex AI) — for the full 123-case eval run.** Keep the Vertex lines, plus run `gcloud auth application-default login` **on the host machine** (the sandbox can't do this — if you try, explain that and escalate to Mel).

2. **Install sandbox deps** (idempotent): `pip install "httpx[socks]" socksio python-dotenv google-adk --break-system-packages`. Verify `python3 -c "import google.adk; print(google.adk.__version__)"` reports ≥ 1.31.0.

3. **Single-case smoke test**:
   ```
   python3 scripts/phase_b_rubric_baseline.py --split dev --num-samples 1 --parallelism 1 --limit 1
   ```
   Expected: the case prints `pred=<cluster> gt=P1 (OK, <few>s)` and `outputs/phase_b/dev/summary.json` has `errors: 0`.

4. **Full dev smoke** (5 cases, still cheap): drop `--limit 1`. Inspect `per_case.jsonl` rationales for sanity.

5. **Eval run.** Switch to Option 2 if not already, then:
   ```
   python3 scripts/phase_b_rubric_baseline.py --split eval --num-samples 5 --parallelism 4
   ```
   Roughly 123 cases × 9 rubrics × 5 samples = ~5.5k judge calls; budget accordingly. Results go to `outputs/phase_b/eval/summary.json` (cluster_accuracy, level_accuracy, unassignable_rate, confusion matrix) and feed Phase D.

6. **Calibration run** (same command with `--split calibration`): lets Phase D compute a judge-vs-human κ before trusting eval numbers.

---

## 5. Phase C — implemented, needs live smoke + eval runs

All three evaluators default to **`gemini-3.1-pro-preview` on Vertex `location=global`** (matches `phase_b_batch.py` / `phase_c_all_at_once.py`). The preview model is only served from `global` — regional endpoints 404.

- **`scripts/phase_c_all_at_once.py`** — Vertex batch. Single structured-JSON attribution per trajectory. Complete.
- **`scripts/phase_c_binary_search.py`** — online async via `google.genai.aio`. Bisection is sequential per trajectory (each midpoint depends on the previous verdict), so it can't collapse into a single batch; uses a semaphore for cross-trajectory parallelism. Per trajectory: ~log₂(n)+1 judge calls.
- **`scripts/phase_c_constraint_grounded.py`** — two-pass Vertex batch. Pass 0 (Python) runs Tier-1 static constraints via `scripts/trajectory_replayer.py` (S4 repeated tool calls, S5/S6 heuristic terminal actions, S8 fresh-token error signals, S9 per-author step budget). Pass 1 batch synthesizes+evaluates D1–D9 per trajectory. Pass 2 batch emits final attribution with the merged violation log as evidence. `--no-violation-log` implements the §9 ablation.

Smoke-tested the replayer on 123 eval cases: 74 flagged, distribution {S8: 756, S4: 244, S9: 8} — S8 tightened to ignore tokens already present in step 0 so AEB's re-embedded task preamble doesn't inflate.

---

## 6. Phase D — designed, not yet implemented

Three-part scorecard per CLAUDE.md objective:

1. **Origin-step match.** Primary: tolerance-3 (human annotation wobble). Secondary: tolerance-0 (strict). W&W shows t-0 is ~17% and t-5 is ~43%, so t-3 is the honest number.
2. **Cluster match** and, separately, **level match** (node vs process).
3. **Late-symptom fidelity** — does the evaluator correctly trace cascading errors (P3, n=8 in active set) back to the origin step rather than the symptom step? This is the cluster that most exercises the "earliest step" objective; report it separately.

Stratified by `source` (AEB / W&W-HC / W&W-AG) and `cluster`. Compute a judge-vs-human κ on the calibration split before trusting eval numbers.

---

## 7. Known landmines

- **Don't re-add FLAG records back into the eval set.** They're either step-0 mis-annotations or have step content missing from the stored history; no step-localization evaluator can score them.
- **Don't classify anything new without listing label signatures first** (per CLAUDE.md working agreement). The 9-cluster taxonomy is settled for the current paper; any extension goes through Mel.
- **P3 is the late-symptom stress test** — n=8 in the active set. Watch it specifically when reading Phase B results; a baseline that predicts the symptom cluster (N1/N2/N3) instead of tracing back will look deceptively fine on N* accuracy but fail the objective.
- **The sandbox has no host-side gcloud auth.** If Vertex AI is needed, Mel has to run `gcloud auth application-default login` on her machine and re-launch the host process.
- **No local shell state between bash calls.** Each `mcp__workspace__bash` invocation is independent; use absolute paths and pass env vars via `.env` + `python-dotenv`, not via `export`.

---

## 8. Open questions for Mel (surface these early)

1. Auth mode for the smoke test — Option 1 AI Studio (she said this) vs finishing the `.env` cleanup (currently has both sets of creds).
2. Is the AI Studio key on line 1 of `.env` still valid, or has it been rotated since the previous session?
3. Judge-model policy: stick with `gemini-2.5-flash` for B or also run `gemini-2.5-pro` as an ablation?
4. Parallelism tolerance for the 123-case eval run — default 4 is polite; can bump to 8 if quota allows.

---

## 9. Files you'll edit most

- `scripts/phase_b_rubric_baseline.py` — Phase B runner (complete, needs an auth-resolved test).
- `scripts/phase_c_*.py` — doesn't exist yet; Phase C runners go here.
- `data/rubrics/option_b_rubric.json` — fixed for Phase B; Phase C may add a separate rubric file for structured JSON.
- `docs/PROJECT.md` — update status + decisions log after each phase.
- `outputs/phase_b/<split>/` — where B results land; Phase D reads from here.

Good luck. If anything in Phase B runs green, the next concrete milestone is "Phase B summary table in `docs/reports/step4_results.md` (new file) + eval split accuracy numbers by cluster and by level".
