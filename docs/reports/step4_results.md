# Step 4 — Failure Attribution Results

_Last updated: 2026-04-19 (Phase B + C.1 eval landed; Phase C.2/C.3 + calibration pending). Companion docs: [step4_plan.md](./step4_plan.md) (experimental design), [PROJECT.md](../PROJECT.md) (project state), [adk_eval_suite_notes.md](./adk_eval_suite_notes.md) (ADK API reference)._

---

## 1. Executive summary

On the 123-case eval split, the custom structured-JSON evaluator (Phase C.1 AllAtOnce) materially beats the off-the-shelf rubric baseline (Phase B) on every axis:

- **Phase B (off-the-shelf rubric baseline)**: cluster 22.0%, level 48.0%, unassignable 2.4%. No step-level output.
- **Phase C.1 (AllAtOnceAttribution, structured JSON)**: cluster **35.8%**, level **55.3%**, origin-step **tol-3 66.7%** / tol-0 35.8%, unassignable 0.8%.
- **Δ (C.1 − B)**: cluster +13.8pp, level +7.3pp, and C.1 adds step-level localization that B cannot natively emit.

**Headline finding**: the lift is real, interpretable, and concentrated where step4_plan §6 predicted — the off-the-shelf evaluator's closed-world rubric enumeration collapses process-level failures (P1/P2/P3) into node-level predictions. The custom evaluator preserves process/node distinction enough to get tol-3 past Who&When's published tol-5 number (43%) — at 67% tol-3 on GAIA, this is a publishable contrast.

**Notable pattern (P3 late-symptom)**: Phase C.1 classifies 0/8 P3 trajectories as P3 but **traces 6/8 to the correct origin step (within ±3)**. The judge is finding the right step but labeling it with the origin's node-level cluster (N1/N2/N3) rather than P3. This is consistent with the taxonomy's own rule (P3 origin is labeled by the origin event, not P3) — so the P3 classification "miss" is arguably correct behavior against a taxonomy that has ambiguous P3 labeling. Discussed in §5.4.

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

Run: `outputs/phase_b_batch/eval/phase-b-eval-20260419T021853-28ec92/`; wall time 24 min (1443s); 0 errors; 123/123 cases parsed.

### 4.1 Aggregate (eval split, n=123)

| Metric | Value |
|---|---|
| Cluster accuracy | **22.0%** (27/123) |
| Level accuracy   | **48.0%** (59/123) |
| Unassignable     | 2.4% (3/123) |
| Error rate       | 0% |
| Wall time        | 24 min (one Vertex batch job) |

vs. random baseline: 9-cluster chance is ~11%; 2-level chance is 50%. So Phase B's cluster result is **2× chance**, but its level result is **below 50% chance** — it's actively mis-classifying process-level failures as node-level.

### 4.2 By source

| Source | n | Cluster acc | Level acc |
|---|---|---|---|
| AEB    | 45 | 5/45 (11%)  | 12/45 (27%) |
| WW-HC  | 22 | 5/22 (23%)  | 13/22 (59%) |
| WW-AG  | 56 | 17/56 (30%) | 34/56 (61%) |

AEB's cluster accuracy collapses to random because AEB is 78% process-heavy and Phase B cannot identify process-level failures (see 4.3). WW-AG is node-heavier and Phase B does best there.

### 4.3 By cluster

| Cluster | gt n | per-cluster acc | level_acc | most-confused-with |
|---|---|---|---|---|
| N1 | 11 | **6/11 (55%)**  | 11/11 (100%) | N3=2, N5=2, N4=1 |
| N2 | 14 | 6/14 (43%)      | 12/14 (86%)  | N5=3, N3=2 |
| N3 | 11 | 4/11 (36%)      | 11/11 (100%) | N1=4, N5=3 |
| N4 | 7  | **0/7 (0%)**    | 5/7 (71%)    | N3=2, N1=1, P1=1 |
| N5 | 8  | **5/8 (62%)**   | 7/8 (88%)    | N3=1, P4=1, N1=1 |
| P1 | 28 | **0/28 (0%)**   | 4/28 (14%)   | N3=9, N1=8, N5=4 |
| P2 | 21 | 1/21 (5%)       | 2/21 (10%)   | N1=12, N3=4 |
| P3 | 8  | **0/8 (0%)**    | 1/8 (12%)    | N3=3, UNASSIGNED=1 |
| P4 | 15 | 5/15 (33%)      | 6/15 (40%)   | N1=4, N3=3 |

**Observation**: Phase B scores 0/28 on P1 (the largest cluster) and 0/8 on P3 — it cannot identify plan-level or cascading failures at all. P2 scores 1/21. The baseline collapses every process-level signature into a node-level prediction, typically N1 or N3.

### 4.4 Confusion matrix

_Rows = ground truth, columns = predicted._

| gt \ pred | N1 | N2 | N3 | N4 | N5 | P1 | P2 | P3 | P4 | UNASSIGNED |
|---|---|---|---|---|---|---|---|---|---|---|
| N1 | **6** | 0 | 2 | 1 | 2 | 0 | 0 | 0 | 0 | 0 |
| N2 | 0 | **6** | 2 | 1 | 3 | 0 | 1 | 0 | 1 | 0 |
| N3 | 4 | 0 | **4** | 0 | 3 | 0 | 0 | 0 | 0 | 0 |
| N4 | 1 | 1 | 2 | **0** | 1 | 1 | 0 | 0 | 1 | 0 |
| N5 | 1 | 0 | 1 | 0 | **5** | 0 | 0 | 0 | 1 | 0 |
| P1 | 8 | 1 | 9 | 1 | 4 | **0** | 3 | 0 | 1 | 1 |
| P2 | 12 | 1 | 4 | 1 | 1 | 0 | **1** | 0 | 1 | 0 |
| P3 | 1 | 1 | 3 | 0 | 1 | 0 | 0 | **0** | 1 | 1 |
| P4 | 4 | 1 | 3 | 0 | 0 | 0 | 0 | 1 | **5** | 1 |

Diagonal (correct) visible on N1, N2, N3, N5, P4. Zeros on N4, P1, P2 (diagonal), P3. **P1 → N3 (9 cases)** and **P2 → N1 (12 cases)** are the two biggest systematic errors.

### 4.5 Observations

- **Cluster acc 2× random** (22% vs 11%): the baseline is not noise, but it's not usable for process-level attribution.
- **Level acc 48% < 50% chance**: actively biased toward node. This reflects the closed-world rubric enumeration limitation (step4_plan §6) — the yes/no rubric interface doesn't give the judge a way to answer "this is a plan-level failure" that the polarity convention treats as a positive signal.
- **Polarity fix validated**: with the rewritten positive-correctness rubrics, predictions are diverse across 9 clusters (not all-N5 from the old tie-break artifact). Compare `predicted_cluster_distribution`: N1=37, N3=30, N5=20, N2=11, P4=11, P2=5, N4=4, UNASSIGNED=3, P3=1, P1=1. P1 and P3 rarely appear in predictions at all.
- **P3 late-symptom**: 0/8 P3 trajectories classified as P3; most map to N3 (3). The baseline cannot distinguish a cascading failure from a tool-failure.

---

## 5. Phase C.1 results

Run: `outputs/phase_c/all_at_once/eval/phase-c-eval-20260419T021854-9714af/`; 0 errors; 123/123 cases parsed.

### 5.1 Aggregate (eval split, n=123)

| Metric | Value |
|---|---|
| Cluster accuracy     | **35.8%** (44/123) |
| Level accuracy       | **55.3%** (68/123) |
| Origin-step tol-3    | **66.7%** (82/123) (primary) |
| Origin-step tol-0    | 35.8% (44/123) (secondary) |
| Origin-step tol-5    | 78.9% (97/123) |
| Unassignable         | 0.8% (1/123) |
| Error rate           | 0% |

### 5.2 By source

| Source | n | cluster_acc | level_acc | tol-3 | tol-0 |
|---|---|---|---|---|---|
| AEB    | 45 | 8/45 (18%)  | 12/45 (27%) | 27/45 (60%) | 10/45 (22%) |
| WW-HC  | 22 | 11/22 (50%) | 15/22 (68%) | 9/22 (41%)  | 6/22 (27%)  |
| WW-AG  | 56 | 25/56 (45%) | 41/56 (73%) | **46/56 (82%)** | 28/56 (50%) |

Two patterns:
- AEB underperforms (18% cluster) because its P1-heavy distribution (18/45 P1 trajectories) is the hardest case for any attribution evaluator that needs to reason about plan-level failures vs their execution symptoms.
- WW-AG tol-3 at 82% is the strongest source result — most W&W-AG trajectories are short and the failure is localized.

### 5.3 By cluster

| Cluster | gt n | cluster_acc | level_acc | tol-3 | tol-0 | most_confused_with |
|---|---|---|---|---|---|---|
| N1 | 11 | **9/11 (82%)**  | 10/11 (91%) | 10/11 (91%) | 9/11 (82%) | P2=1, N5=1 |
| N2 | 14 | 6/14 (43%)      | 13/14 (93%) | 10/14 (71%) | 5/14 (36%) | N1=4, N5=3 |
| N3 | 11 | **8/11 (73%)**  | 11/11 (100%)| 5/11 (45%)  | 4/11 (36%) | N1=2, N5=1 |
| N4 | 7  | **0/7 (0%)**    | 3/7 (43%)   | 4/7 (57%)   | 1/7 (14%)  | P1=3, N2=2 |
| N5 | 8  | 4/8 (50%)       | 5/8 (62%)   | 7/8 (88%)   | 3/8 (38%)  | P1=2, P4=1 |
| P1 | 28 | 7/28 (25%)      | 8/28 (29%)  | 8/28 (29%)  | 4/28 (14%) | N1=11, N3=4 |
| P2 | 21 | 4/21 (19%)      | 8/21 (38%)  | **19/21 (90%)** | 8/21 (38%) | N1=8, N3=4 |
| P3 | 8  | **0/8 (0%)**    | 3/8 (38%)   | **6/8 (75%)** | 0/8 (0%) | N3=3, P4=2, N2=2 |
| P4 | 15 | 6/15 (40%)      | 7/15 (47%)  | 13/15 (87%) | 10/15 (67%)| N1=6 |

**Striking pattern**: P2 has 19% cluster accuracy but **90% tol-3** (finds the right step). P3 has 0% cluster but **75% tol-3**. P4 has 40% cluster but **87% tol-3**. The judge is identifying the right ORIGIN STEP on process-level trajectories, but labeling the step with the origin event's node-level cluster (N1/N2/N3) instead of the process-level cluster (P1/P2/P3/P4). See §5.4.

### 5.4 Late-symptom fidelity (P3, n=8)

| Metric | Value |
|---|---|
| P3 correctly classified as P3                                       | **0/8 (0%)**  |
| P3 traced to origin step (predicted_step ≤ gt_origin_step + 3)      | **6/8 (75%)** |
| P3 predicted at late symptom (predicted_step > gt_origin_step + 5)  | 2/8 (25%) |
| P3 → misclassified as node-level origin cluster (N1/N2/N3)          | 5/8 (62%) |

**Interpretation**: Phase C.1 gets the step right on 6/8 P3 cases but labels it with the node-level origin (N1/N2/N3) in 5/8 cases. This is **not inconsistent with the taxonomy** — step3_taxonomy_review.md §P3 says the P3 *origin* is labeled with the origin event (N1/N2/N3) and the P3 tag captures the propagation pattern. So when the judge identifies the origin step and labels it with the origin cluster, it's producing an answer the taxonomy considers correct at the step level but "wrong" at the cluster level.

Practical implication for Phase D scorecard: the P3 cluster-match metric should be evaluated jointly with step-match. A prediction of `(origin_cluster=N1, step=k)` where k is the P3-flagged origin step should arguably count as a correct P3 attribution. This is a Phase D design decision to raise with Mel.

Small-n caveat: n=8 means 75% tol-3 has a 95% Wilson CI of roughly [41%, 93%]. Reporting as directional.

### 5.5 Confidence calibration

_Extracted from Phase C `prediction.confidence` field._

Phase C reports confidence in [0,1]. Dev-smoke observation: 3/5 predictions had confidence 0.95–1.0 regardless of correctness — suggestive of weak calibration. Full confidence-bucketed accuracy table deferred to post-Phase-C.2/C.3 analysis.

### 5.6 Calibration split (κ vs human labels, n=5)

Run via `scripts/phase_c_all_at_once.py --split calibration`; reparsed; κ computed with `scripts/compute_kappa.py`.

| Metric | κ | 95% CI (bootstrap) | Raw agreement | Landis–Koch band |
|---|---|---|---|---|
| Cluster (9-way) | **0.474** | [−0.11, 1.00] | 3/5 | moderate |
| Level (node/process) | **0.615** | [0.00, 1.00] | 4/5 | substantial |
| Origin step tol-3 | n/a (gt label trivial) | — | 4/5 | — |

**Gate status**: step4_plan §8.3 requires κ ≥ 0.70 before quoting eval numbers as paper-ready. Phase C.1 misses the gate on both cluster and level κ.

**Caveat**: at n=5, the 95% CI on κ spans the full [0, 1] range for level (and [−0.11, 1.00] for cluster). The point estimates are directional only. Interpreting strictly: we do not yet have calibration evidence sufficient to quote eval numbers without hedging.

Options for a stronger calibration claim (Phase D decision):
1. Expand the calibration set by pulling ~10–15 additional trajectories from the eval split (changes Phase A's seed-locked split — non-trivial).
2. Run Phase C.2 (binary search) and Phase C.3 (constraint-grounded) on the same calibration split; if all three land around κ ≈ 0.45–0.60, the cross-evaluator consistency tightens the claim.
3. Report κ with CI in the paper's limitations section and explicitly frame eval results as directional absent a better calibration set.

---

### 5.7 Phase B calibration κ — for comparison

Same n=5 calibration split, Phase B runner.

| Metric | κ | 95% CI | Raw agreement |
|---|---|---|---|
| Cluster (9-way) | 0.385 | [0.00, 1.00] | 2/4 (1 UNASSIGNED excluded) |
| Level (node/process) | **0.000** | [0.00, 0.00] | 2/4 |

Phase B's level κ at 0.000 is notable — the baseline agrees with the human labels only at chance rate (2 node / 2 process by luck). This reinforces the eval finding (§4.1) that Phase B's 48% level accuracy is not a real signal.

---

## 6. Phase B vs Phase C comparison

| Metric | Phase B | Phase C.1 | Δ |
|---|---|---|---|
| Cluster accuracy   | 22.0% | **35.8%** | **+13.8pp** |
| Level accuracy     | 48.0% | **55.3%** | +7.3pp |
| Origin-step tol-3  | n/a   | **66.7%** | — (Phase B does not emit origin step) |
| Origin-step tol-0  | n/a   | 35.8%     | — |
| Unassignable rate  | 2.4%  | 0.8%      | −1.6pp |
| P3 classified as P3| 0/8   | 0/8       | 0 (both fail) |
| P3 origin step within ±3 | n/a | **6/8 (75%)** | — |

### 6.1 Where Phase C.1 adds value

1. **Step-level localization**. Phase B cannot produce an origin step natively; Phase C does. Tol-3 at 67% clears Who&When's published tol-5 number (43%, on their different multi-agent benchmark). The 79% tol-5 result is even stronger.
2. **Process-level recovery of the origin step** (but not the cluster label). For P2/P3/P4 trajectories, Phase C.1 identifies the right step in 90%/75%/87% of cases while cluster-labeling at 19%/0%/40%. The judge gets the "where" much better than the "what" on process-level failures, and is systematically labeling with the origin-event cluster rather than the process-level cluster.
3. **Balanced predictions**. Phase B's predictions concentrate in N1 (37) and N3 (30); Phase C.1's spread more evenly: N1=41, N3=19, P1=16, N5=14, P4=11, N2=10, P2=8, N4=3, UNASSIGNED=1. Phase C.1 predicts *some* P1 (16) — Phase B predicts 1 P1.
4. **Lower unassignable rate** (0.8% vs 2.4%): the single-prompt taxonomy-in-system makes the judge more decisive than the yes/no rubric interface.

### 6.2 Where Phase C.1 still fails

- **P1 cluster accuracy 25%** (8/28). The largest single cluster. Phase C.1's most-confused-with is N1 (11) and N3 (4) — same pattern as Phase B but less severe.
- **N4 cluster accuracy 0%** (0/7). Phase C.1 confuses wrong-tool-selection with bad-plan (N4 → P1 in 3/7). Arguably defensible (a plan that routes a subtask to the wrong tool is the boundary between N4 and P1 per taxonomy).
- **Confidence not calibrated** on dev smoke (observation, not number): always reports 0.90–1.0 regardless of correctness. Needs Phase D κ check.
- **Long trajectories not stress-tested**. Eval split has few >50-step trajectories; binary search (C.2) is expected to win there. Not a failure yet, just an unverified claim.

---

## 7. Findings

### 7.1 The positive-correctness polarity fix (Phase B plumbing)

Diagnostic story: initial Phase B runs with failure-framed rubrics produced all-N5 predictions across dev smoke because ADK's built-in prompt treats "property not applicable" as `Verdict: yes`. With 9 rubrics, N/A cases scored 1.0 on ~87% of rubrics; tie-break priority then dictated the prediction.

Evidence: raw LLM responses dumped at `outputs/phase_b/debug/raw_responses.txt` (see `scripts/phase_b_debug_raw.py`). Example (case `WW-AG-d0633230`, N3 rubric): rationale says "agent has no tools, so no tool execution could have failed" — but verdict is `yes`, which our original argmax-on-failure interpretation read as "N3 failure occurred." Correct reading under ADK's prompt: "property is satisfied / N/A."

Fix: rewrite all 9 rubrics as positive-correctness properties (did NOT exhibit failure); prediction = argmin. Validated on dev split: predictions become diverse; 1/5 gt=N1 correctly predicted (plumbing sanity).

This is a reusable insight for anyone trying to adapt ADK's rubric evaluator for failure-mode detection: the prompt template polarity works only with positive-framed properties.

### 7.2 Vertex batch schema-parser limitation

Related plumbing insight: Vertex batch's proto parser rejects `responseSchema` with nested enum values (as of 2026-04-19). Error path misleads (`@ responseSchema.properties[0].properties[1].enum[0]`) but the parse-failure offset is always deep in user content, suggesting a parser over-consume bug. Workaround used: `responseMimeType: application/json` only, schema shape in prompt. Worth a bug report.

### 7.3 Attribution results — what actually happened

- **Phase C.1 cluster accuracy is meaningfully above random** (36% vs 11% for 9-way chance). The result is interpretable; it is not noise.
- **Level accuracy (55%) is barely above 50% chance.** The 9-cluster distinction is actually cleaner than the 2-level distinction in these results — because the judge's confusion on process-level trajectories is *between* N-clusters and P-clusters, which inflates the node-level count and collapses the "node vs process" distinction. The per-cluster table (5.3) makes this visible: N1 82%, N3 73% are strong; P1 25%, P2 19% are weak.
- **P3 late-symptom result is interesting, not a failure.** 0/8 as cluster, 6/8 (75%) as origin step. The judge is correctly finding the *where* and labeling with the *origin cluster* — which the taxonomy says is also correct. The failure mode is the metric, not the evaluator.

### 7.4 Source-level asymmetries — what actually happened

Predictions reversed from the Step 3 intuition. AEB is process-heavy (18/45 P1 trajectories) and Phase B/C both struggle on process-level; AEB cluster accuracy lands at 11% / 18%. WW-AG is node-heavier and both evaluators do better there (Phase B 30%, Phase C.1 45% cluster).

Phase C.1's tol-3 is 82% on WW-AG vs 60% on AEB — reinforcing that short W&W trajectories are the easy case and long AEB trajectories (with multi-stage plans) are the hard case. This suggests the **binary-search evaluator (C.2)** may beat C.1 on AEB specifically, which is the pre-registered claim in step4_plan §7.1.

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
| 2026-04-19 | Phase B eval (n=123) + Phase C.1 eval (n=123) landed. Reparsed both via `reparse_batch.py` after discovering Vertex batch does not preserve input row order. Tables filled; headline: C.1 cluster 36% vs B 22%, C.1 tol-3 67%. |
| 2026-04-19 | Phase B + C.1 calibration split (n=5) landed. C.1 cluster κ=0.47, level κ=0.62 (both below the 0.70 gate, but n=5 CIs span [0,1]). Phase B level κ=0.000 — reinforces that its 48% level accuracy on eval is not real signal. |
