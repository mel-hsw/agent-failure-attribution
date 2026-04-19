# Project State — Failure Attribution on GAIA

_Last updated: 2026-04-19 (Phase B polarity fix + Vertex eval run kicked off). This is the evolving project doc; it changes as the experiment progresses. For the stable high-level contract see `../CLAUDE.md`._

## Current status

- **Step 1 (data cleaning)**: complete — see `reports/step1_data_cleaning.md`.
- **Step 2 (consolidation)**: complete — see `reports/step2_consolidation.md`.
- **Step 3 (taxonomy review)**: complete — see `reports/step3_taxonomy_review.md`. Decisions recorded below.
- **Step 4 (run Google ADK eval suite)**:
  - Phase A: complete and re-verified against 133-record active set (`scripts/phase_a_verify.py` exits clean).
  - Phase B: dev smoke green; full eval split (123 cases) running on Vertex AI + `gemini-2.5-pro` with `num_samples=5`, `parallelism=8` (background job). Rubrics rewritten to positive-correctness polarity after diagnosing that ADK's built-in prompt treats "property not applicable" as `Verdict: yes` (see 2026-04-19 decision rows).
  - Phase C: three evaluators implemented (C.1 `phase_c_all_at_once.py`, C.2 `phase_c_binary_search.py`, C.3 `phase_c_constraint_grounded.py`) plus `trajectory_replayer.py` for Tier-1 static constraints. All three default to `gemini-3.1-pro-preview` on Vertex `location=global` (matches Phase B batch default). Ready for live smoke + eval runs.
  - Phase D: pending. Full design in `reports/step4_plan.md`. ADK reference notes in `reports/adk_eval_suite_notes.md`.

## Consolidated dataset

- Source (pre-patch): `../data/consolidated/gaia_consolidated.jsonl` (154 records)
- Cluster-review patches: `../data/consolidated/cluster_review_patch.jsonl` (49 patches: 28 cluster reassignments, 14 DROP, 7 FLAG)
- Reviewed dataset: `../data/consolidated/gaia_consolidated_reviewed.jsonl` (154 records, all patches applied; includes `review_status`, `review_original_cluster`, `review_reason` fields)
- Per-record classifications: `../data/consolidated/failure_classifications.csv` (154 rows, same extra review fields)
- Composition (pre-patch): 50 AgentErrorBench + 29 Who_and_When Hand-Crafted + 75 Who_and_When Algorithm-Generated.
- Filtering rules applied: GAIA only (dropped 56 AssistantBench rows); W&W dedup with Hand-Crafted winning (dropped 20 Algorithm-Generated duplicates); 4 ambiguous records dropped per Mel's Step 3 decision.

### Post-patch eval-ready dataset (Phase A output)

- Clean (judge-visible): `../data/consolidated/gaia_consolidated_clean.jsonl` (134 records)
- Scoring-side: `../data/consolidated/gaia_consolidated_with_gt.jsonl` (134 records, annotations in `gt` block)
- Splits: `../data/splits/` — dev (5), calibration (5), eval (124); seed 20260418; manifest in `split_manifest.json`
- ADK EvalSets: `../data/evalsets/{dev,calibration,eval}.evalset.json` (judge-visible) and `*.with_gt.evalset.json` (scoring-side)

Dataset shrank 154 → 134 because 14 DROP + 6 FLAG records from cluster review were removed (outcome-only reasoning or step-0 mis-annotations). The DROP count includes 1 previously flagged for removal (see 2026-04-19 decision row).

## Failure taxonomy (current working version)

The taxonomy emerged from reading every reasoning signature across the 154 records. Node vs process is the core split; the specific clusters below are data-driven and may evolve.

### Node-level clusters (single-step, localized)

| ID | Cluster | Test approach |
|---|---|---|
| N1 | Hallucination / factual fabrication | Requires ground-truth comparison |
| N2 | Code implementation bug | Can be validated by executing the code |
| N3 | Tool execution or retrieval failure | Detectable from tool output/error signals |
| N4 | Wrong tool selection | Requires task-goal vs tool-purpose comparison |
| N5 | Invalid tool parameters / input | Schema validation |

N1 and N2 are kept separate because the validation method differs — N2 is runtime-verifiable, N1 requires a reference answer.

### Process-level clusters (multi-step, structural or cumulative)

| ID | Cluster |
|---|---|
| P1 | Improper task decomposition / bad plan |
| P2 | Progress misassessment |
| P3 | Cascading error (explicit propagation) |
| P4 | Constraint ignorance / unchecked assumption |

### Categories not currently represented in the dataset

- **Long-horizon goal drift / objective divergence** — zero records.
- **Causal misattribution** — zero records.
- Scoring the eval on these two will require additional data from outside this library.

## Cluster distribution

### Pre-patch (154 records, Step 3 output)

| Level | Count | % |
|---|---|---|
| Node-level | 85 | 55% |
| Process-level | 69 | 45% |

| Cluster | Count |
|---|---|
| N1 Hallucination / factual fabrication | 33 |
| P1 Improper task decomposition | 33 |
| N2 Code implementation bug | 24 |
| P2 Progress misassessment | 17 |
| N3 Tool execution or retrieval failure | 15 |
| P3 Cascading error (explicit propagation) | 12 |
| N4 Wrong tool selection | 9 |
| P4 Constraint ignorance / unchecked assumption | 7 |
| N5 Invalid tool parameters / input | 4 |

### Post-patch — Phase A output (134 records, first pass)

| Level | Count | % |
|---|---|---|
| Node-level | 58 | 43% |
| Process-level | 76 | 57% |

| Cluster | Count |
|---|---|
| P1 Improper task decomposition | 30 |
| P2 Progress misassessment | 24 |
| N1 Hallucination / factual fabrication | 16 |
| N2 Code implementation bug | 15 |
| P3 Cascading error (explicit propagation) | 12 |
| N3 Tool execution or retrieval failure | 11 |
| P4 Constraint ignorance / unchecked assumption | 10 |
| N4 Wrong tool selection | 8 |
| N5 Invalid tool parameters / input | 8 |

### Post-full-review (133 active records — canonical)

Full record-by-record review of all 154 records completed 2026-04-19. 11 additional patches applied (9 cluster reclassifications + 1 FLAG override to N3 + 1 new FLAG). Active dataset is 133 records (154 − 14 DROP − 7 FLAG). **Phase A outputs need to be regenerated** to reflect the 133-record active set (one record shifted from active to FLAG since Phase A was cut).

| Level | Count | % |
|---|---|---|
| Node-level | 55 | 41% |
| Process-level | 78 | 59% |

| Cluster | Count |
|---|---|
| P1 Improper task decomposition | 32 |
| P2 Progress misassessment | 23 |
| P4 Constraint ignorance / unchecked assumption | 15 |
| N2 Code implementation bug | 16 |
| N1 Hallucination / factual fabrication | 13 |
| N3 Tool execution or retrieval failure | 11 |
| P3 Cascading error (explicit propagation) | 8 |
| N4 Wrong tool selection | 7 |
| N5 Invalid tool parameters / input | 8 |

Key shifts from first-pass patch to full review: N1 fell from 16 → 13 (3 more N1 reclassified as P4 — agents ignoring constraints or making explicit assumptions, not fabricating); P4 rose from 10 → 15; P3 fell from 12 → 8 (4 P3 labels corrected to origin-step cluster: 2×P1, 1×N2, 1×N1). The process-level share rose further to 59% as more failures were correctly traced to planning/constraint failures rather than node-level errors.

The level balance shifted from node-heavy (55% pre-patch) to process-heavy (59% post-full-review). The primary drivers: W&W "hallucination" annotations that were actually misinterpretation of tool output (N1 → P2); fabrication annotations where the agent acknowledged it was assuming rather than asserting (N1 → P4); and cascade labels where the critical step was the origin error, not a propagation step (P3 → origin cluster).

## Decisions log

| Date | Decision | Rationale |
|---|---|---|
| 2026-04-19 | Phase C evaluators (C.1/C.2/C.3) all default to `gemini-3.1-pro-preview` on Vertex `location=global` | Matches the model string already in use by `phase_b_batch.py` and `phase_c_all_at_once.py`; consistent judge across batch-capable evaluators. Note: `gemini-3.1-pro-preview` is only served from the `global` location (memory entry `gemini3_pro_preview_location.md`). If the project's allowlist lapses, fall back to `gemini-2.5-pro` via `--judge-model`. |
| 2026-04-19 | Phase B judge is Vertex `gemini-2.5-pro` (not Gemini 3 Pro) | `gemini-3-pro-preview` and `gemini-3.1-pro-preview` exist in the publisher catalog but `projects/agentevaluationtest` is not allowlisted for generation — returns 404. Allowlist request submitted separately; if access lands, re-run as a Pro-3 ablation. `gemini-2.5-pro` GA works and was the original handover suggestion. |
| 2026-04-19 | Phase B rubrics rephrased as positive-correctness properties; runner flipped to argmin | ADK's built-in `FINAL_RESPONSE_QUALITY` prompt has hardcoded few-shot examples that emit `Verdict: yes` when a property is "not applicable". With failure-framed rubrics ("exhibits N2 failure"), N/A cases were scored 1.0 across ~87% of rubrics — tie-break priority dictated every prediction. Rewording to "did NOT exhibit N2 failure" inverts the polarity so `Verdict: no` = failure exhibited. Raw LLM responses dumped at `outputs/phase_b/debug/raw_responses.txt`; diagnostic runner at `scripts/phase_b_debug_raw.py`. |
| 2026-04-19 | Phase A re-run and verified at 133-record active set | `phase_a_verify.py` now exits clean: 133 records, all 9 clusters in eval, splits disjoint, no annotation leakage. Handover's earlier "134-record" state is stale. |
| 2026-04-19 | Full record-by-record review completed; 11 additional patches applied | All 154 records now have individual step-content analysis. 49 total patches in `cluster_review_patch.jsonl`. Active dataset is 133 (154 − 14 DROP − 7 FLAG). Phase A outputs need to be regenerated from `gaia_consolidated_reviewed.jsonl`. |
| 2026-04-19 | FLAG records (6, then 7 after full review) removed from eval set alongside DROP records (14) | FLAG records have either step-0 mis-annotations or step content not present in stored history; neither can be scored by any step-localization evaluator. Dataset size: 154 → 133. |
| 2026-04-19 | Dev/calibration splits seeded at 20260418; WW-HandCrafted absent from the first 10 picks | Stratification favors larger strata first to keep rare clusters intact in eval. Hand-Crafted (n=23) is smallest and didn't round-robin into dev/cal; acceptable because dev is for prompt iteration and calibration is for kappa-on-a-small-set, not for source-level generalization. If Phase D kappa looks source-biased, re-seed. |
| 2026-04-18 | Phase C will run 3 custom evaluators, not 4 | Step-by-Step dropped; its step-level accuracy ties Binary Search (16.6%) while Binary Search has lower cost and more trajectory-aware framing. Its agent-level advantage is covered by All-at-Once. See step4_plan.md §7.1. |
| 2026-04-18 | Origin-step match reports tolerance-3 as primary, tolerance-0 as secondary | Who&When shows tolerance-0 is brutal (≈17%) while tolerance-5 is ≈43%; tolerance-3 reflects human annotation wobble. See step4_plan.md §8 / Phase D. |
| 2026-04-18 | Phase A includes a data-hygiene pass to strip annotation metadata from trajectories | Prevents leakage of `critical_failure_*` / `mistake_*` / `failure_type` fields into judge context. Emits `gaia_consolidated_clean.jsonl`. See step4_plan.md §5. |
| 2026-04-18 | Static constraints for ConstraintGroundedAttribution limited to Tier 1 (S4, S5-heuristic, S6-heuristic, S8, S9) | Other static constraints require per-source tool schemas / agent role specs we don't have. Method leans on dynamic constraints (D1–D9) as the load-bearing piece. See step4_plan.md §7.3. |
| 2026-04-17 | Keep N1 and N2 as separate clusters | Test methodology differs: N2 is runtime-verifiable by executing the code; N1 requires a ground-truth answer to detect fabrication. |
| 2026-04-17 | Drop the 4 ambiguous records ("answer incorrect" / "reasoning is wrong" with no further detail) | Reasoning text too thin to classify or to score the eval against. |
| 2026-04-17 | Keep P4 (constraint ignorance) as its own cluster | Data suggested it clearly but it doesn't fit any of the CLAUDE.md example categories. |
| 2026-04-17 | Accept that P5 (goal drift) and P6 (causal misattribution) are not represented | No trajectories in this library exhibit either; don't fabricate examples. |
| 2026-04-16 | W&W dedup policy: Hand-Crafted wins on UUID collisions | Hand-annotated is more likely to be correct than algorithm-generated. |
| 2026-04-16 | Filter to GAIA only (drop AssistantBench) | Canonical benchmark scope for this experiment. |

## Data sources

- **AgentErrorBench** (`../data/AgentErrorBench/`) — 50 labeled GAIA trajectories across GPT-4o, Llama3.3-70B-Turbo, and Qwen3-8B. Uses standardized `critical_failure_step` + `critical_failure_module` + per-module `failure_type`.
- **Who_and_When** (`../data/Who_and_When/`) — Two Hugging Face splits (Algorithm-Generated: 126 rows; Hand-Crafted: 58 rows). Mix of GAIA and AssistantBench. Free-text `mistake_reason`, no standardized failure-type column.

## Reference papers (`../paper/references/`)

- `2503.13657v2.pdf` · `2505.00212v3.pdf` · `2509.25370v1.pdf` · `2602.02475v1.pdf`

## Next steps

Full Step 4 plan lives in `reports/step4_plan.md`. At a high level:

1. **Phase A — Adapter**: ✅ complete at 133 records (verified 2026-04-19 via `scripts/phase_a_verify.py`).
2. **Phase B — Off-the-shelf baseline**: 🏃 eval split (123 cases) running on Vertex `gemini-2.5-pro`, `num_samples=5`, `parallelism=8`. Results land in `outputs/phase_b/eval/{per_case.jsonl, summary.json}`. Once done: also run `--split calibration` for Phase D κ calibration.
3. **Phase C — Custom evaluators + constraint layer**: Three custom `Evaluator` subclasses — AllAtOnceAttribution, BinarySearchAttribution, ConstraintGroundedAttribution — plus TrajectoryReplayer constraint checker (Tier-1 static + D1–D9 dynamic).
4. **Phase D — Scorecard**: Three-part match per CLAUDE.md (origin step, cluster/level, late-symptom fidelity). Stratified by source and cluster. Calibration κ check before numbers are trusted.
5. **Ablations (appendix)**: model swap, constraint-log ablation, trajectory-length stratification, reasoning-mode on/off.

Pay special attention to P3 (explicit cascading, n=12) as the late-symptom stress-test cluster.

Decide post-Phase-D whether to pursue additional data for P5 (goal drift) and P6 (causal misattribution), or scope those out of the current paper.
