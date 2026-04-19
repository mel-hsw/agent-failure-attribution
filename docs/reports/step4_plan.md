# Step 4 — Failure Attribution Evaluation Plan

_Date: 2026-04-18 · Living planning document. All decisions, debates, and open questions live here. Edit freely and flag changes for discussion. Status markers: [DECIDED] = locked, [OPEN] = needs sign-off, [DROPPED] = explicitly not doing._

---

## 0. Purpose

Design and execute Step 4 of the failure-attribution experiment: run the Google ADK evaluation suite against the 154-record consolidated GAIA dataset and measure whether it can accurately identify the origin step, cluster, and level of each trajectory's failure per the CLAUDE.md three-part match.

This document is the single source of truth for the experimental design. It supersedes looser discussion in chat. Companion reference: [adk_eval_suite_notes.md](./adk_eval_suite_notes.md).

---

## 1. Research question

Can Google's ADK evaluation suite — either out of the box or with modest custom extensions — accurately identify where a multi-agent trajectory first went wrong on GAIA?

Decomposes into three sub-questions from CLAUDE.md:
1. Origin-step match — does the evaluator pick the right step?
2. Cluster match — does the evaluator pick the right failure cluster and level?
3. Late-symptom fidelity — when a failure is process-level, does the evaluator point at the root cause rather than the late symptom?

---

## 2. Current project state (recap)

- Steps 1–3 complete. Taxonomy committed. Dataset finalized.
- 154 consolidated GAIA records in `data/consolidated/gaia_consolidated.jsonl`.
- 9 clusters committed: N1–N5 (node-level, 85 records) and P1–P4 (process-level, 69 records).
- P5 (goal drift) and P6 (causal misattribution) are **absent** from this library. Not fabricating examples.
- Composition: 50 AEB + 29 W&W Hand-Crafted + 75 W&W Algorithm-Generated.
- Source asymmetry: AEB is 78% process-heavy; W&W is 69% node-heavy. Must stratify reporting.
- P3 is the cleanest late-symptom stress test (n=12) — small, report with confidence bounds.

---

## 3. What ADK actually provides (short version)

Full catalogue in [adk_eval_suite_notes.md](./adk_eval_suite_notes.md). Summary:

**Usable as-is:**
- `rubric_based_final_response_quality_v1` — reference-free LLM-as-judge; primary off-the-shelf baseline.
- `final_response_match_v2` — LLM-judge on final answer; useful as failure-detector gate.

**Scaffolding we will build on:**
- `Evaluator` base class (`evaluate_invocations`) for custom attribution evaluators.
- Six callbacks (`before/after_agent`, `before/after_model`, `before/after_tool`) for constraint synthesis and logging.
- Event bus (`session.events`) for validation log assembly.

**Not usable for this project:**
- `response_match_score` (ROUGE-1; too lexical).
- `tool_trajectory_avg_score` (requires expected trajectories we don't have).
- `safety_v1` (unrelated to attribution).

---

## 4. Phase overview

Four phases, each producing a standalone artifact. **B vs C is the central experimental contrast**: B faithfully exercises ADK's built-in rubric evaluator (hardwired yes/no template, closed-world rubric enumeration) to establish what a library user gets for free. C drops those constraints by writing custom `Evaluator` subclasses that emit structured attribution directly and, in one variant, ground judgments in a programmatically-generated constraint-violation log. See §6 for the full framing of why both exist.

| Phase | Produces | Blocks |
|---|---|---|
| A — Adapter | `EvalSet` / `EvalCase` JSON from 154-record JSONL; dataset split field | All of B, C, D |
| B — Off-the-shelf baseline | `rubric_based_final_response_quality_v1` run results on 154 records | Baseline number for lift calculations |
| C — Custom evaluators + constraint layer | Three custom `Evaluator` subclasses + callback-based constraint synthesis | Main experimental comparisons |
| D — Scorecard + reporting | 3-part match metrics, stratified by source and cluster | Paper's results section |

Ablations live in the paper's appendix, not the main results.

---

## 5. Phase A — Adapter

### Scope

Convert `data/consolidated/gaia_consolidated.jsonl` into ADK's `EvalSet` / `EvalCase` format. One `EvalCase` per trajectory. Ground-truth fields ride along as metadata.

### Dataset split [DECIDED — but method open]

A three-way split recorded as a field in the JSONL.

| Subset | Size | Purpose |
|---|---|---|
| dev | ~15 records | Prompt engineering, sanity checks. Stratified: at least one record per cluster; P3 and P4 get two each. |
| eval | ~134 records | Primary scorecard. Judge never sees these at prompt-construction time. |
| calibration | ~5 records | Human-vs-judge κ validation before declaring the evaluator ready. Pulled from eval set after eval set is locked. |

### Few-shot sourcing [DECIDED]

Hybrid approach:
- **Cluster definitions and 1–2 sentence signatures**: lifted from [step3_taxonomy_review.md](./step3_taxonomy_review.md) representative quotes per cluster. Zero dataset cost.
- **Longer exemplars for P3 (cascading) and P2 (progress misassessment)**: lifted from external sources (MAST Appendix D / AgentDebug / AgentRx Appendix E). Zero dataset cost.
- **~5-record internal dev slice**: used only for prompt-scaffolding iteration (does the JSON output parse; does the judge terminate; does the schema validate). Not used as few-shot content.
- Remaining ~149 records → eval + calibration.

Rationale: keeps the entire 154 available for scoring, except the 5 dev records which are held out anyway.

### Data-hygiene pass [DECIDED — new sub-phase]

Before any evaluator runs, strip annotation metadata from every trajectory to prevent leakage into the judge's context.

Risk: if fields like `critical_failure_step`, `critical_failure_module`, `failure_type`, `mistake_step`, or `mistake_reason` are embedded in the trajectory payload (vs kept as sidecar metadata), the judge sees the answer and every reported number is inflated.

Pipeline:
1. Load each record from `gaia_consolidated.jsonl`.
2. Produce a `clean_trajectory` field = trajectory with every annotation-shaped field stripped: `critical_failure_*`, `mistake_*`, `failure_type`, `proposed_cluster`, `proposed_level`, plus any free-text field that heuristically reads as annotator commentary.
3. Grep `clean_trajectory` for annotation keywords (`critical_failure`, `mistake`, "should have", "the agent failed", etc.); flag any trajectory that still matches for manual review.
4. Emit two files:
   - `gaia_consolidated_clean.jsonl` — input to every evaluator. Only `clean_trajectory` is exposed to the judge.
   - `gaia_consolidated_with_gt.jsonl` — scoring-side file with ground truth in metadata, never shown to the judge.
5. Pre-flight assertion before any evaluator run: no ground-truth field appears in any string the judge will see.

### Ground-truth fields to carry into EvalCase metadata

- `ground_truth_origin_step` (int) — from `critical_failure_step` (AEB) or `mistake_step` (W&W).
- `ground_truth_cluster` (str) — from `proposed_cluster`.
- `ground_truth_level` (str) — "node" or "process".
- `source` (str) — "AEB" / "WW-HC" / "WW-AG".
- `symptom_step` (int, optional) — only populated for AEB P3 records where origin and symptom are cleanly separable.
- `split` (str) — "dev" / "eval" / "calibration".

---

## 6. Phase B — Off-the-shelf baseline

### Why Phase B exists (and what it is — and isn't — testing)

Phase B answers a narrow question: **can the ADK evaluation suite perform failure attribution out of the box?** It is not a tuned attribution method. It is a faithful exercise of ADK's default shape, so the gap to Phase C quantifies what a library user actually gets for free.

Two structural constraints are baked into the built-in `rubric_based_final_response_quality_v1` and worth stating plainly, because they shape what Phase B can and cannot say:

1. **The prompt template is hardwired.** It emits `Property / Evidence / Rationale / Verdict: yes|no` per rubric (see [rubric_based_final_response_quality_v1.py:284–323](../../../../Library/Python/3.9/lib/python/site-packages/google/adk/evaluation/rubric_based_final_response_quality_v1.py)). There is no hook to request a structured JSON attribution payload — the evaluator cannot natively emit an origin step, a level, or a confidence. Step-level localization is outside the evaluator's designed output.
2. **Rubric scoring is closed-world.** The judge only answers yes/no against the rubrics you supply. To make the evaluator approximate a multi-class attribution, the user must **enumerate the failure taxonomy as N rubrics** and argmax-yes across verdicts. A trajectory whose true failure doesn't match any enumerated rubric yields all-no and is unassignable.

Phase C exists because these two constraints aren't removable by configuration — they're structural to the built-in. Phase C's custom `Evaluator` subclasses drop the hardwired template (so the judge can emit structured attribution directly), replace closed-world rubric enumeration with a taxonomy-in-prompt + reasoning-first protocol, and — in ConstraintGroundedAttribution — add non-LLM evidence (the violation log) that no built-in evaluator exposes.

### Falsifiable claims Phase B will license

- If Phase B scores well on cluster/level match: ADK's default shape is sufficient for agent-level attribution; the open issue is step localization, not classification.
- If Phase B scores poorly: the built-in evaluator is shaped for *final-response quality grading*, not for *failure attribution* — and the closed-world rubric enumeration is a load-bearing weakness, because any taxonomy the user didn't pre-specify becomes unassignable.

Either outcome is a clean result. Phase B is designed so the answer is interpretable in both directions.

### Method

Configure `rubric_based_final_response_quality_v1` with a taxonomy-derived rubric set and run on the eval split. Per-trajectory budget: 1 judge call × `num_samples` (self-consistency), each call emits yes/no across all rubrics in a single response.

### Rubric design [REVISED — Option B reinterpreted as 9 yes/no rubrics]

**Original plan (now stale, kept for audit trail)**: one structured-JSON rubric emitting `{predicted_origin_step, predicted_cluster, predicted_level, reasoning, evidence_steps, confidence, unassignable_reason}`.

**Actual Phase B**: one yes/no rubric per cluster — 9 total (N1–N5, P1–P4). Predicted cluster = argmax over rubric verdicts, ties broken by a fixed priority order (rarer/node-specific first). Records with all-no verdicts are recorded as `unassignable`. Origin step, confidence, and level are **not** emitted at this phase — those live in Phase C's AllAtOnceAttribution where the output schema fits the evaluator's design.

**Why the reinterpretation**: the built-in prompt template is hardwired to yes/no verdicts as noted in §6.0 above; a single-rubric structured-JSON variant does not compose with the built-in without subclassing it, which would make it no longer "off-the-shelf." The 9-rubric form is the honest off-the-shelf baseline. The structured-JSON schema is preserved in Phase C (AllAtOnceAttribution). Recorded in `data/rubrics/option_b_rubric.json` as `_reinterpretation_note`.

**Best practices baked into the prompt design (from G-Eval, MT-Bench, and 2024–2025 bias literature):**

1. **Chain-of-thought before verdict (G-Eval, Liu et al. EMNLP 2023)** — reasoning emitted before the answer. G-Eval showed this raises Spearman ρ with human judgments from 0.51 → 0.66 on summarization; Who&When independently reports +4–7%.
2. **Structured output with JSON schema** — `{predicted_origin_step, predicted_cluster, predicted_level, reasoning, evidence_steps, confidence, unassignable_reason}`. Use strict JSON mode where available; validation + retry loop for parse failures.
3. **Confidence elicitation** — judge emits a confidence score per prediction. Report confidence-stratified accuracy (high-conf accuracy vs low-conf accuracy) as a calibration check.
4. **Bias mitigations applied:**

| Bias | Applicability to our task | Mitigation |
|---|---|---|
| Position bias | Low — we're doing absolute attribution, not pairwise | If we ever add pairwise comparisons, randomize order |
| Verbosity bias | Low — length isn't on our scoring surface | Structured output removes the lever |
| Self-preference bias | Medium — judge may favor outputs from its own family | Model-swap ablation across Gemini / Claude / OpenAI checks for consistency |
| Lazy parsing on long contexts | High (our trajectories can be 100+ steps) | Strict JSON mode + validation/retry |

5. **Prompt structure** — (i) role preamble defining the task, (ii) taxonomy block with cluster definitions and reasoning signatures from [step3_taxonomy_review.md](./step3_taxonomy_review.md), (iii) JSON output schema specification, (iv) chain-of-thought instruction, (v) trajectory block, (vi) [ConstraintGrounded only] violation log.

**References for paper citation:**
- G-Eval (Liu et al. EMNLP 2023) — CoT + form-filling rubric.
- Judging LLM-as-a-Judge with MT-Bench (Zheng et al. NeurIPS 2023) — foundational biases.
- Justice or Prejudice? (2024) — 12-bias framework (CALM).
- A Survey on LLM-as-a-Judge (Gu et al. 2024) — comprehensive overview.
- Self-Preference Bias in LLM-as-a-Judge (2024) — perplexity-based bias measurement.

### Failure-detector gate

`final_response_match_v2` runs before attribution as a sanity check — confirms the trajectory actually failed. Your dataset is pre-filtered to failures, so this is robustness insurance against mislabeled rows, not a primary filter. Report the gate's agreement rate separately.

### What Phase B produces

A single number per evaluator metric (origin-step match, cluster match, level match) reported on the eval set. This is the ADK off-the-shelf baseline that Phase C's methods are measured against.

---

## 7. Phase C — Custom evaluators + constraint layer

### 7.1 Evaluator roster [DECIDED]

**Three custom `Evaluator` subclasses, not four.** Step-by-Step dropped.

| Evaluator | Strategy | Primary strength |
|---|---|---|
| AllAtOnceAttribution | One-pass judge over full trajectory | Fast, good agent-level accuracy |
| BinarySearchAttribution | Log-bisection with trajectory-level question at each split | Long traces; process-level framing |
| ConstraintGroundedAttribution | Judge reasons over a violation log produced by the callback layer | Root-cause identification; interpretability |

#### Rationale for dropping Step-by-Step

Who&When's numbers:

| Method | Agent-level | Step-level |
|---|---|---|
| All-at-Once | 53.5% | 6.9% |
| Step-by-Step | 36.2% | 16.6% |
| Binary Search | 20.0% | 16.6% |

Step-level ties. Binary search wins on cost (O(log n) vs O(i*/2)). Binary search's judge question ("has the trajectory diverged from the goal by step k?") is more trajectory-aware, which fits process-level attribution better. Step-by-step's advantage is agent-level accuracy, which All-at-Once already covers. So the evaluator roster becomes {fast one-pass, log-bisection, evidence-grounded} rather than {fast, incremental, log-bisection, evidence-grounded}.

**Caveat to note in paper**: Who&When's result is on their multi-agent systems, not GAIA specifically. If Phase C results look surprising, we may revisit step-by-step.

### 7.2 Prompt engineering [DECIDED — based on paper best practice]

**No full-trajectory few-shots.** The papers converge on the MAST style:

- **Cluster definitions + 1–2 sentence reasoning signatures** in the judge's system prompt. Source: Step 3 representative quotes or external-paper exemplars.
- **Longer exemplars reserved for P3 and P2** specifically. P3 needs a "here's what cascading language looks like" example; P2 needs disambiguation from N1. One longer exemplar each. Every other cluster gets definition + signature.
- **Explicit reasoning instruction as top-level directive** — judge emits reasoning before verdict. (+4–7% in Who&When ablations.)
- **Fixed JSON output schema**: `{predicted_origin_step: int, predicted_cluster: str, predicted_level: "node"|"process", reasoning: str, evidence_steps: int[], confidence: float, unassignable: bool}`.
- **ConstraintGrounded skips most few-shots** — leans on the violation log as evidence. (AgentRx's insight.)

> **Clarification**: we are **not** importing AgentRx's data, rules, or constraint language. AgentRx's tasks (τ-bench, Magentic-One customer-service) are different from GAIA and their specific constraints don't transfer. What we port is the **methodology**: "generate a violation log by checking your own domain's constraints against each trajectory, then feed the log to the judge as evidence." The constraints we check are ours (see 7.3 — Tier-1 static + D1–D9 dynamic). The violation-log format is ours. The judge prompt is ours. AgentRx is cited as the paper that validated the evidence-grounded-judging technique.

### 7.3 Constraint layer [DECIDED]

Callback layer supporting ConstraintGroundedAttribution. All constraints emit `ConstraintEvent`s into the session event bus with `{step, constraint_id, verdict, evidence}`. Verdicts: `CLEAR_PASS`, `CLEAR_FAIL`, `UNCLEAR`.

#### Static constraints [REVISED — Tier 1 only]

**Context**: Our 154 records span three source systems (AEB, W&W-HC, W&W-AG) with different tool interfaces and agent definitions. A constraint is only usable if it can be evaluated from the recorded trajectory alone — constraints that require per-system tool schemas or agent role specs aren't realistic for us to encode at scale.

Three-tier audit:

| ID | Constraint | Generic? | Decision |
|---|---|---|---|
| S1 | Tool args match schema | No — needs per-source schema catalog | **DROPPED** |
| S2 | Enum values in allowed set | No — needs schema | **DROPPED** |
| S3 | Tool in agent's declared toolset | No — needs each agent's toolset | **DROPPED** |
| S4 | No repeated identical tool call within 3 steps | **Yes** — pattern-match on (tool_name, args_hash) | **KEEP** |
| S5 | No submit_final_answer before info-gathering | Partially — terminal-action name varies | **KEEP with heuristic detector + confidence flag** |
| S6 | No tool calls after submit_final_answer | Partially — same as S5 | **KEEP with heuristic detector + confidence flag** |
| S7 | Tool-capability mismatch | No — needs per-tool capability knowledge | **DROPPED** |
| S8 | Tool-result error signals (404, 500, "not found") | **Yes** — regex on tool output | **KEEP** |
| S9 | Per-agent step budget | **Yes** — count steps per agent; threshold empirical | **KEEP** |
| S10 | Response format matches role spec | No — needs role specs | **DROPPED** |

**Final Tier-1 static constraint set**: S4, S5 (heuristic), S6 (heuristic), S8, S9.

Impact on ConstraintGrounded: the method leans more heavily on the **dynamic constraints (D1–D9)** than originally drawn. Since D1–D9 are LLM-synthesized per task, they adapt automatically without per-source engineering. The method survives as "mostly-dynamic-constraint-grounded."

Dropped constraints (S1, S2, S3, S7, S10) could be revisited in follow-up work if Phase D results show a specific gap that they would close.

#### Dynamic constraints (per-task, synthesized from GAIA prompt)
| ID | Constraint | Generation | Detects |
|---|---|---|---|
| D1 | Final-answer format matches task-specified format (int / list / string / yes-no) | LLM parses task prompt at run start | N1 variant, MAST task spec |
| D2 | If task references a time frame, trajectory contains verification of temporal validity | LLM extracts temporal constraints | P4 |
| D3 | If task references a specific source, trajectory accesses it | LLM extracts source requirements | P4, N1 |
| D4 | All sub-questions in multi-part tasks addressed | LLM decomposes task into sub-questions | P1, P2 |
| D5 | Task-referenced files/URLs accessed and non-empty | LLM extracts file/URL references | N3, P4 |
| D6 | Task-forbidden actions don't occur | LLM extracts forbidden actions | MAST task spec |
| D7 | Reasoning claims backed by prior tool calls (hallucination check) | Streaming: match claims against tool outputs | N1 |
| D8 | Numerical computations have a verification step | Detected if task involves arithmetic | P4, N2 |
| D9 | Plan enumerated at run start is followed or explicitly revised | Extract plan from first reflection; track adherence | P1, MAST task derailment |

#### Runtime flow [CLARIFIED]

**Two clarifications first:**

1. **Dynamic constraints are per-task, not per-agent.** One LLM call per GAIA task at the start of evaluation synthesizes that task's dynamic-constraint list. Example:
   - Task "According to Wikipedia, what year did X happen?" → synthesizes `{D1: answer must be a year/integer, D3: trajectory must access Wikipedia}`.
   - Task "Calculate the sum of populations in file.csv" → synthesizes `{D1: answer is numeric, D5: file must be accessed, D8: verification step recommended}`.

   The list is shared across whichever agents appear in the trajectory — constraints are about whether the *system as a whole* satisfies the task, not per-agent adherence.

2. **We are not running live ADK agents — we are evaluating pre-recorded trajectories.** Callback language in the plan is a metaphor for *where* in the trajectory each constraint applies; it is not a literal runtime. Implementation = `TrajectoryReplayer` class that walks each recorded trajectory step-by-step and applies static + dynamic constraints at the appropriate positions, producing the violation log. Integrates into ADK via a custom `Evaluator` subclass; the constraint checker underneath is plain Python. (Rejected alternative: fake ADK agent that replays so real callbacks fire — more engineering, no scientific gain.)

**Per-trajectory flow:**

1. Trajectory loaded from `gaia_consolidated_clean.jsonl`.
2. One-shot LLM call synthesizes dynamic-constraint list from the task prompt. Cached.
3. `TrajectoryReplayer` walks the trajectory:
   - At each tool call: Tier-1 static constraints (S4, S8, S9 where applicable) + applicable dynamic constraints (D5, D6).
   - At each model response: S5/S6 heuristic terminal-action checks + dynamic constraints D1, D7, D9.
   - At each tool result: S8 error-signal scan.
4. All constraint evaluations emit `ConstraintEvent`s into an in-memory log with `{step, constraint_id, verdict, evidence}`. Verdicts: `CLEAR_PASS`, `CLEAR_FAIL`, `UNCLEAR`.
5. Replayer produces the violation log artifact.
6. ConstraintGroundedAttribution evaluator runs: feeds judge the clean trajectory + violation log + taxonomy checklist + reasoning prompt. Judge emits structured attribution.

#### Instruction-following coverage

D1, D2, D3, D6, D9 collectively function as the instruction-following metric. No separate IF evaluator needed. Report IF score as a derived metric from the constraint log.

### 7.4 LLM-as-judge model matrix [DECIDED — subject to final pick]

Run on Vertex AI + LiteLLM routing for OpenAI.

| Role | Model | Via |
|---|---|---|
| Big Google | gemini-3-pro-preview or gemini-2.5-pro | Vertex native |
| Small Google | gemini-2.5-flash-lite | Vertex native |
| Big Anthropic | Claude 4 Sonnet (latest available) | Vertex Model Garden |
| Big OpenAI | GPT-4o or GPT-5 | LiteLLM → OpenAI API (OpenAI not in Vertex Model Garden) |
| Small cross-provider | gemini-2.5-flash or Claude Haiku | Vertex native / Vertex Model Garden |

**Scope**: Run full model matrix only on Phase B baseline and on ConstraintGroundedAttribution (best custom method). Other evaluators use the big Gemini default. Rationale: 5 models × 4 evaluators = 20 conditions dilutes signal; two chosen evaluators × 5 models = 10 conditions is tractable.

**Expected finding to test**: Who&When reported reasoning models (o1, R1) *underperform* GPT-4o on failure attribution. Worth testing with gemini-3-pro's thinking mode on vs off if available.

---

## 8. Phase D — Scorecard and reporting

### Three-part match per CLAUDE.md

1. **Origin-step match** — reported at tolerance 0 and tolerance 3.
2. **Cluster match** — exact (9 clusters) and level-only (node vs process).
3. **Late-symptom fidelity** — process-level predictions must point at root, not symptom.

### Tolerance [DECIDED]

- **Tolerance 0**: predicted step == ground-truth step exactly.
- **Tolerance 3**: |predicted step − ground truth| ≤ 3.
- **Primary: tolerance 3.** This is what we headline in the paper.
- **Secondary: tolerance 0.** Reported in results table but not the headline claim.

Rationale: Who&When shows tolerance 0 is brutal (≈17%) while tolerance 5 is ≈43%. Tolerance 3 is a reasonable middle ground and reflects that human annotation itself has step-wobble. Tolerance 0 reported as stress metric.

### Cluster match

- Exact: predicted_cluster == ground_truth_cluster (9-way).
- Level-only: predicted_level == ground_truth_level (2-way).
- Report both. Exact is the hard version; level-only is the "did it at least get the right kind of failure?" measure.

### Late-symptom fidelity [DECIDED]

Computed only on **AEB P3 records** (n=12) where `ground_truth_origin_step` and `symptom_step` are cleanly separable.

Metric: fraction of P3 predictions where `predicted_step ≤ symptom_step − Δ` for some Δ (recommend Δ=3 to match tolerance bound, so it's an "origin not symptom" check with the same fuzziness as origin-step match).

Report with confidence bounds given n=12.

### Stratifications [DECIDED]

Every metric reported three ways:

- Aggregate (all 134 eval records).
- By source (AEB vs W&W-HC vs W&W-AG).
- By cluster (per N1–N5, per P1–P4).

Without stratification, AEB's process-heaviness and W&W's node-heaviness mask method strengths.

### P5 / P6 handling [DECIDED]

- Both included as valid labels in the judge prompt's cluster list.
- If judge predicts P5 or P6, log the prediction but **do not count in primary scorecard** (no ground truth available).
- Report separately as "unassignable predictions" count.
- Analyze: if judge predicts P5/P6 frequently on trajectories labeled P1/P2, flag potential confusion in paper discussion. If judge almost never predicts them, we've validated that our dataset's absence is reflected in judge behavior.

### Calibration check

Before any scorecard numbers are declared trustworthy: compute Cohen's κ between judge and human on the ~5-record calibration set. Bar to clear: κ ≥ 0.70 (below MAST's 0.77 is acceptable since our task is harder, but sub-0.70 means the judge isn't ready).

### Post-execution addendum (2026-04-19) — reporting structure finalized

After Phase D numbers landed, the analysis section of the paper reorganized around CLAUDE.md's core framing: **node-vs-process discrimination is the primary hypothesis**; 9-way cluster accuracy and step localization are supporting dimensions. Concrete reporting structure committed in `docs/reports/step4_results.md`:

1. **Primary scorecard** — node vs process level accuracy + macro F1 + per-class recall/F1/precision. One headline table. C.3 > C.1 > C.3-ablation ≈ Phase B.
2. **Strictness ladder (L1 / L2 / L3)** applied to the level classification, where
   - L1 = level correct only
   - L2 = level correct AND step within tol-3 (headline tolerance)
   - L3 = level correct AND step exact (tol-0)
   One stacked table rather than three. Purpose: show whether the level ranking holds when step fidelity is also required (it does).
3. **Violation-log ablation** — C.3 full vs C.3-ablation at each of L1/L2/L3. Purpose: prove the log is the causal factor in C.3's advantage, not the prompt scaffold. Finding: C.3-ablation L1 accuracy = Phase B L1 accuracy exactly (0.480 both), so the entire +14.6pp C.3 lift over Phase B traces to the log payload. Lift grows with strictness (+14.6pp → +19.5pp → +21.9pp on accuracy from L1 → L3), confirming the log anchors the step as well as the level.
4. **9-way cluster accuracy demoted to supporting evidence.** It does not alter the primary ranking and is reported in §5 of `step4_results.md` alongside the N4/P3 taxonomic-floor caveat. The earlier plan treated cluster as a co-headline; that is superseded.
5. **Statistical support**: McNemar's paired χ² on level accuracy (Phase B vs C.3 p = 0.0019) and bootstrap 95% CIs on process F1 (Phase B upper 0.413 vs C.3 lower 0.486, non-overlapping) — both clean signals at n=123.
6. **Tolerance unchanged**: tol-3 primary, tol-0 stress, per §8 above. Still the case.
7. **Late-symptom fidelity** (P3 n=8 in active set): reported in the scorecard table but not the narrative headline. Finding: P3 cluster accuracy is taxonomy-capped near 0 (separate from P3 step tol-3, which reaches 0.75 on C.1 and 0.50 on C.3). The ≈0 cluster-accuracy floor at P3 is driven by the "origin cluster is the node-level one; P3 labels the downstream propagation pattern" convention noted in step3 taxonomy review.

See `docs/reports/step4_results.md` §0 for the narrative exposition and `docs/reports/step4_scorecard.md` §6–9 for the machine-readable tables that back each claim.

---

## 9. Ablations [DECIDED — appendix only]

Run but report in paper appendix:

1. **Model swap**: gemini-3-pro-preview vs GPT-4o vs Claude 4 Sonnet on Phase B baseline and ConstraintGroundedAttribution.
2. **Constraint log ablation**: run ConstraintGroundedAttribution without violation log injected. If lift < 5 pp, the AgentRx scheme isn't pulling its weight.
3. **Trajectory-length stratification**: bucket eval set into ≤20 / 21–50 / >50 steps. Report each method's accuracy per bucket. This is where All-at-Once is expected to collapse.
4. **Reasoning-mode on/off** on Gemini 3 Pro thinking if available. Who&When's surprising o1/R1 finding replicated or not.

---

## 10. Execution sequencing

| Order | Phase | Notes |
|---|---|---|
| 1 | A — Adapter | Foundational; blocks everything else |
| 2 | B — Baseline | Locks the "off-the-shelf ADK" number |
| 3 | C.1 — AllAtOnceAttribution | Simplest custom evaluator; sanity-check the custom-Evaluator scaffolding |
| 4 | C.3 — Constraint layer (callbacks) | Heaviest engineering; build before the evaluator that depends on it |
| 5 | C.2 — BinarySearchAttribution | Independent; can interleave with constraint layer |
| 6 | C.4 — ConstraintGroundedAttribution | Consumes constraint layer |
| 7 | D — Scorecard | After all predictions are produced |
| 8 | Calibration κ check | Gate before accepting Phase D numbers as trustworthy |
| 9 | Ablations | After primary results are locked |

---

## 11. Things we explicitly decided NOT to do [DROPPED]

- Fabricating P5 / P6 trajectories to fill dataset gaps.
- Per-step classification (CLAUDE.md says trajectory-level origin is sufficient).
- Including Step-by-Step attribution as a separate evaluator (subsumed by All-at-Once + Binary Search).
- Using `response_match_score` (ROUGE-1) — too lexical for GAIA semantic matching.
- Using `tool_trajectory_avg_score` as a primary method (we don't have expected trajectories).
- Using `safety_v1` (unrelated to attribution).
- Separate instruction-following evaluator (covered by D1/D2/D3/D6/D9 in the constraint layer).
- Mixing judge models across stages within a single run (pick one judge per run; swap at the ablation level).
- Full-trajectory few-shot exemplars in judge prompts (use MAST-style definitions + signatures instead).
- Running full 5-model matrix on all 4 evaluators (2 evaluators × 5 models instead).
- Chasing SOTA absolute step-level accuracy (paper contribution is relative lift from ADK baseline).

---

## 12. Open questions requiring sign-off

1. **Rubric design**: [DECIDED — Option B] Structured output with chain-of-thought reasoning. Details in Section 6.
2. **Dev set sourcing**: [DECIDED — Hybrid] Cluster definitions from step3_taxonomy_review.md, longer exemplars from external papers, ~5 internal dev records for prompt scaffolding only, remaining ~149 for eval + calibration. Details in Section 5.
3. **Model matrix — big Google**: [DECIDED — gemini-3-pro-preview].
4. **Judge model for primary runs**: [DECIDED — gemini-3-pro-preview] Used for Phase B baseline and all Phase C non-ablation runs. Swaps only in the model-swap ablation.
5. **Update PROJECT.md**: [DECIDED — yes] To reflect: Phase C = 3 evaluators (Step-by-Step dropped), tolerance-3 primary, data-hygiene pass in Phase A, Step 4 plan documented in step4_plan.md.

---

## 13. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Annotation metadata leaks into trajectory payload, inflating every number | Medium-High | Data-hygiene pass in Phase A; pre-flight assertion that ground-truth fields don't appear in judge-visible strings |
| Judge ignores JSON output schema, breaks scorecard parsing | Medium | Use strict JSON mode where supported; validation + retry loop |
| ConstraintGroundedAttribution costs blow up (many LLM calls for D1–D9 per trajectory) | Medium | Cache per-task dynamic constraint synthesis; run D7 hallucination check in batches per 5 steps, not every step |
| Small n on P3 (n=12) makes late-symptom fidelity number noisy | High | Report with confidence bounds; flag as directional |
| Dataset split accidentally leaks prompt-tuning exemplars into eval set | Medium | Freeze split in JSONL field before any prompt work; CI check that no eval-set record appears in any prompt |
| Gemini 3 models change behavior mid-experiment (API drift) | Low-medium | Pin model version strings; log model version per run |
| Claude 3.7 Sonnet referenced during planning is deprecated 2026-05-11 | Certain | Use Claude 4 line only |
| W&W records don't have separable origin vs symptom, limiting late-symptom metric scope | Certain | Restrict late-symptom fidelity to AEB P3 only; report scope limitation in paper |
| Heuristic terminal-action detector (for S5/S6) mislabels terminal action | Medium | Emit detector confidence; treat low-confidence detections as UNCLEAR rather than PASS/FAIL |
| Self-preference bias in LLM judge (favors own family) | Medium | Model-swap ablation checks consistency across Gemini/Claude/OpenAI; report divergence if any |

---

## 14. Companion documents

- [CLAUDE.md](../../CLAUDE.md) — stable contract.
- [PROJECT.md](../PROJECT.md) — evolving project state.
- [step1_data_cleaning.md](./step1_data_cleaning.md) — dataset provenance.
- [step2_consolidation.md](./step2_consolidation.md) — consolidation pipeline.
- [step3_taxonomy_review.md](./step3_taxonomy_review.md) — taxonomy decisions.
- [adk_eval_suite_notes.md](./adk_eval_suite_notes.md) — ADK reference for paper drafting.

---

## 15. Change log

| Date | Change | By |
|---|---|---|
| 2026-04-18 | Initial version capturing plan through prompt-engineering and model-matrix discussion. | Claude |
| 2026-04-18 | Mel review — flagged data-hygiene need, rubric best-practices request, AgentRx scope, static constraints realism, per-task vs per-agent dynamic synthesis. Resolved open items 1–3, 5. | Mel |
| 2026-04-18 | Resolved Mel's edits: added data-hygiene pass (§5); expanded rubric design with G-Eval / MT-Bench / bias-literature grounding (§6); clarified AgentRx = methodology port only, not data (§7.2); audited static constraints down to Tier 1 only (S4/S5/S6/S8/S9) (§7.3); clarified dynamic constraints are per-task and we evaluate pre-recorded trajectories via TrajectoryReplayer, not live ADK agents (§7.3); updated risk register. Open item 4 still needs confirmation. | Claude |
| 2026-04-18 | Mel confirmed primary judge = gemini-3-pro-preview. All §12 items now DECIDED. Plan ready for Phase A execution. | Mel + Claude |
