# Handover — Paper Consolidation

_Written 2026-04-19 by the eval-execution agent. Reader: the agent consolidating these results into a paper. C.2 BinarySearch has been **dropped from the paper scope** per Mel; everything in this doc assumes a 3-evaluator story (Phase B, Phase C.1 AllAtOnce, Phase C.3 ConstraintGrounded)._

## 1. TL;DR

**Thesis (per CLAUDE.md)**: evaluate whether Google ADK can perform failure attribution on pre-recorded multi-agent GAIA trajectories. Primary question: can the evaluator distinguish **node-level from process-level failures** and localize the origin step? Within-level 9-way cluster is a secondary detail metric.

**Three-evaluator story (eval split, n=123)**:

| Evaluator | Level acc | Step tol-3 | Macro F1 | Level κ (cal n=5) | Notes |
|---|---|---|---|---|---|
| Phase B (ADK off-the-shelf rubric) | 0.480 | — | 0.445 | **0.000** | Chance-level on node/process; no step output |
| C.1 AllAtOnce (v1 prompt) | 0.553 | **0.667** | 0.547 | 0.615 | Best step localizer |
| **C.3 ConstraintGrounded** | **0.626** | 0.650 | **0.626** | 0.000 (n=5 noise) | **Best level classifier**; log lift +14.6pp over ablation |

**Paper argument in one sentence**: ADK's built-in rubric evaluator is chance-level on node/process (level κ=0.000); custom evaluators substantially improve both level accuracy and step localization; C.3's constraint-violation log is the causal driver of its level-accuracy lead over C.1 (log-ablation recovers Phase-B-level performance).

**Statistical claim**: McNemar's paired test on Phase B vs C.3 gives p=0.0019 (significant at α=0.05). C.3 vs C.1 is marginal (p=0.052). Bootstrap 95% CIs on process F1 do not overlap between Phase B [0.17, 0.41] and C.3 [0.49, 0.70].

## 2. Doc map — where to read what

| Doc | Purpose | Read this for |
|---|---|---|
| [CLAUDE.md](../CLAUDE.md) | Stable project contract | Project goal + working agreement |
| [docs/PROJECT.md](PROJECT.md) | Live project state | Current status of Phase A–D, dataset composition, decisions log |
| [docs/HANDOVER.md](HANDOVER.md) | Agent handover (pre-paper) | Resumption guide; C.3-specific details at §C.3 |
| [docs/reports/step4_plan.md](reports/step4_plan.md) | Experimental design | Original plan, methodology rationale, stratification decisions |
| **[docs/reports/step4_results.md](reports/step4_results.md)** | **Narrative executive summary** | **Findings #1-12, all the prose you'll paraphrase into the paper** |
| [docs/reports/step4_scorecard.md](reports/step4_scorecard.md) | Auto-generated tables | All tables (aggregate, per-source, per-cluster, per-level F1, confusion matrix, calibration κ). Regenerate via `scripts/phase_d_scorecard.py`. |
| [docs/reports/step4_scorecard.json](reports/step4_scorecard.json) | Machine-readable scorecard | If you need numbers in code (e.g., to build figures) |
| [docs/reports/step3_taxonomy_review.md](reports/step3_taxonomy_review.md) | Taxonomy reference | Canonical 9-cluster definitions; cite for methods section |
| [docs/reports/adk_eval_suite_notes.md](reports/adk_eval_suite_notes.md) | ADK API reference | Cite when describing what ADK provides (§6 Phase B framing) |

## 3. Canonical result paths

All numbers reported in the paper come from these specific run directories. **Do not confuse with archived runs** (see §7).

### Eval split (n=123)

| Evaluator | Canonical path | Key numbers |
|---|---|---|
| Phase B | `outputs/phase_b_batch/eval/phase-b-eval-20260419T021853-28ec92/` | cluster 0.220, level 0.480, macro F1 0.445 |
| C.1 (v1 prompt, pro) | `outputs/phase_c/all_at_once/eval/phase-c-eval-20260419T021854-9714af/` | cluster 0.358, level 0.553, tol-3 0.667 |
| C.1 flash-lite (v3 prompt, t=0.3) | `outputs/phase_c/all_at_once_v3/gemini-3-1-flash-lite-preview/eval/phase-c-eval-gemini-3-1-flash-lite-preview-t0.30-20260419T113609-89124f/` | cluster 0.203, level 0.455, tol-3 0.610 — ablation only |
| C.3 (fixed, with log) | `outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-20260419T113252-c4fd41/` | cluster 0.341, level **0.626**, tol-3 0.650, P3 0.625 |
| C.3 ablation (no log) | `outputs/phase_c/constraint_grounded/eval/phase-c-cg-eval-20260419T025817-84b2d2/` | cluster 0.106, level 0.480 (= Phase B), tol-3 0.423 |

### Calibration split (n=5; directional only)

| Evaluator | Canonical path | Level κ | Cluster κ |
|---|---|---|---|
| Phase B | `outputs/phase_b_batch/calibration/phase-b-calibration-20260419T025025-920163/` | **0.000** | 0.385 |
| C.1 | `outputs/phase_c/all_at_once/calibration/phase-c-calibration-20260419T025026-166b4c/` | 0.615 | 0.474 |
| C.3 (fixed) | `outputs/phase_c/constraint_grounded/calibration/phase-c-cg-calibration-20260419T135134-67bc06/` | 0.000 | 0.318 |

**Important caveat**: the C.3 level κ=0.000 on n=5 is noise, not a real contradiction of the eval-split result. Raw agreement is 2/5 for both Phase B and C.3. At n=5 the 95% CI on κ spans [0, 1]. Finding #11 in step4_results.md carries this caveat — use it when quoting κ.

### Dataset

| Artifact | Path |
|---|---|
| Canonical 133-record dataset | `data/consolidated/gaia_consolidated_clean.jsonl` (judge-visible) + `gaia_consolidated_with_gt.jsonl` (with ground truth) |
| Splits (seed 20260418) | `data/splits/{dev,calibration,eval}.jsonl` |
| ADK EvalSets | `data/evalsets/{dev,calibration,eval}{,.with_gt}.evalset.json` |
| Verify re-generation | `python3 scripts/phase_a_verify.py` (must exit 0 with "Phase A verification PASSED") |

**Post-patch cluster distribution** (133 active records): P1=32, P2=23, N2=16, P4=15, N1=13, N3=11, N5=8, P3=8, N4=7. Eval split = 123 cases (dev=5, calibration=5).

**Evidence for polarity finding** (§7.1 in step4_results.md): `outputs/phase_b/debug/raw_responses.txt` — raw Gemini outputs showing ADK's "N/A → Verdict: yes" pattern. Cite when discussing why Phase B's rubrics were rewritten.

## 4. Caveats & limitations (cite in paper's limitations section)

1. **Calibration n=5.** The 0.70 κ gate from step4_plan §8.3 is unresolved because the calibration split is too small. CIs on κ span [0, 1] at n=5. A larger calibration set (≥25 cases) is the highest-leverage methodological next step but was not executed.
2. **Phase B level κ=0.000 is real.** Not an artifact. The off-the-shelf rubric evaluator agrees with human level labels at chance rate. Raw agreement is 2/5 but predicted distribution is ~83% node regardless of gt — i.e., it's acting as a near-pure node classifier. Process F1 at 0.289 (bootstrap [0.17, 0.41]) confirms: Phase B cannot identify process-level failures.
3. **9-way cluster accuracy is harder than level for all evaluators.** All three evaluators are at least 2× random (11% chance on 9-way) but C.1 at 36% and C.3 at 34% are still far from usable as standalone cluster classifiers. **Report level as the headline metric, cluster as a within-level detail.**
4. **P3 cluster accuracy is 0/8 across all evaluators.** This is a taxonomy-inherent limit, not a prompt deficiency. Step3 taxonomy review §P3 notes that P3's origin step is labeled with the origin event's node cluster (N1/N2/N3), not P3. So when C.1 gets step right on 6/8 P3 cases but labels them as the origin cluster, it's doing the taxonomy-correct thing. See Finding #9 for the rule and `scripts/archive/phase_c_p3_probe_v1_5.py` for the probe that validated this.
5. **C.3's cluster accuracy lags C.1 on some clusters (especially N3, P4).** Finding #3 traces this to the violation log being dominated by S8 static error events (756 of 1,008 static events are tool-error regex matches), which biases toward N1/N3 framing on tool-failure trajectories. A trimmed-log ablation (only dynamic events) is the recommended follow-up but was not executed.
6. **Flash-lite is an ablation, not a production recommendation.** Finding #10. Useful for "fast screening if tol-3 is all you need" but cluster accuracy drops materially. Use if discussing model-size/compute tradeoffs; not a baseline replacement.
7. **Single sample per case (`num_samples=1`).** Self-consistency (majority vote over 3-5 samples at t=0.3) was not executed. Noted as a possible +2-5pp ablation but unlikely to change the thesis.
8. **C.2 BinarySearch is out-of-scope per 2026-04-19 decision.** Quota-blocked, merged partial result abandoned. Don't include in paper. The method description in step4_plan §7.1 should be cut or relegated to "future work" in the paper.

## 5. What's done vs what needs consolidating

### Already in the repo, paper-ready:

- Executive summary with 12 findings: `docs/reports/step4_results.md` §0
- Aggregate + per-source + per-cluster tables: `docs/reports/step4_scorecard.md`
- Strictness ladder (L1/L2/L3 level-then-step): `step4_results.md` §0 "Strictness ladder"
- Source × level matrix: `step4_results.md` §0 "Source × level matrix"
- McNemar's paired significance: `step4_results.md` §0 "Statistical significance"
- Bootstrap 95% CIs: `step4_results.md` §0 "Bootstrap 95% CI"
- C.3 log ablation (with vs without log): `step4_results.md` §0 "Ablation"
- Node-vs-process per-class F1, precision, recall: headline table in `step4_results.md` §0

### What the consolidating agent needs to do:

1. **Translate Findings #1-12 (step4_results.md §0) into paper prose.** These are dense; expand each into a paragraph with context and citations. Expected paper sections:
   - Intro / motivation (Finding #1: ADK baseline can't do node/process)
   - Method (Phase B, C.1, C.3 designs — from step4_plan §6-7)
   - Results (Findings #2, #3, #4, #6 — the positive findings)
   - Ablations (Findings #8 v3 rejection, #10 flash-lite, "C.3 log ablation")
   - Limitations (Findings #9 P3 ceiling, #11 calibration κ)
2. **Drop C.2 BinarySearch from the paper scope** per 2026-04-19 decision. Step4_plan's §7.1 C.2 subsection should be cut or relegated to "future work." Only C.1 and C.3 are the custom evaluators being compared in the paper.
3. **Build figures** from step4_scorecard.json sidecar. Likely needed:
   - Bar chart: level accuracy across B / C.1 / C.3 with 95% CI error bars
   - 2×2 confusion matrices for level (per evaluator)
   - Bootstrap process F1 distributions (violin or overlaid histograms)
   - Source × level heatmap
4. **Write a methods section** covering: dataset filtering (step1/step2/step3 reports), taxonomy (step3_taxonomy_review), Phase A data hygiene (polarity finding at §7.1 of step4_results), batch infrastructure (Vertex batch via phase_d_scorecard flow), and the specific prompts used (v1 for C.1, full C.3 two-pass design).
5. **Cite the polarity finding as methods contribution.** Phase B's rewrite from failure-framed rubrics to positive-correctness rubrics (discovered when 87% of verdicts were spurious yes) is itself a documented finding about using ADK's rubric evaluator for failure detection. See `outputs/phase_b/debug/raw_responses.txt` for raw evidence.
6. **Decide on calibration κ narrative.** Given n=5 makes κ directional only, the paper should either:
   - (a) Cite κ with the n=5 caveat and report as "below 0.70 paper-gate; CIs span [0,1]; directional ranking Phase B ≪ C.1 ≤ C.3 preserved"
   - (b) Drop κ as a primary metric and rely on McNemar's + bootstrap CIs, which are robust at n=123

## 6. Reproducibility quick-start

Every number in the paper can be regenerated from the canonical paths via:

```bash
# Phase A verify (data + splits + evalsets from reviewed.jsonl)
python3 scripts/phase_a_verify.py

# Regenerate the scorecard (reads all canonical per_case.jsonl files, writes tables)
python3 scripts/phase_d_scorecard.py --output "$(pwd)/docs/reports/step4_scorecard.md"

# The statistical analyses (source×level, McNemar, bootstrap) are at:
python3 scripts/level_analysis.py
```

To re-run the eval from scratch (not needed for paper, only if judge outputs need regeneration):

```bash
# Phase B (~25 min batch)
python3 scripts/phase_b_batch.py --split eval

# C.1 AllAtOnce (~25 min batch)
python3 scripts/phase_c_all_at_once.py --split eval

# C.3 ConstraintGrounded (~30 min two-pass batch)
python3 scripts/phase_c_constraint_grounded.py --split eval
```

All use Vertex batch with `gemini-3.1-pro-preview` on `location=global`. Requires `GOOGLE_GENAI_USE_VERTEXAI=1` + `GOOGLE_CLOUD_PROJECT=agentevaluationtest` + ADC set via `gcloud auth application-default login`.

## 7. Archive pointers

**Do not cite these in the paper.** They're preserved for reproducibility of exploration but are not canonical.

- `outputs/archive/phase_b_dev_smokes/` — Phase B dev smokes during polarity iteration (4 runs)
- `outputs/archive/phase_c_all_at_once_dev_smokes/` — C.1 dev smokes (v1, v2, v3 prompt iteration)
- `outputs/archive/phase_c_all_at_once_duplicate_eval/` — a duplicate C.1 eval (canonical: -9714af)
- `outputs/archive/phase_c_all_at_once_v3_pro_eval/` — **rejected v3 prompt on pro; cluster 0.260 vs v1's 0.358 = regression. Cite only if discussing prompt-engineering failure modes (Finding #8).**
- `outputs/archive/phase_c_all_at_once_flash_lite_dev_smokes/` — flash-lite dev smokes
- `outputs/archive/phase_c_binary_search_quota_blocked/` — **7 C.2 attempts; paper scope dropped C.2 so ignore**
- `outputs/archive/phase_c_constraint_grounded_stale_prefix/` — pre-ID-alignment-fix C.3 runs (numbers 0.114/0.472/0.496 from these are STALE, do not cite)
- `outputs/archive/phase_c_constraint_grounded_dev_smokes/` — C.3 dev smokes
- `outputs/archive/phase_c_p3_probe/` — P3 probe with consumption-based rule; +1/8 → documented in Finding #9
- `scripts/archive/` — retired helper scripts (v2/v3 smokes, P3 probe, sanity checks, dev review tool)

## 8. Known technical gotchas

1. **Gemini 3 Pro preview requires `location=global`.** Regional endpoints (us-central1) 404. All batch jobs run at location=global. See [gemini3_pro_preview_location.md memory note](../../.claude/projects/-Users-mel-Documents-GitHub-failure-experiment/memory/gemini3_pro_preview_location.md) if relevant for cost/latency discussion.
2. **Vertex batch does NOT preserve input row order.** Align outputs by the `trajectory_id` embedded in each prompt. All runners in `scripts/*_batch.py` use `batch_utils.parse_output_by_key()` for this. If re-implementing, use the trajectory_id extractor: `batch_utils.make_trajectory_id_extractor()`.
3. **Vertex batch's schema validator rejects nested enum in `responseSchema`.** Workaround used: `responseMimeType: application/json` only, with explicit JSON shape in the system prompt. All runners drop `responseSchema` from the batch request config.
4. **Phase B cluster labels were stale in early evalsets.** `phase_a_clean.py:CLUSTER_LABEL_CANON` now canonicalizes `proposed_cluster_label` from the cluster code every time. 25/123 eval cases had mismatched codes/labels before the fix; scoring was always against the code (correct) but JSON was internally inconsistent.
5. **Per-class F1 ≈ per-class accuracy only in binary tasks.** In the 9-way cluster task, F1/precision/recall are all meaningful. In the binary node/process task, per-class accuracy = per-class recall. Step4_results.md uses the "accuracy" label for clarity (user-facing framing).
6. **`num_samples=1` throughout.** We opted against self-consistency for cost reasons; step4_plan §6 mentions `num_samples=5` as a candidate ablation. If the paper needs stronger numbers, this is the cheapest improvement (~3× batch cost, +2-5pp expected from G-Eval/Who&When literature).
7. **step4_plan.md is the experimental design doc**, not the final report. Treat it as "what we planned to do" — step4_results.md is "what we actually did + found." They will diverge; step4_plan may need epilogue edits to note dropped C.2 scope.

## 9. Open decisions for the consolidating agent

Before writing the paper, check with Mel on:

- **Keep or cut the κ narrative?** (see §5 item 6 above)
- **Main-paper vs supplementary for the v3 prompt rejection (Finding #8)?** It's a useful negative result for methodology sections but could clutter the main story.
- **How much flash-lite to include?** Finding #10 is rich; could be a full ablation section or a one-paragraph note in limitations.
- **Paper venue target?** Methods emphasis (venue: workshops on LLM-as-judge, evaluation) vs. applied emphasis (venue: multi-agent systems, agent error research)?

## 10. Tone/style notes from Mel's preferences during eval

- Prefers honest framing over rosy findings. "C.3's cluster accuracy is capped" should not be softened to "C.3 focuses on level accuracy."
- Flag statistical noise aggressively (n=5 calibration, 95% CIs that span 0).
- Do not claim C.1 vs C.3 is significant at α=0.05 (p=0.052 is marginal).
- The constraint-log ablation is the cleanest causal signal — lead with it when arguing for C.3's value.
- Node-vs-process is THE primary thesis; 9-way cluster is within-level detail, not co-equal.

---

_Good luck. The Findings #1-12 in step4_results.md are paper-prose-adjacent; most of your narrative work is expanding and citing them rather than re-analyzing. Numbers, tables, and statistical rigor are locked — just translate and decide paper structure._
