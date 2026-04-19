# Evaluating Failure Attribution in Multi-Agent GAIA Trajectories

_Working draft · last updated 2026-04-18 · internal; target: workshop / conference submission_

**Author:** Mel Wong (CMU)
**Status:** Preliminary. Dataset construction (Steps 1–3) and cluster-review verification are complete. Evaluation methodology (Step 4) is fully designed and documented in `docs/reports/step4_plan.md`; it is presented in Section 6. Section 8 (results) is scaffolded but not yet populated — the evaluation suite has not been run against the consolidated dataset at the time of writing.

---

## Abstract

Agentic systems built on large language models fail in ways that are hard to attribute: executions are long-horizon, probabilistic, and interleaved with noisy tool output. Where a single-turn chatbot either produces a right answer or a wrong one, a multi-agent trajectory of 30+ steps can contain a "wrong" step 5 whose consequences only become visible at step 27. A correct *answer-level* evaluation tells you the agent failed; it does not tell you *where* the failure entered the trajectory.

We are evaluating whether the Google ADK evaluation suite can perform this harder task — **failure attribution**, i.e. locating the earliest step at which an error enters a multi-agent trajectory — on the GAIA benchmark. As a prerequisite, we consolidate two existing annotated trajectory libraries (AgentErrorBench and Who_and_When) into a single GAIA-only dataset of 154 labeled trajectories, verify every per-record cluster assignment through a row-by-row review pass, and standardize their heterogeneous failure-type labels into a two-level, nine-cluster taxonomy derived directly from the data. We define a three-part scoring protocol that checks (i) origin-step match, (ii) cluster match under the unified taxonomy, and (iii) absence of "late-symptom bias" — the tendency of evaluators to blame the step at which the symptom becomes visible rather than the step at which the error was introduced.

Around that protocol we design an evaluation pipeline with four phases: a dataset adapter that converts the consolidated JSONL into ADK's `EvalSet`/`EvalCase` format with a data-hygiene pass that strips annotation metadata before any judge sees a trajectory; an off-the-shelf baseline using ADK's `rubric_based_final_response_quality_v1` configured with a nine-cluster attribution rubric; three custom `Evaluator` subclasses (All-at-Once, Binary-Search, Constraint-Grounded) layered on a constraint-synthesis layer of five static checks and nine per-task dynamic checks; and a stratified scorecard that reports origin-step match at tolerance 0 and tolerance 3, exact and level-only cluster match, and a late-symptom fidelity score restricted to AgentErrorBench P3 records where origin and symptom steps are cleanly separable.

Preliminary dataset analysis shows structural asymmetries between the two source libraries that have direct implications for any attribution evaluator: AgentErrorBench trajectories are dominated by process-level failures (78% process), while Who_and_When trajectories are dominated by node-level ones (69% node). Two failure categories commonly listed in the literature — long-horizon goal drift and causal misattribution — are absent from the consolidated library. These observations shape both the evaluation design and the interpretation of whatever results the Google ADK suite produces.

## 1. Introduction

Multi-agent frameworks (AutoGen, Magentic-One, MetaGPT, and their kin) increasingly run long, tool-using workflows on tasks drawn from benchmarks like GAIA. Practitioners and researchers alike need to know not only *whether* these systems succeed but *why* they fail, because (a) the same final wrong answer can arise from very different upstream causes, and (b) the corrective intervention — prompt edit, tool fix, memory architecture change, orchestration-level repair — depends entirely on which cause.

The narrow technical problem we address in this paper is **failure attribution on a trajectory**: given the full history of an agentic trajectory that ended in an incorrect answer, identify the earliest step at which the failure was introduced. We refer to this step as the **failure origin**. Trajectory-level attribution of a single origin is the scope here; we do not require per-step classification.

### 1.1 Why this is hard

Failures split naturally into two regimes:

- **Node-level failures** are localized to a single step and are, in principle, visible at that step. A tool is called with malformed arguments; a fact is fabricated; the wrong tool is chosen.
- **Process-level failures** are structural or cumulative. An early misreading of the task, a memory summary that drops key detail, an unverified assumption passed between agents — each individual step looks locally reasonable, but the error compounds and surfaces only much later.

For process-level failures, the symptom step and the origin step can be many turns apart. A naive evaluator that reads the trajectory and points at the step *where the answer obviously went wrong* will systematically attribute process-level failures to their late symptoms. We call this the **late-symptom bias** and treat it as a first-class evaluation criterion: any attribution suite worth the name must resist it.

### 1.2 Contributions

1. **A consolidated, GAIA-only, failure-attribution benchmark of 154 labeled trajectories** derived from AgentErrorBench and Who_and_When, with unified schema and normalized labels, followed by a row-by-row verification pass against the taxonomy's extended boundary definitions.
2. **A two-level, nine-cluster failure taxonomy** derived inductively from the labels and free-text reasoning present in the two libraries. Clusters are preserved when data supports them, even if they don't map onto a pre-existing category in the literature.
3. **A three-part scoring protocol** for evaluating any failure-attribution method, with late-symptom bias as an explicit sub-score.
4. **An end-to-end ADK-based evaluation methodology** comprising a data-hygiene pass, an off-the-shelf rubric baseline, three custom attribution evaluators, and a constraint-synthesis layer (five static + nine per-task dynamic constraints) that produces a violation log consumed by an evidence-grounded judge.
5. **Preliminary data analysis** that surfaces structural asymmetries between the two source libraries, identifies the hardest cases (explicit cascading errors, cluster **P3**), and flags two expected failure modes (goal drift, causal misattribution) that are not represented in the consolidated data and therefore cannot be scored on here.

### 1.3 Scope and non-goals

We do not train or modify the system under test. We do not attempt per-step labeling of every step in every trajectory; the consolidated library is single-origin by construction. We do not claim the nine clusters are a universal taxonomy of agentic failure — they are the clusters the data in this library supports.

## 2. Related Work

### 2.1 Multi-agent frameworks and benchmarks

GAIA [ref-2503.13657] is the canonical benchmark we use for task grounding: questions require multi-hop research and tool use, and current leading multi-agent systems succeed on roughly half of the set, leaving a large population of failure trajectories to study. Our trajectory sources were both produced by running multi-agent architectures — AutoGen / Magentic-One variants and similar — against GAIA.

### 2.2 Annotated failure libraries

Two existing annotation efforts feed this work:

- **AgentErrorBench** [ref-2505.00212] provides trajectory-level failure labels across three underlying models (GPT-4o, Llama3.3-70B-Turbo, Qwen3-8B) with a standardized module-and-type taxonomy: failures are tagged with `critical_failure_module` (planning / action / memory / reflection / system) and a module-specific `failure_type`.
- **Who_and_When** [ref-2509.25370] contributes two splits: a **Hand-Crafted** split of 58 trajectories and an **Algorithm-Generated** split of 126 trajectories. Both splits attach a `mistake_step`, `mistake_agent`, and a free-text `mistake_reason` to each failure but do **not** standardize the failure-type vocabulary — this is the primary cleaning task our consolidation has to solve.

_[TODO: expand this subsection with proper citations and with a paragraph on how these two libraries construct their ground truth; the four referenced papers in `paper/references/` should be read and summarized before external submission.]_

### 2.3 Why a new consolidation was needed

Neither library alone is sufficient: AEB's 50 GAIA trajectories are too few to stress-test cross-cluster generalization; Who_and_When covers more GAIA questions but has no standardized label vocabulary. Combining them produces a larger, more diverse labeled set, but only if the two very different labeling schemes can be mapped onto a common taxonomy — the subject of Section 4.

## 3. Problem Formulation

Let a trajectory $\tau$ be a sequence of steps $s_1, s_2, \ldots, s_T$, where each step records an agent's action, tool call, observation, and reasoning. Assume $\tau$ is a failure trajectory — i.e. the final answer is incorrect.

The failure-attribution task is a mapping

$$f: \tau \mapsto (s^\ast, c^\ast)$$

where $s^\ast \in \{1, \ldots, T\}$ is the predicted failure-origin step and $c^\ast \in \mathcal{C}$ is the predicted failure cluster, for $\mathcal{C}$ the cluster vocabulary defined in Section 4.

**Ground-truth** for each trajectory is a pair $(s_{gt}, c_{gt})$ derived from the annotation in the source library (Section 5.1).

**Scoring** of a predicted $(s^\ast, c^\ast)$ against ground truth proceeds along three axes:

1. **Origin-step match:** $s^\ast = s_{gt}$. An exact-match scoring; we also report near-match ($|s^\ast - s_{gt}| \le 1$) for error tolerance.
2. **Cluster match:** $c^\ast = c_{gt}$. Both the cluster ID and the level (node vs process) must agree; a predicted N3 against a ground-truth N4 is a cluster miss but a level hit.
3. **Late-symptom penalty:** for process-level ground truth, an additional check that $s^\ast$ is not suspiciously close to the end of the trajectory. Concretely, for every process-level trajectory we report the fraction of predictions that fall in the last $k$ steps of the trajectory (default $k = 3$). A well-calibrated attributor should not have predictions bunching up against the trailing edge.

The three axes are reported separately rather than collapsed into a single score, because the operator cost of each kind of miss is different: a wrong cluster with a correct step is a labeling problem; a wrong step with a correct cluster is an attribution problem; both together indicate the attributor did not engage with this trajectory meaningfully.

## 4. Taxonomy

The cluster vocabulary $\mathcal{C}$ was derived inductively from the 158 consolidated trajectories (pre-drop; see Section 5). It was **not** pre-specified: we read every distinct `failure_type` in AEB and every `mistake_reason` free-text string in Who_and_When, grouped them by reasoning signature, and assigned each group a level (node vs process) based on whether the described failure is localized to one step or structural across steps.

### 4.1 The nine clusters

**Node-level clusters** (single step; locally visible):

| ID | Cluster | Validation method |
|---|---|---|
| N1 | Hallucination / factual fabrication | Requires ground-truth reference answer |
| N2 | Code implementation bug | Runtime-verifiable by executing the code |
| N3 | Tool execution or retrieval failure | Detectable from tool output or error signals |
| N4 | Wrong tool selection | Task-goal vs tool-purpose comparison |
| N5 | Invalid tool parameters / input | Schema validation |

**Process-level clusters** (multi-step; cumulative or structural):

| ID | Cluster |
|---|---|
| P1 | Improper task decomposition / bad plan |
| P2 | Progress misassessment |
| P3 | Cascading error (explicit propagation) |
| P4 | Constraint ignorance / unchecked assumption |

### 4.2 Two design choices worth flagging

**N1 and N2 are kept separate** despite both being single-step fabrications. The reason is methodological rather than phenomenological: N2 is runtime-verifiable — you can execute the code and see whether it does what was claimed — while N1 requires a ground-truth reference answer to detect the fabrication. An evaluation suite will use different tooling for each, and merging them into a single cluster would obscure this distinction.

**P4 (constraint ignorance) is retained as its own cluster** even though it does not match any of the pre-existing categories in the taxonomy we initially imported from the literature. The data supports a distinct cluster — "the agent ignored a stated constraint or accepted an unverified value as fact" — and forcing those records into a nearby category (such as P2 or P1) would mis-score the attributor's task. The working agreement throughout this project is that data-driven clusters take precedence over imported ones when the two disagree.

### 4.3 Categories listed in the literature but absent from this data

The initial taxonomy we imported from prior work includes two more process-level categories that have **zero representation** in the consolidated library: long-horizon goal drift (P5) and causal misattribution (P6). Neither AEB nor Who_and_When annotators flagged any of the 158 trajectories in those terms. This is not a claim that such failures don't exist in agentic systems; it is a statement about coverage of this particular labeled library. Any evaluation of the Google ADK suite on this benchmark cannot, by construction, score its behavior on P5 or P6, and we flag this as a limitation (Section 7).

## 5. Dataset: Consolidation to GAIA

### 5.1 Sources

| Source | Split | Records | Label format |
|---|---|---|---|
| AgentErrorBench | GAIA-only (whole library) | 50 | Standardized `critical_failure_module` × `failure_type` |
| Who_and_When | Hand-Crafted | 58 | Free-text `mistake_reason` (+ mostly-null `mistake_type`) |
| Who_and_When | Algorithm-Generated | 126 | Free-text `mistake_reason` |

### 5.2 Filtering

**GAIA-only filter.** The two Who_and_When splits mix GAIA and AssistantBench questions. GAIA questions have UUID-format `question_ID` (`8-4-4-4-12` hex), AssistantBench questions have 64-character SHA-256-style hex. We confirmed this discriminator by sampling question text in each group (GAIA: multi-hop research questions; AssistantBench: "gyms within X miles of Y"-style web queries). Dropping AssistantBench removes 56 Who_and_When rows (28 per split). All 50 AEB records are already GAIA.

**Who_and_When dedup.** 20 GAIA UUIDs appear in both the Hand-Crafted and Algorithm-Generated splits. Per the working decision that human annotation is more likely to be correct than algorithmic, the Hand-Crafted annotation wins and the 20 duplicated Algorithm-Generated rows are dropped.

**Ambiguous-record drop.** Four Who_and_When records carry reasoning text too sparse to cluster with confidence — strings like "The reasoning process is wrong." or "The answer provided was incorrect." — which, in isolation, cannot be assigned to a cluster, nor can any attribution method be fairly scored against them. We drop these four rather than guess a label.

**Resulting dataset:** 154 labeled GAIA trajectories (50 AEB + 30 HC + 74 AG).

### 5.3 Normalization

A handful of data-quality issues were resolved during consolidation and are documented in the step-1 and step-2 reports. Briefly: AEB `failure_type` strings were lowercased and stripped (resolving `Parameter_error` → `parameter_error` and a trailing-whitespace variant of `tool_execution_error`); Who_and_When `mistake_agent` capitalization was canonicalized (resolving `Websurfer` → `WebSurfer`); `mistake_step` was cast from string to int; divergent field names (`is_correct`/`is_corrected`, `ground_truth`/`groundtruth`) were merged; Hand-Crafted history entries, which lack a `name` field, were filled with `null` to match the Algorithm-Generated schema.

### 5.4 Cluster assignment procedure

AEB's standardized `(module, failure_type)` pairs were mapped to the nine clusters deterministically: e.g. `(action, parameter_error)` → N5, `(planning, inefficient_plan)` → P1, `(memory, over_simplification)` → P3. The full mapping is in `scripts/finalize.py`.

Who_and_When records, which lack standardized labels, were clustered by reading every `mistake_reason` and grouping by reasoning signature into the same nine clusters. Representative excerpts for each cluster are recorded in the step-3 report. Ambiguous assignments were flagged (not silently resolved) and surfaced for explicit user decision before being dropped.

### 5.5 Per-record verification pass

After the initial clustering, every one of the 154 records was re-examined row-by-row against the extended cluster definitions of §4. Each record's step content, prior step context, and annotator reasoning were read, compared against the definition of the proposed cluster (including its counterfactual and nearest-neighbor tests), and assigned a verdict of KEEP, CHANGE `<old> → <new>`, FLAG, or DROP. Batches were reviewed in sets of five with explicit user sign-off before any change was written to the patch file.

The verification surfaced several consistent patterns. First, N1 (hallucination) had been over-applied to records where a wrong factual claim was actually read from real tool output (correctly reclassified as P2 misinterpretation) or derived from a malformed tool argument such as a placeholder URL or incomplete identifier (reclassified as N5). Second, N3 (tool execution failure) had been over-applied to records where no tool was invoked at the critical step (reclassified as P2) or where the wrong tool was selected in the first place (reclassified as N4). Third, a class of records with "outcome-only" reasoning text — phrases such as "the code is wrong," "the caculation is wrong," or "the answer provided was incorrect" — carried no mechanism description sufficient to support any cluster assignment and were dropped for the same reason as the four ambiguous records dropped in §5.2.

The verification produced (across all 154 records): 17 cluster changes, 11 FLAGs requiring further case-by-case handling (most commonly step-0 assignments where the critical step is actually the manager's task delivery, not agent behavior; and N3 records where no tool invocation is present in the critical step), and 11 additional DROPs for outcome-only reasoning. The patch file of per-record decisions is `data/consolidated/cluster_review_patch.jsonl`; the final-distribution numbers reported in §5.6 reflect the pre-patch state and will be updated once the patch is applied and written back to `gaia_consolidated.jsonl`.

### 5.6 Final distribution

**By level** (154 records):

| Level | Count | % |
|---|---|---|
| Node-level | 85 | 55% |
| Process-level | 69 | 45% |

**By cluster:**

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

**By origin step (all 154 trajectories):** steps 0–2: 64 records · 3–5: 53 · 6–10: 23 · 11+: 14 (max 51, pre-drop max 51). The long tail of late-origin failures comes almost entirely from Who_and_When, where trajectories are longer and failures sometimes originate deep into a conversation; this is the region where late-symptom bias is most consequential.

## 6. Methodology

The Google ADK evaluation suite is not a single metric but a scaffold: a small set of built-in evaluators, an `EvalSet`/`EvalCase` data format, an `Evaluator` base class, and six callback hooks (`before/after_agent`, `before/after_model`, `before/after_tool`) that emit events onto a session event bus. Of its five shipped evaluators, only `rubric_based_final_response_quality_v1` is directly usable for attribution (as a reference-free rubric-based judge) and `final_response_match_v2` is useful as a failure-detector gate; `tool_trajectory_avg_score` requires expected trajectories we do not have, `response_match_score` is ROUGE-1 lexical and inadequate for GAIA semantic matching, and `safety_v1` is unrelated to attribution. Per-step error localization, cascading-error detection, goal-drift detection, late-symptom bias penalties, and any failure-taxonomy annotation schema on `EvalCase` are absent from ADK and must be added by the user. The methodology below specifies how we add them.

The evaluation is organized into four phases: a dataset adapter, an off-the-shelf baseline, three custom evaluators with a constraint layer, and a stratified scorecard. Each phase produces a standalone artifact that can be inspected independently of the next.

### 6.1 Phase A — Adapter and data hygiene

The 154-record consolidated JSONL is converted into ADK's `EvalSet`/`EvalCase` format with one `EvalCase` per trajectory and the ground-truth fields (`ground_truth_origin_step`, `ground_truth_cluster`, `ground_truth_level`, `source`, optional `symptom_step` for AEB P3 records) carried as case metadata rather than embedded in the judge-visible trajectory payload. A three-way dataset split is recorded as a `split` field on each record: a development slice of about five records (stratified to cover every cluster, with two each for P3 and P4) used only for prompt-scaffolding iteration; an evaluation slice of about 149 records used for the primary scorecard, which the judge never sees during prompt construction; and a calibration slice of about five records pulled from the eval set after it is locked, used for a human-vs-judge κ check before any scorecard number is declared trustworthy.

Before any evaluator runs, a data-hygiene pass strips annotation metadata from every trajectory to prevent leakage into the judge's context. Fields matching `critical_failure_*`, `mistake_*`, `failure_type`, `proposed_cluster`, and `proposed_level`, plus any free-text field that heuristically reads as annotator commentary, are removed from the trajectory payload and retained only in the scoring-side metadata file. The pipeline emits two files: `gaia_consolidated_clean.jsonl` — the judge-visible input that contains only `clean_trajectory` — and `gaia_consolidated_with_gt.jsonl` — the scoring-side file where ground truth is never shown to the judge. A pre-flight assertion before any evaluator run fails the pipeline if any ground-truth field appears in any string the judge will see, and an additional grep for keywords such as `critical_failure`, `mistake`, "should have," and "the agent failed" flags any trajectory that survives stripping but still matches for manual review.

### 6.2 Phase B — Off-the-shelf baseline

`rubric_based_final_response_quality_v1` is configured with a single-item rubric instructing the judge to identify the earliest unrecoverable step, classify the failure into one of the nine clusters, and justify the choice. This is the "what does ADK give you if you just turn it on?" number. The rubric is reference-free (it does not require a golden final response) and emits a structured verdict under a JSON output schema of `{predicted_origin_step: int, predicted_cluster: str, predicted_level: "node" | "process", reasoning: str, evidence_steps: int[], confidence: float, unassignable: bool}`, with strict JSON mode enforced where the underlying model supports it and a validation-plus-retry loop for parse failures.

The rubric prompt applies five practices from the LLM-as-judge literature. First, chain-of-thought reasoning is emitted before the verdict; G-Eval reports a Spearman ρ lift from 0.51 to 0.66 on summarization under this design, and Who&When reports an independent lift of 4–7% on failure attribution. Second, the structured output schema removes verbosity as a scoring lever and enables automated parsing. Third, the judge emits a per-prediction confidence score so that confidence-stratified accuracy can be reported as a calibration check. Fourth, bias mitigations are applied where relevant: position bias is not on the scoring surface (absolute, not pairwise); verbosity bias is neutralized by the structured schema; self-preference bias is addressed by the model-swap ablation of §6.5; long-context lazy-parsing risk — material for trajectories of 100+ steps — is addressed by the strict JSON mode and validation-plus-retry loop. Fifth, the prompt structure is fixed: a role preamble defining the task, a taxonomy block containing the nine cluster definitions and reasoning signatures from the step-3 taxonomy review, the JSON output schema, the chain-of-thought instruction, the trajectory block, and — for the constraint-grounded evaluator of §6.3 only — an appended violation log.

A sanity-check `final_response_match_v2` gate runs before attribution to confirm that the trajectory actually failed. Our dataset is pre-filtered to failures, so this gate is robustness insurance against mislabeled rows rather than a primary filter; agreement rates are reported separately.

### 6.3 Phase C — Custom evaluators and constraint layer

Three custom `Evaluator` subclasses extend the baseline. The choice of three rather than four reflects a direct reading of Who&When's reported numbers: on their multi-agent systems, Step-by-Step attribution achieves 16.6% step-level accuracy and 36.2% agent-level accuracy; Binary Search achieves 16.6% step-level and 20.0% agent-level; All-at-Once achieves 6.9% step-level and 53.5% agent-level. Step-level accuracy between Step-by-Step and Binary Search is a tie, Binary Search wins on cost (O(log n) versus O(i*/2)) and has the more trajectory-aware framing ("has the trajectory diverged from the goal by step k?"), and Step-by-Step's agent-level advantage is already covered by All-at-Once. We note the caveat that Who&When's numbers are reported on their systems and not on GAIA specifically, and we may revisit the decision if Phase C results are surprising.

The three evaluators are: **All-at-Once Attribution**, a one-pass judge over the full trajectory that is fast and produces the best agent-level accuracy in the comparison set; **Binary-Search Attribution**, a log-bisection procedure that asks the judge at each split whether the trajectory has diverged from the goal by step k, keeping context per call small and framing the question in process-level terms; and **Constraint-Grounded Attribution**, which does not read the trajectory alone but reads the trajectory together with a per-trajectory violation log produced by the constraint layer described below. Prompt engineering follows the MAST pattern of cluster-definition-plus-reasoning-signature rather than full-trajectory few-shot exemplars; longer exemplars are reserved for P3 (where "cascading language" must be demonstrated) and P2 (where disambiguation from N1 is the recurring confusion). The Constraint-Grounded evaluator mostly skips few-shots and leans on the violation log as evidence, following the evidence-grounded judging methodology that AgentRx validated on different domains. We are not porting AgentRx's constraints, tasks, or data — which cover τ-bench and Magentic-One customer-service workflows and do not transfer to GAIA — only the methodology of generating a domain-specific violation log and feeding it to the judge.

The constraint layer supports the Constraint-Grounded evaluator. Every constraint emits a `ConstraintEvent` of shape `{step, constraint_id, verdict, evidence}` with verdict in `{CLEAR_PASS, CLEAR_FAIL, UNCLEAR}` onto an in-memory log. The constraint set is partitioned into static and dynamic constraints.

Static constraints were audited against the realism of applying them uniformly across AEB, Who&When Hand-Crafted, and Who&When Algorithm-Generated trajectories — three different source systems with different tool interfaces and agent role specs. Five tier-1 constraints survive the audit and are retained: **S4** no repeated identical tool call within three steps (pattern-matched on `(tool_name, args_hash)`); **S5** no submit-final-answer before any information gathering (heuristic terminal-action detector with confidence flag, since terminal-action names vary by source); **S6** no tool calls after submit-final-answer (same heuristic detector); **S8** tool-result error signals such as `404`, `500`, or "not found" in tool output (regex scan); and **S9** a per-agent step budget counted per agent with an empirical threshold. Five additional static constraints (S1 tool-args schema match, S2 enum membership, S3 toolset membership, S7 tool-capability mismatch, S10 role-specification response-format match) are dropped because they require per-source tool schemas or agent role specs we cannot realistically encode at scale; they are candidates for follow-up work if Phase D surfaces a specific gap they would close.

Dynamic constraints are synthesized per task from the GAIA prompt by a single LLM call at the start of evaluation and cached. Nine dynamic constraints are supported: **D1** final-answer-format match (integer / list / string / yes-no) against the task specification; **D2** temporal-validity verification when the task references a time frame; **D3** required-source access when the task references a specific source; **D4** sub-question coverage for multi-part tasks; **D5** file-and-URL access when the task references files or URLs; **D6** forbidden-action avoidance; **D7** claim-backing where reasoning claims are matched against prior tool outputs in a streaming hallucination check; **D8** a verification step for numerical computations; and **D9** plan-adherence where the plan enumerated at run start is either followed or explicitly revised. The dynamic set is per-task, not per-agent — constraints are about whether the system as a whole satisfies the task, not whether any individual agent follows its local role spec — and the set D1 together with D2, D3, D6, and D9 collectively covers the instruction-following dimension, so a separate instruction-following evaluator is not needed.

Because this project evaluates pre-recorded trajectories rather than live ADK agents, callback language in the Phase C design is a metaphor for where in the trajectory each constraint applies rather than a literal runtime. The implementation is a `TrajectoryReplayer` class that walks each recorded trajectory step by step and applies the appropriate static and dynamic constraints at each position: static S4, S8, and where applicable S9 at each tool call; S5 and S6 heuristic terminal-action checks plus dynamic D1, D7, and D9 at each model response; and S8 error-signal scan at each tool result. The replayer produces the violation log artifact, which is then fed to the Constraint-Grounded Attribution evaluator along with the clean trajectory, the taxonomy checklist, and the reasoning prompt.

### 6.4 Phase D — Scoring

The scorecard implements the three-part match of §3. **Origin-step match** is reported at two tolerance levels: tolerance 0 (exact step match) and tolerance 3 (`|predicted − ground_truth| ≤ 3`); tolerance 3 is the headline metric and tolerance 0 is reported as a secondary stress metric, on the basis that Who&When's own numbers show tolerance 0 is brutal (≈17%) while tolerance 5 is ≈43% and tolerance 3 reflects human annotation wobble. **Cluster match** is reported in two modes: exact match over the nine clusters and level-only match over the node-vs-process split, with the latter serving as the "did it at least get the right kind of failure?" check. **Late-symptom fidelity** is computed only on AgentErrorBench P3 records (n = 12), where `ground_truth_origin_step` and `symptom_step` are cleanly separable; the metric is the fraction of P3 predictions where `predicted_step ≤ symptom_step − Δ` with Δ = 3 to match the tolerance bound, and confidence bounds are reported given the small sample size.

Every metric is reported three ways: aggregated over the 134-record eval slice, stratified by source (AEB vs Who&When Hand-Crafted vs Who&When Algorithm-Generated), and stratified by cluster (per N1–N5 and per P1–P4). Without stratification, AEB's process-heavy skew and Who&When's node-heavy skew mask the method strengths and weaknesses the experiment is designed to reveal. P5 (goal drift) and P6 (causal misattribution) appear in the judge's cluster list; if the judge predicts either, the prediction is logged but not counted in the primary scorecard because no ground truth is available, and the rate of P5/P6 predictions is reported separately as an "unassignable predictions" count. Before any scorecard number is declared trustworthy, Cohen's κ between judge and human is computed on the five-record calibration set; the bar to clear is κ ≥ 0.70, below MAST's 0.77 but acceptable given that our task is strictly harder than theirs.

### 6.5 Model matrix and ablations

The primary judge for Phase B and all non-ablation Phase C runs is `gemini-3-pro-preview`. The full model matrix — `gemini-3-pro-preview`, `gemini-2.5-flash-lite`, Claude 4 Sonnet via Vertex Model Garden, GPT-4o/GPT-5 via LiteLLM to the OpenAI API, and a small cross-provider option (`gemini-2.5-flash` or Claude Haiku) — is run only on Phase B baseline and on Constraint-Grounded Attribution. Running the full matrix on all four evaluators would inflate condition count to twenty and dilute signal; running two evaluators across five models gives ten conditions and is tractable.

Four ablations live in the paper's appendix. The first is the model swap above. The second is a constraint-log ablation that runs Constraint-Grounded Attribution without the violation log injected; if the resulting lift over the baseline is less than five percentage points, the evidence-grounded-judging methodology is not pulling its weight on this dataset and the constraint layer should be revisited. The third is a trajectory-length stratification into buckets of ≤ 20, 21–50, and > 50 steps, which is where All-at-Once Attribution is expected to collapse relative to Binary-Search Attribution. The fourth is a reasoning-mode on/off comparison on Gemini 3 Pro thinking mode, which probes Who&When's surprising finding that reasoning models (o1, R1) underperformed GPT-4o on failure attribution.

## 7. Preliminary Analysis

The evaluation suite has not yet been run at the time of this draft; the observations below characterize the **dataset** and its implications for what such a run will and won't be able to measure.

### 7.1 Source-level asymmetries

AgentErrorBench is process-heavy: 39 of its 50 GAIA records (78%) are process-level, dominated by planning-module failures. Who_and_When is node-heavy: 74 of its 108 post-dedup, post-drop GAIA records (69%) are node-level, dominated by N1 (hallucination) and N2 (code bug).

This matters for evaluation design. A suite tested only on AEB would underrate how well the attributor handles localized fabrication (N1 is only one trajectory in AEB). A suite tested only on Who_and_When would underrate cascading-error detection (P3 is absent from AEB). Reporting per-source performance alongside the aggregate is therefore necessary.

### 7.2 The code-bug tail from Who_and_When

N2 (code implementation bug) is the single largest cluster from Who_and_When (24 of 108 records). This reflects the multi-agent architecture from which those trajectories are drawn — AutoGen / Magentic-One expert agents (PythonDebugging_Expert, DataAnalysis_Expert, etc.) write and execute a great deal of Python. AEB's agents do not execute Python, so the cluster is effectively absent there (0 records).

Any attribution suite that relies on spotting runtime errors in code blocks to identify failure origin will do well on this subset but cannot generalize that competence to the AEB subset, where code is not in play.

### 7.3 P3 is the clearest stress test

Cluster P3 (cascading error with explicit propagation) has 12 records. Its defining feature is that the annotator's reasoning text explicitly calls out downstream contamination — e.g. _"The price provided by HawaiiRealEstate_Expert is incorrect, causing the error to propagate through subsequent steps to the final output."_ Because the annotator has labeled both the origin and the downstream propagation, these trajectories are the cleanest test of whether an attributor can resist late-symptom bias: the symptom step is documented to be late, the origin is documented to be early, and the suite must pick the latter.

We will report P3 performance as a standalone headline number, because it is the cluster where the evaluation framework's most distinctive criterion (late-symptom bias resistance) is most directly applicable.

### 7.4 Coverage gaps

As noted in §4.3, the consolidated library contains zero examples of long-horizon goal drift (P5) and zero examples of causal misattribution (P6). The evaluation can therefore say nothing about the Google ADK suite's competence on those modes. Extending the benchmark to cover them would require either finding annotations in a different source library or generating and labeling new trajectories deliberately targeted at those modes — both deferred to future work.

### 7.5 Class imbalance

The cluster distribution is skewed: two clusters (N1, P1) account for 43% of the dataset; two clusters (N5, P4) have ≤ 10 records each. Per-cluster accuracy numbers for the smaller clusters will be noisy. We will report confidence intervals accordingly and avoid over-interpreting small-sample differences.

## 8. Results

_To be populated after Phase D completes. The scorecard will report origin-step match at tolerance 0 and tolerance 3, exact and level-only cluster match, and late-symptom fidelity restricted to the twelve AgentErrorBench P3 records, each aggregated and stratified by source (AEB vs Who_and_When Hand-Crafted vs Who_and_When Algorithm-Generated) and by cluster (N1–N5, P1–P4). The off-the-shelf rubric baseline from §6.2 will be reported as the reference point against which the three custom evaluators of §6.3 are measured. Ablation tables from the model matrix, the constraint-log ablation, the trajectory-length stratification, and the reasoning-mode ablation will live in the appendix._

## 9. Limitations and Threats to Validity

**Single-origin assumption.** Each trajectory carries exactly one annotated failure-origin step. Real trajectories may contain multiple independent failures; the consolidated library cannot distinguish them. A predicted origin step that matches neither the ground-truth origin nor any secondary annotated failure will be scored as a miss even if it is, in fact, a real failure in the trajectory.

**Free-text clustering noise.** Who_and_When labels were assigned by reading free-text `mistake_reason` strings and grouping by reasoning signature. This process is not reproducible in the strict statistical sense. Independent re-clustering by a second annotator would produce slightly different boundary assignments, particularly between P1 (bad plan) and P2 (progress misassessment), and between N1 (hallucination) and P3 (cascading fabrication).

**Taxonomy is data-bounded.** The nine clusters are the clusters this particular library supports. They are not a closed-form taxonomy of agentic failure. A different library — e.g. one drawn from long-horizon autonomous agents rather than tool-calling research agents — would likely require different clusters.

**Missing P5 and P6.** Previously noted; any conclusion about the Google ADK suite's total-vocabulary coverage is restricted to the seven-of-nine modes that are actually present.

**Late-symptom scoring is heuristic.** The default "last $k$ steps" check in §3 is a first-order proxy. A more principled version would use the trajectory structure to identify the last step at which information relevant to the ground-truth origin was still available to the agent; we leave that refinement for future work.

## 10. Future Work

The immediate next milestone is execution of the four-phase methodology of §6 against `data/consolidated/gaia_consolidated_clean.jsonl` and production of the scorecard in §8. Reporting will be broken down per cluster, per source (AEB vs Who_and_When), and per level (node vs process), with P3 singled out as the headline stress test and the calibration κ check gating whether any of the numbers is declared trustworthy.

Beyond that first scored run, three extensions are on the near horizon. First, a targeted data-collection pass to bring P5 (goal drift) and P6 (causal misattribution) into the library so the benchmark can score the full failure vocabulary the literature names. Second, a comparison against at least one non-LLM attribution baseline (e.g. a simple heuristic that always points at the last tool-error step) to calibrate how much of the suite's score is driven by genuinely understanding the trajectory rather than by trajectory-independent regularities. Third, a small inter-annotator agreement study on a held-out subset of Who_and_When records to quantify the clustering noise acknowledged in §9. A fourth possible extension is revisiting the five dropped static constraints (S1, S2, S3, S7, S10) for source-specific subsets where schemas or role specs are recoverable, if the Phase D results point at a gap those constraints would close.

## 11. Conclusion

We have constructed and documented a 154-trajectory, GAIA-only, unified-taxonomy failure-attribution benchmark built from two previously unaligned annotation libraries, together with a row-by-row verification pass over every record's cluster assignment and an end-to-end ADK-based evaluation methodology that layers three custom attribution evaluators and a constraint-synthesis layer on top of ADK's off-the-shelf rubric baseline. The benchmark and the methodology are ready to be run under a three-part scoring protocol that specifically targets the hardest case in agentic failure attribution — process-level failures that originate early but surface late. The consolidated dataset, per-record classifications, data-hygiene pipeline, evaluator scaffolding, and scoring protocol are the prerequisites for that run; results and interpretation follow in subsequent drafts.

## References

_[TODO: convert the four `paper/references/` PDFs into proper bibliographic entries. Current placeholders, to be replaced:]_

- [ref-2503.13657] — `paper/references/2503.13657v2.pdf`
- [ref-2505.00212] — `paper/references/2505.00212v3.pdf` (AgentErrorBench)
- [ref-2509.25370] — `paper/references/2509.25370v1.pdf` (Who_and_When)
- [ref-2602.02475] — `paper/references/2602.02475v1.pdf`

## Appendix A. Dataset artifacts and methodology references

- Consolidated JSONL (154 records): `data/consolidated/gaia_consolidated.jsonl`
- Per-record classifications (CSV): `data/consolidated/failure_classifications.csv`
- Per-record cluster-review patch: `data/consolidated/cluster_review_patch.jsonl`
- Step-1 (data cleaning) report: `docs/reports/step1_data_cleaning.md`
- Step-2 (consolidation) report: `docs/reports/step2_consolidation.md`
- Step-3 (taxonomy review) report: `docs/reports/step3_taxonomy_review.md`
- Cluster-review handoff and batch-1–4 patches: `docs/reports/cluster_review_handoff.md`
- Cluster-review batches 5+ (records #25–153): `docs/reports/cluster_review_batch5_onwards.md`
- AgentErrorBench cluster review (AEB #0–49): `docs/reports/aeb_review_section.md`
- Step-4 methodology plan: `docs/reports/step4_plan.md`
- Google ADK evaluation suite reference notes: `docs/reports/adk_eval_suite_notes.md`
- Decisions log + current project state: `docs/PROJECT.md`
