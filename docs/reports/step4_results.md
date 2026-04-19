# Step 4 — Failure Attribution Results

_Last updated: 2026-04-19 (skeleton; tables staged with TBD markers pending eval-split batch completion). Companion docs: [step4_plan.md](./step4_plan.md) (experimental design), [PROJECT.md](../PROJECT.md) (project state), [adk_eval_suite_notes.md](./adk_eval_suite_notes.md) (ADK API reference)._

---

## 1. Executive summary

_To be populated once eval-split batches (Phase B `bklgc0xqq`, Phase C `by4tfrba1`) complete._

Placeholder structure — one paragraph each:
- **Phase B (off-the-shelf rubric baseline)**: [cluster_acc=TBD], [level_acc=TBD], [unassignable=TBD].
- **Phase C.1 (AllAtOnceAttribution, structured JSON)**: [cluster_acc=TBD], [level_acc=TBD], [origin_step_tol3=TBD].
- **Headline finding**: TBD (is the custom-evaluator lift ≥ paper-worthy? does P3 late-symptom fidelity hold?).

---

## 2. Dataset

- 133 active records (154 − 14 DROP − 7 FLAG; see `data/consolidated/gaia_consolidated_reviewed.jsonl`).
- Eval split: 123 records; dev: 5; calibration: 5. Seed `20260418`; manifest at `data/splits/split_manifest.json`.
- Post-patch cluster distribution (eval split): TBD-table-loaded-from-`data/splits/split_manifest.json`.
- All Phase B / Phase C results below reported on the **eval split (n=123)** unless otherwise noted.

---

## 3. Methodology

### 3.1 Phase B — off-the-shelf rubric baseline

- Judge: `gemini-3.1-pro-preview` on Vertex AI (location=`global`; see project memory: `gemini3_pro_preview_location.md`).
- Runner: `scripts/phase_b_batch.py`.
- Per trajectory: one Vertex batch prediction request asking for a yes/no verdict against each of 9 rubrics (one per cluster).
- Rubrics: `data/rubrics/option_b_rubric.json`. **Polarity (revised 2026-04-19)**: rubrics rewritten as *positive correctness properties* so that `Verdict: yes` = the trajectory does NOT exhibit the failure mode. Prediction = argmin over scores (lowest = most "no" = exhibited failure). Ties broken by fixed priority `["N5","N4","N3","N2","N1","P4","P3","P2","P1"]`.
- Why the polarity flip: the original failure-framed rubrics collided with ADK's built-in FINAL_RESPONSE_QUALITY prompt, which is trained to emit `Verdict: yes` on N/A properties. ~87% of verdicts were spurious "yes" and tie-breaking determined every prediction. Raw-response evidence: `outputs/phase_b/debug/raw_responses.txt`. See §7 Findings.
- Batch submission: `responseMimeType: application/json` without `responseSchema` (Vertex batch's proto parser rejects nested-enum schemas; shape enforced by prompt discipline).

### 3.2 Phase C.1 — AllAtOnceAttribution (structured JSON)

- Judge: same as Phase B (`gemini-3.1-pro-preview`, global).
- Runner: `scripts/phase_c_all_at_once.py`.
- Per trajectory: one Vertex batch prediction request; judge returns structured JSON — `{reasoning, evidence_steps, predicted_origin_step, predicted_cluster, predicted_level, confidence, unassignable, unassignable_reason}`.
- Taxonomy + one-sentence cluster signatures embedded in system prompt; full trajectory rendered as numbered step block in user content.
- Chain-of-thought first, then verdict fields — per G-Eval methodology (step4_plan §6).

### 3.3 Why both exist

Phase B quantifies what ADK's default shape gets you for free (closed-world yes/no rubric enumeration; no native step / level / confidence). Phase C drops those structural constraints by writing our own evaluator — the gap is the experimental contrast. See step4_plan §6.0 for framing.

### 3.4 What we did NOT use

- ADK's `RubricBasedFinalResponseQualityV1Evaluator` for the final batch runs. We exercised it first (`scripts/phase_b_rubric_baseline.py`) to produce the polarity-finding diagnostic, then bypassed it for the production batch run because its LLM client doesn't expose a batch hook. The rubric semantics remain faithful.
- Self-consistency (num_samples > 1). Batch mode with Vertex gives sufficient throughput that a single sample per case is enough for the main result; self-consistency is a candidate ablation.
- ADK's built-in prompt template. Polarity-finding (§7) showed it's incompatible with failure-framed rubrics.

---

## 4. Phase B results

### 4.1 Aggregate (eval split, n=123)

| Metric | Value |
|---|---|
| Cluster accuracy | TBD |
| Level accuracy   | TBD |
| Unassignable     | TBD |
| Error rate       | TBD |
| Wall time        | TBD |

### 4.2 By source

| Source | n | Cluster acc | Level acc | Unassignable |
|---|---|---|---|---|
| AEB    | TBD | TBD | TBD | TBD |
| WW-HC  | TBD | TBD | TBD | TBD |
| WW-AG  | TBD | TBD | TBD | TBD |

### 4.3 By cluster

| Cluster | gt n | correct | per-cluster acc | most-confused-with |
|---|---|---|---|---|
| N1 | TBD | TBD | TBD | TBD |
| N2 | TBD | TBD | TBD | TBD |
| N3 | TBD | TBD | TBD | TBD |
| N4 | TBD | TBD | TBD | TBD |
| N5 | TBD | TBD | TBD | TBD |
| P1 | TBD | TBD | TBD | TBD |
| P2 | TBD | TBD | TBD | TBD |
| P3 | TBD | TBD | TBD | TBD |
| P4 | TBD | TBD | TBD | TBD |

### 4.4 Confusion matrix

_Rows = ground truth, columns = predicted._

| gt \ pred | N1 | N2 | N3 | N4 | N5 | P1 | P2 | P3 | P4 | UNASSIGNED |
|---|---|---|---|---|---|---|---|---|---|---|
| N1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| N2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| N3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| N4 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| N5 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| P1 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| P2 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| P3 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| P4 | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

### 4.5 Observations

_One bullet per pattern once numbers land. Questions to answer:_
- Does Phase B's cluster accuracy differ meaningfully from random (1/9 ≈ 11%)?
- Does the positive-correctness polarity fix remove the tie-break artifact seen in dev smoke? (Dev smoke with old polarity: all predictions were N5 due to tie-break. With new polarity: diverse predictions.)
- Which clusters get the best / worst per-class recall? Intuition: P2 (progress misassessment) and P3 (cascading) may collapse into N1 because the judge reads them as "output is wrong → hallucination."
- P3 late-symptom fidelity: when gt=P3, does Phase B correctly map it to P3 or does it fall back to the node-level origin (N1/N2/N3)?

---

## 5. Phase C.1 results

### 5.1 Aggregate (eval split, n=123)

| Metric | Value |
|---|---|
| Cluster accuracy        | TBD |
| Level accuracy          | TBD |
| Origin-step tol-3       | TBD (primary) |
| Origin-step tol-0       | TBD (secondary) |
| Unassignable            | TBD |
| Error rate              | TBD |
| Mean confidence         | TBD |
| Wall time               | TBD |

### 5.2 By source, by cluster

_Same 3-column tables as 4.2 / 4.3, extended with `tol-3` and `tol-0` columns._

| Cluster | gt n | cluster_acc | level_acc | tol-3 | tol-0 |
|---|---|---|---|---|---|
| N1 | TBD | TBD | TBD | TBD | TBD |
| N2 | TBD | TBD | TBD | TBD | TBD |
| N3 | TBD | TBD | TBD | TBD | TBD |
| N4 | TBD | TBD | TBD | TBD | TBD |
| N5 | TBD | TBD | TBD | TBD | TBD |
| P1 | TBD | TBD | TBD | TBD | TBD |
| P2 | TBD | TBD | TBD | TBD | TBD |
| P3 | TBD | TBD | TBD | TBD | TBD |
| P4 | TBD | TBD | TBD | TBD | TBD |

### 5.3 Confusion matrix

_Same layout as 4.4._

### 5.4 Late-symptom fidelity (P3, n=8)

| Metric | Value |
|---|---|
| P3 correctly classified as P3 | TBD / 8 |
| P3 traced to origin step (predicted_step ≤ gt_origin_step + 3) | TBD / 8 |
| P3 predicted at symptom step (predicted_step > gt_origin_step + 5) | TBD / 8 |
| P3 → misclassified as node-level origin cluster (N1/N2/N3) | TBD / 8 |

Confidence bound: 95% CI on p=TBD with n=8 is approximately [TBD, TBD] (Wilson interval).

### 5.5 Confidence calibration

_For use in Phase D; raw numbers here._

| Confidence bucket | n | cluster_acc |
|---|---|---|
| [0.0, 0.5) | TBD | TBD |
| [0.5, 0.8) | TBD | TBD |
| [0.8, 0.95) | TBD | TBD |
| [0.95, 1.0] | TBD | TBD |

Observation: TBD (is confidence calibrated or always ~1.0 regardless of correctness?).

---

## 6. Phase B vs Phase C comparison

| Metric | Phase B | Phase C.1 | Δ |
|---|---|---|---|
| Cluster accuracy | TBD | TBD | TBD |
| Level accuracy   | TBD | TBD | TBD |
| Origin-step tol-3 | n/a | TBD | — (Phase B does not emit origin step) |
| Unassignable rate | TBD | TBD | TBD |

### 6.1 What Phase C adds over Phase B

_One bullet per axis. Pre-registered claims to check:_

1. **Step-level localization** — Phase B cannot produce an origin step natively; Phase C emits one per trajectory. Is `tol-3 > 1/trajectory_length` on average?
2. **Structured output** — Phase C's JSON output includes confidence and reasoning. Does reasoning text correlate with correctness?
3. **Taxonomy-in-prompt vs closed-world rubrics** — Phase C's single-prompt taxonomy may reduce tie-break artifacts seen in Phase B. Does the predicted-cluster distribution become more balanced?

### 6.2 Where Phase C likely does NOT beat Phase B

_Pre-registered:_
- On very long trajectories (expected >50 steps in the eval split), All-at-Once may lose coherence (context pressure). This is the BinarySearchAttribution ablation (future work).
- On trajectories where the failure mode is genuinely ambiguous, Phase C may commit to one cluster while Phase B returns unassignable — the former may look better per-case but worse under κ.

---

## 7. Findings

### 7.1 The positive-correctness polarity fix (Phase B plumbing)

Diagnostic story: initial Phase B runs with failure-framed rubrics produced all-N5 predictions across dev smoke because ADK's built-in prompt treats "property not applicable" as `Verdict: yes`. With 9 rubrics, N/A cases scored 1.0 on ~87% of rubrics; tie-break priority then dictated the prediction.

Evidence: raw LLM responses dumped at `outputs/phase_b/debug/raw_responses.txt` (see `scripts/phase_b_debug_raw.py`). Example (case `WW-AG-d0633230`, N3 rubric): rationale says "agent has no tools, so no tool execution could have failed" — but verdict is `yes`, which our original argmax-on-failure interpretation read as "N3 failure occurred." Correct reading under ADK's prompt: "property is satisfied / N/A."

Fix: rewrite all 9 rubrics as positive-correctness properties (did NOT exhibit failure); prediction = argmin. Validated on dev split: predictions become diverse; 1/5 gt=N1 correctly predicted (plumbing sanity).

This is a reusable insight for anyone trying to adapt ADK's rubric evaluator for failure-mode detection: the prompt template polarity works only with positive-framed properties.

### 7.2 Vertex batch schema-parser limitation

Related plumbing insight: Vertex batch's proto parser rejects `responseSchema` with nested enum values (as of 2026-04-19). Error path misleads (`@ responseSchema.properties[0].properties[1].enum[0]`) but the parse-failure offset is always deep in user content, suggesting a parser over-consume bug. Workaround used: `responseMimeType: application/json` only, schema shape in prompt. Worth a bug report.

### 7.3 Attribution results

_TBD once batches land. Questions on the table:_
- Is Phase C's cluster accuracy meaningfully above 1/9 random? What's the confidence interval?
- Is process-level vs node-level a cleaner distinction than per-cluster? (Expected: yes, ~60% on dev smoke vs 20% cluster.)
- Does P3 late-symptom fidelity work or does the judge collapse to node-level origins?

### 7.4 Source-level asymmetries

_TBD. Expected patterns:_
- AEB (process-heavy, 78%) may favor process-level accuracy.
- W&W-AG (node-heavy) may favor node-level.
- If both evaluators favor their "native" source, the source stratification is doing real work.

---

## 8. Limitations & scope notes

- **Single judge, single sample.** No self-consistency, no model-swap ablation. Both are in step4_plan §9.
- **No calibration κ yet.** Phase D gate (step4_plan §8: "κ ≥ 0.70") is not verified. Calibration run on `--split calibration` is the next action.
- **P3 n=8.** Small-n stress test cluster. CI bounds will be wide.
- **P5 / P6 absent.** Not represented in this dataset; see step3_taxonomy_review.md and step4_plan §8.
- **Phase C.2 (BinarySearch) and C.3 (ConstraintGrounded) not yet run.** This results document covers C.1 AllAtOnceAttribution only. Phases C.2/C.3 + Phase D scorecard will update this doc.
- **Responses not reviewed case-by-case.** A spot-check of 10–20 high-confidence Phase C predictions for reasoning quality is a natural follow-up.

---

## 9. Reproducibility

| Artifact | Path |
|---|---|
| Phase A verifier (regenerates splits + evalsets) | `scripts/phase_a_verify.py` |
| Phase B runner (batch) | `scripts/phase_b_batch.py` |
| Phase C.1 runner (batch) | `scripts/phase_c_all_at_once.py` |
| Shared batch utilities | `scripts/batch_utils.py` |
| Rubrics (positive correctness polarity) | `data/rubrics/option_b_rubric.json` |
| Batch job artifacts | `gs://agenttracebucket/phase_{b,c}/...` |
| Per-case predictions | `outputs/phase_b_batch/eval/<run_id>/per_case.jsonl`, `outputs/phase_c/all_at_once/eval/<run_id>/per_case.jsonl` |
| Summary metrics | `outputs/phase_{b_batch,c/all_at_once}/eval/<run_id>/summary.json` |

Judge model string: `gemini-3.1-pro-preview` | Vertex location: `global` | Project: `agentevaluationtest`.

To reproduce from scratch:
```bash
python3 scripts/phase_a_verify.py                       # regenerates splits + evalsets, asserts 133 records
python3 scripts/phase_b_batch.py --split eval           # Phase B eval
python3 scripts/phase_c_all_at_once.py --split eval     # Phase C.1 eval
```

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-04-19 | Skeleton staged; tables pre-populated with TBD markers pending batch completion. |
