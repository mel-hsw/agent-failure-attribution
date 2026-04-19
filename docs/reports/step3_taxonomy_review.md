# Step 3 — Failure-Taxonomy Review

_Date: 2026-04-17 · 158 consolidated GAIA trajectories · Please validate the node-vs-process assignments before we commit._

## Summary of proposed classifications

| Level | Count | % of dataset |
|---|---|---|
| Node-level | 85 | 54% |
| Process-level | 69 | 44% |
| Ambiguous (flagged) | 4 | 2% |

## Unified cluster definitions

I collapsed the AEB standardized types and the W&W free-text reasoning into **9 unified clusters** that map cleanly onto the node-vs-process split from `CLAUDE.md`. The quick-reference tables below are followed by extended descriptions for each cluster; these extended descriptions are the authoritative definitions for classification purposes.

### Node-level (single-step, localized)

| ID | Cluster | Maps to CLAUDE.md category |
|---|---|---|
| **N1** | Hallucination / factual fabrication | Hallucination |
| **N2** | Code implementation bug | Hallucination (code fabrication) — see note |
| **N3** | Tool execution or retrieval failure | Invalid tool invocation (environment-driven) |
| **N4** | Wrong tool selection | Wrong tool selection |
| **N5** | Invalid tool parameters / input | Invalid tool invocation |

### Process-level (multi-step, structural or cumulative)

| ID | Cluster | Maps to CLAUDE.md category |
|---|---|---|
| **P1** | Improper task decomposition / bad plan | Unreasonable node dependency / improper task decomposition |
| **P2** | Progress misassessment | Progress misassessment |
| **P3** | Cascading error (explicit propagation) | Cascading errors / error propagation |
| **P4** | Constraint ignorance / unchecked assumption | (new — closest to goal drift, but at origin step) |
| P5 | Goal drift / objective divergence | Long-horizon goal drift — **not observed** in this 158-record subset |
| P6 | Causal misattribution | **not observed** in this 158-record subset |

---

### Extended cluster definitions

The descriptions below are the canonical definitions used for labeling. Each definition covers: the core behavior that qualifies a record for this cluster, the validation method an evaluator would use to detect it, and explicit boundaries that separate this cluster from its nearest neighbors. Literature correspondences are noted where relevant.

---

#### N1 — Hallucination / factual fabrication

The agent asserts a specific fact, number, name, date, or content string that is not grounded in any retrieved source, tool output, or prior turn in the conversation history. The agent may cite a plausible-sounding reference that does not exist, perform arithmetic on values it never retrieved, or describe the content of a document it never accessed. The failure is contained to a single step: at that step, the agent produces a specific claim, and the claim is demonstrably false relative to the ground-truth answer.

**Validation method.** Requires a ground-truth reference answer; the fabrication cannot be detected from the trajectory alone without knowing what the correct answer is. This distinguishes N1 from all tool-based clusters (N3, N4, N5), where the error is visible in the tool call or its return value.

**Nearest-neighbor boundaries.** N1 differs from N2 (code bug) in that no executable code is involved — the agent is making a declarative claim, not running a procedure. N1 differs from P3 (cascading error) in that N1 is the origin event; if a fabricated value is then passed downstream and corrupts later steps, the *origin* is still N1 (the downstream corruption is classified P3 in the trajectory it damages, but the record in this dataset carries the origin label). N1 differs from P2 (progress misassessment) because N1 concerns *what the agent says*, not *how the agent evaluates its progress*.

**Literature correspondence.** Corresponds to the `memory.hallucination` failure type in the AgentErrorTaxonomy (Zhu et al., 2025), "Invention of New Information" in AGENTRX (Barke et al., 2026), and is a component of MAST's FM-1.1 Disobey Task Specification when the deviation is driven by invented content rather than rule-following failure (Cemri et al., 2025). The Who&When annotation vocabulary uses the phrase "fabricated" or "hallucinates" to flag this mode.

---

#### N2 — Code implementation bug

The agent writes executable code that runs without a hard crash but produces incorrect output. Failure signatures include: wrong algorithm for the task (e.g., DFS that does not explore all branches), unhandled edge cases (e.g., dropping NaN rows when counting requires them), incorrect indexing or slicing, wrong aggregation logic, or incorrect data type handling. The code is syntactically valid and may even return a result — the result is simply wrong relative to the task.

**Validation method.** Runtime-verifiable by executing the code against a known-correct input/output pair. This is the defining distinguishing feature from N1: a human or automated evaluator can, in principle, detect an N2 failure *without* knowing the answer to the original task, by running the code and checking its output against a test case.

**Nearest-neighbor boundaries.** N2 differs from N1 in that it involves a procedural error (wrong logic in code), not a declarative error (wrong stated fact). N2 differs from N3 (tool execution failure) in that the code *executes successfully* at the system level — the tool completes, but the agent-written logic inside it is incorrect. N2 differs from N5 (bad parameters) in that the problem is in the *body* of the agent's code, not in the arguments supplied to an external tool. This cluster is entirely absent from AgentErrorBench (which uses non-Python-executing agents) and is the single largest cluster in Who&When (24 of 108 records), reflecting the heavy Python use by AutoGen/Magentic-One expert agents.

**Literature correspondence.** Closest to the `action.misalignment` failure type in AgentErrorTaxonomy when the misalignment is in agent-written code (Zhu et al., 2025), and to "Invention of New Information" in AGENTRX when the invented information takes the form of a procedurally derived but wrong result (Barke et al., 2026). MAST does not isolate code bugs as a distinct mode; they surface there as Reasoning-Action Mismatch (FM-2.6) when the agent's stated reasoning does not match the code it writes.

---

#### N3 — Tool execution or retrieval failure

The agent invokes the correct tool with structurally valid arguments, but the tool returns no useful result due to a system or environment failure: a 404 or access-denied error, a timeout, an empty result set where content was expected, an API endpoint that is unreachable, or a context-window limit that prevents the underlying LLM from following its instructions. The failure is in the environment or infrastructure, not in the agent's reasoning or choice of tool.

**Validation method.** Detectable from the tool output or error signals in the trajectory: the return value contains an error code, an exception, or a null/empty payload where content was expected. Unlike N1, no ground-truth answer is needed — the failure is visible from the trajectory itself.

**Nearest-neighbor boundaries.** N3 differs from N4 (wrong tool selection) in that the right tool was chosen; the problem is what happened when it ran. N3 differs from N5 (bad parameters) in that the invocation was structurally correct — the tool's failure is not attributable to the agent's input formation. N3 differs from P3 (cascading error) in that the environment failure is the origin event; if the missing data then causes downstream steps to fail, the origin record is still N3.

**Literature correspondence.** Corresponds to `system.tool_execution_error` and `system.llm_limit` in the AgentErrorTaxonomy (Zhu et al., 2025), "System Failure" in AGENTRX (Barke et al., 2026), and the System-level module (Environment Error, Step Limit, Tool Execution Error) in AgentErrorBench. MAST does not treat environment failures as a primary failure mode; they appear there as context for other modes rather than as first-class origins.

---

#### N4 — Wrong tool selection

The agent selects a tool that is inappropriate for the task goal, even though the tool is available and could, in principle, be invoked. Representative signatures: using a general web search tool when a task-specific database tool exists and is needed; using a Wikipedia searcher when the required source is Tropicos; using an OCR tool on data that requires structured parsing; using a code generator for manual arithmetic. The correct tool exists in the system's toolkit; the agent simply chose the wrong one.

**Validation method.** Requires comparing the task goal to the selected tool's documented purpose. The error is visible from the trajectory — the tool's output will be off-target — but diagnosis requires knowing what the correct tool would have been, which makes this cluster harder to detect automatically than N3 or N5.

**Nearest-neighbor boundaries.** N4 differs from N3 (tool execution failure) in that the failure is in the *selection decision*, not in the execution outcome — an N4 tool might return a result, but that result is irrelevant to the task. N4 differs from N5 (bad parameters) in the level of error: N4 is about *which* tool was invoked, N5 is about *how* the correct tool was invoked. N4 and P1 (bad plan) can co-occur at origin — a plan that routes a subtask to the wrong agent is a P1 failure; a single step within an otherwise correct plan that calls the wrong tool is N4.

**Literature correspondence.** Corresponds to `action.misalignment` in the AgentErrorTaxonomy (Zhu et al., 2025), "Intent Not Supported" in AGENTRX when an appropriate tool does exist but was not selected (Barke et al., 2026), and FM-1.1 Disobey Task Specification in MAST when the disobedience manifests as calling the wrong tool (Cemri et al., 2025). In Who&When, annotators typically flag this with phrases like "should have used X instead of Y."

---

#### N5 — Invalid tool parameters / input

The agent selects the correct tool for the task but invokes it with malformed, incorrect, or missing arguments: a query string that points at the wrong resource, a missing required field, a type mismatch, an incorrectly scoped search term, or a URL that does not correspond to the target document. The tool could succeed if given the right input; the failure is in the agent's input formation.

**Validation method.** Schema validation or inspection of the tool's input against its documented API: the error is visible in the call itself, not in the tool's execution outcome. This makes N5 the most mechanically detectable cluster among the node-level failures.

**Nearest-neighbor boundaries.** N5 differs from N3 (tool execution failure) in the locus of fault: N5 is an agent error (wrong input was supplied); N3 is an environment error (the system failed despite correct input). N5 differs from N4 (wrong tool) in that N5 presupposes the right tool was chosen — the error is at the argument level, not the selection level. N5 is the rarest cluster in this dataset (4 records), which may reflect that parameter errors are often caught and retried rather than reaching the final failure step.

**Literature correspondence.** Corresponds to `action.parameter_error` in the AgentErrorTaxonomy (Zhu et al., 2025) and "Invalid Invocation" in AGENTRX (Barke et al., 2026). In AgentErrorBench's labeling scheme, `parameter_error` is defined as "parameter error when calling tool" — the most operationally precise definition in the reference literature.

---

#### P1 — Improper task decomposition / bad plan

The agent's initial or subsequently revised plan is structurally flawed in a way that makes task success impossible or highly unlikely regardless of execution quality. Failure signatures include: assigning a subtask to an agent whose available tools cannot complete it; sequencing steps so that a later step requires information that the plan has no mechanism to gather; misreading the task description such that the plan targets the wrong goal from the outset; selecting a methodology (e.g., manual enumeration) that is computationally infeasible for the problem's scale. The error is in the *architecture of the plan*, not in its execution.

**Validation method.** Requires comparing the plan structure to the task requirements. An evaluator needs to ask: "If every step of this plan were executed perfectly, would the task succeed?" If the answer is no, the failure is P1. This counterfactual framing distinguishes P1 from all execution-level clusters.

**Nearest-neighbor boundaries.** P1 differs from P2 (progress misassessment) in *direction*: P1 is "the plan was wrong from the beginning"; P2 is "the plan was reasonable but the agent misjudged where it stood." A plan that is structurally sound but declared complete too early is P2, not P1. P1 differs from P4 (constraint ignorance) in scope: P4 involves the omission of one specific verification step within an otherwise reasonable plan; P1 involves a plan that would not succeed even if all verification steps were added. P1 and N4 (wrong tool) can share an origin step when the plan routes a subtask to an inappropriate tool — classify as P1 when the flaw is in the decomposition structure, N4 when the plan is otherwise sound but one step picks the wrong tool.

**Literature correspondence.** Corresponds to `planning.inefficient_plan` and `planning.impossible_action` in the AgentErrorTaxonomy (Zhu et al., 2025), "Intent-Plan Misalignment" in AGENTRX (Barke et al., 2026), and FM-1.1 Disobey Task Specification at the planning level in MAST (Cemri et al., 2025). In AgentErrorBench, `planning.inefficient_plan` is the single most frequent failure type (18 of 50 AEB records), underscoring that plan-level failures are the dominant failure mode in structured multi-agent systems.

---

#### P2 — Progress misassessment

The agent incorrectly evaluates its own state of progress: it declares the task complete when prerequisite information has not been gathered, proceeds to a final answer when essential verification steps have been skipped, or — in the opposite direction — fails to recognize that it has already obtained the needed information and continues taking redundant actions that introduce errors. The failure is in the agent's *self-monitoring and reflection*, not in the underlying plan or in any individual tool call.

**Validation method.** Requires comparing the agent's stated assessment of task status to the actual state of information at that step. The error is typically visible in the reasoning trace — the agent says "I have gathered enough information" or "the task is complete" in a step where it demonstrably has not.

**Nearest-neighbor boundaries.** P2 differs from P1 (bad plan) in that the plan itself may have been sound — the agent simply misjudged where it was within that plan. P2 differs from P3 (cascading error) in mechanism: P2 is a *self-assessment* failure (the agent's internal reflection module produces an incorrect evaluation); P3 is a *data propagation* failure (a specific erroneous value is carried forward by later agents). A trajectory where the agent closes out prematurely because it is working from a wrong value (P3 origin) is classified at the P3 origin, not as a P2 event, even if the premature termination is the visible symptom.

**Literature correspondence.** Corresponds to `reflection.progress_misjudge` and `reflection.outcome_misinterpretation` in the AgentErrorTaxonomy (Zhu et al., 2025), FM-3.1 Premature Termination and FM-3.2 No or Incomplete Verification in MAST (Cemri et al., 2025), and "Misinterpretation of Tool Output" in AGENTRX when the misinterpretation causes a premature conclusion (Barke et al., 2026). The Who&When annotators flag this mode with phrases like "directly reaches a conclusion without performing the correct actions" or "should not draw a conclusion if enough information has not been gathered."

---

#### P3 — Cascading error (explicit propagation)

An early failure — typically N1 (hallucination), N2 (code bug), or N3 (tool failure) — is not caught and corrected at origin; instead, its erroneous output is treated as ground truth by one or more downstream agents or steps, which build further reasoning and actions on top of it. The symptom of failure surfaces late in the trajectory, often at or near the final answer step, but the root cause is the much earlier origin event. A P3 classification requires that the annotator's reasoning text (or the trajectory structure) explicitly identifies both the origin step and the downstream propagation.

**Validation method.** Requires tracing the erroneous value forward through the trajectory: the origin value appears at step _k_, is carried into memory or passed to another agent, and shapes decisions at steps _k+1_ through _T_. The key diagnostic question is: "If the error at step _k_ had been corrected, would the downstream failure have occurred?" If no, the failure is P3 with origin at _k_.

**Nearest-neighbor boundaries.** P3 is the cluster most directly targeted by the late-symptom bias criterion in the evaluation protocol. An attributor that labels the *symptom* step (where the wrong final answer becomes visible) instead of the *origin* step is making exactly the error P3 is designed to stress-test. P3 differs from P1 (bad plan) because the initial plan may have been valid — P3 failures originate from a concrete data error, not from a structural design flaw. P3 differs from P2 (progress misassessment) because the cascade is data-driven: a specific wrong value is carried forward by later agents, rather than the agent misjudging its own status. P3 records often contain a node-level failure at origin (N1, N2, or N3) — the *origin* cluster label is the node-level one; P3 labels the process-level propagation pattern from the perspective of the downstream failure trajectory.

**Literature correspondence.** Corresponds to `memory.over_simplification` in the AgentErrorTaxonomy — where the memory module summarizes results in a way that loses key detail, which is then treated as accurate by planning and action modules in subsequent steps (Zhu et al., 2025). The AgentErrorBench paper's central finding — "error propagation is the primary bottleneck in LLM agent reliability; early mistakes rarely remain confined" — describes P3 as the dominant structural failure pattern across multi-step agent trajectories. MAST's FM-2.4 Information Withholding captures the inter-agent communication dimension of P3 when an agent fails to pass a correction downstream (Cemri et al., 2025).

---

#### P4 — Constraint ignorance / unchecked assumption

The agent proceeds with an unverified value or ignores a constraint that is explicitly or implicitly required by the task. The agent accepts an extracted value as correct without checking its validity (e.g., treating the first population figure returned by a search as the 2020 census value without confirming the date), or fails to apply a scope restriction that was specified in the task (e.g., using the current team roster when the task asks for the roster as of a specific past date). The agent's plan may have been otherwise reasonable; the failure is the omission of one verification or scope-checking step that was required.

**Validation method.** Requires comparing the agent's working assumptions at the origin step to the task's stated or implied constraints. The error is visible in the reasoning trace: the agent states or acts on a value without flagging uncertainty or performing a verification step that the task clearly required.

**Nearest-neighbor boundaries.** P4 differs from P1 (bad plan) in *scope*: P4 has an otherwise reasonable plan that omits one verification step for a specific constraint; P1 has a plan architecture that would fail even if all such steps were added. P4 differs from P2 (progress misassessment) in *target*: P2 is about whether the agent correctly assesses overall task completeness; P4 is about whether the agent correctly applies a specific factual or temporal constraint to a specific retrieved value. P4 differs from N1 (hallucination) in that the constraint-ignorance failure does not require the agent to have *invented* a fact — the value accepted may have been real but incorrectly scoped (e.g., a real population figure for the wrong year).

**Literature correspondence.** Corresponds to `planning.constraint_ignorance` in the AgentErrorTaxonomy (Zhu et al., 2025), FM-1.1 Disobey Task Specification in MAST when the disobedience is a missed constraint rather than an invented deviation (Cemri et al., 2025), and "Instruction/Plan Adherence Failure" in AGENTRX when a specific constraint is overlooked within an otherwise compliant plan (Barke et al., 2026). This cluster does not appear under a matching name in the CLAUDE.md initial taxonomy; it was retained because the data clearly supports a distinct cluster and forcing these records into P1 or P2 would misrepresent the failure mechanism.

### Counts per cluster

```
P1 Improper task decomposition / bad plan    33
N1 Hallucination / factual fabrication       33
N2 Code implementation bug                   24
P2 Progress misassessment                    17
N3 Tool execution or retrieval failure       15
P3 Cascading error (explicit propagation)    12
N4 Wrong tool selection                       9
P4 Constraint ignorance / unchecked assumption 7
N5 Invalid tool parameters / input             4
AMBIG (need your review)                       4
```

**Note on N2 vs N1**: I split "code bug" out from "hallucination" because they feel qualitatively different even though both are single-step fabrications. N1 is "the agent made up a fact/number/answer"; N2 is "the agent wrote code that doesn't work". If you'd rather fold them together, just merge N2 into N1 and the node count stays at 85.

---

## AgentErrorBench — mapping of the 11 standardized types

| Raw (module :: failure_type) | Count | Proposed cluster | Level | Representative reasoning |
|---|---|---|---|---|
| `planning :: inefficient_plan` | 18 | P1 | process | _"Make a low efficient plan that not success, repeat the similar action that not success"_ |
| `reflection :: outcome_misinterpretation` | 5 | P2 | process | _"Misinterpret the meaning and grouping of the provided cuneiform symbols"_ |
| `memory :: over_simplification` | 4 | P3 | process | _"At step 3, the memory module summarized the outcome of the world box office URL extraction as 'The top 10 highest-grossing worldwide movies were identified,' but did not actually store or enumerate the extracted movie titles…"_ |
| `planning :: constraint_ignorance` | 4 | P4 | process | _"constraint_ignorance by not including all required elements"_ |
| `planning :: impossible_action` | 4 | P1 | process | _"URL extractor can not extract video content, description, or transcript from a YouTube page, and only returns generic site text. This is an unreasonable parameter choice for the task…"_ |
| `reflection :: progress_misjudge` | 4 | P2 | process | _"progress_misjudge by claiming that the agent has completed the task goal"_ |
| `action :: misalignment` | 3 | N4 | node | _"the action taken was to use the 'wikipedia_knowledge_searcher' tool, which does not access the Tropicos database"_ |
| `action :: parameter_error` | 3 | N5 | node | _"Parameter error when calling tool"_ |
| `system :: tool_execution_error` | 3 | N3 | node | _"impossible_action by using the python_code_generator tool for manual arithmetic"_ |
| `memory :: hallucination` | 1 | N1 | node | _"hallucination by asserting that 'Tom Ridge, the first U.S. Secretary of Homeland Security, received his bachelor's degree from the University of Maryland UMBC.'"_ |
| `system :: llm_limit` | 1 | N3 | node | _"LLM limit: not follow the instructions but directly give the answer in the last part"_ |

**AEB totals: 11 node-level, 39 process-level.**

---

## Who_and_When — thematic clusters from free-text reasoning

Because W&W has no standardized `failure_type`, I read every `mistake_reason` and grouped them into the same 9 clusters. Below, a few representative examples per cluster; the full per-record spreadsheet is linked at the end.

### N1 — Hallucination / factual fabrication (31 W&W records)

- _Orchestrator/Assistant "made up" numbers or content_:
  - "Validation_Expert fabricated the population figures for Seattle and Colville, resulting in an incorrect calculation of the population difference."
  - "The expert fails to view the image and hallucinates the notes."
  - "ArtHistory_Expert fabricates the content of the website and does not actually verify its contents."
  - "Poetry_Expert begins providing the full text of the poem without retrieving the text and formatting from websites."

### N2 — Code implementation bug (24 W&W records)

- _Code executes but produces wrong output_:
  - "The DFS algorithm is not correctly exploring the possible words on the Boggle board."
  - "The code failed to handle edge cases in the 'Street Address' data, leading to an incomplete and inaccurate count of even-numbered addresses."
  - "The agent made a mistake in handling the NaN values in the 'Platform' column by dropping all NaN values from the DataFrame."

### N3 — Tool execution or retrieval failure (14 W&W records)

- _Tool returned nothing useful / failed to access the source_:
  - "WebSurfer's inability to reliably access the requested documents resulted in the overall task failure."
  - "FileSurfer failed to access the article due to a 404 File Not Found error."
  - "The search tool does not return the desired information regarding the passenger count of each train in 2019."

### N4 — Wrong tool selection (6 W&W records)

- _Right goal, wrong tool_:
  - "Using YouTube tools is more appropriate." (agent used a search tool instead)
  - "The agent writes code using pandas, which cannot handle the color data in the Excel file."
  - "The expert should not use OCR, and analyzing data is not the responsibility of the Validation_Expert."

### N5 — Invalid tool parameters / input (1 W&W record)

- _Right tool, wrong input_:
  - "The key word should include Monterey Bay Aquarium website."

### P1 — Improper task decomposition / bad plan (14 W&W records)

- _The plan itself is flawed; the task was misunderstood_:
  - "The plan to solve the problem is incorrect."
  - "The task description and focus were unrelated to the actual question of identifying cities based on university locations."
  - "The expert didn't import the necessary tables, leading to the exhaustion of the step limits." (architecturally wrong decomposition)

### P2 — Progress misassessment (15 W&W records)

- _Agent thinks it's done/on-track when it isn't_:
  - "The Orchestrator should not directly draw a conclusion if enough information has not been gathered to answer the query."
  - "The WebSurfer directly reaches a conclusion without performing the correct actions."
  - "GIS_DataAnalysis_Expert did not directly access the USGS database to verify the ZIP codes."

### P3 — Cascading error / explicit propagation (8 W&W records)

- _Flagged specifically because the reasoning text calls out downstream contamination_:
  - "The price provided by HawaiiRealEstate_Expert is incorrect, causing the error to propagate through subsequent steps to the final output."
  - "DataAnalysis_Expert wrote code with bugs, leading the following experts to follow the same method for extracting winner information in an incorrect way."
  - "The page retrieved by WebSurfer does not provide relevant information to address the question, causing the Orchestrator to rely on its own assumptions and make a guess."

### P4 — Constraint ignorance / unchecked assumption (3 W&W records)

- _Ignored a constraint or accepted an unverified value as fact_:
  - "The agent provides information about the current roster, but the question asks for the roster as of July 2023."
  - "The step assumed the extracted population value (56,583) was the 2020 estimate without verifying its accuracy or time frame."
  - "The conversation did not verify the exact recycling rate from the Wikipedia link…"

---

## Records flagged AMBIGUOUS — need your judgment

Four W&W records have reasoning text that's too sparse to classify with confidence. Please tell me how you'd like each handled (and I'll apply your call + update the spreadsheet).

1. **`WW-HC-14569e28-c88c-43e4-8c32-097d35b9a67d`** (step 12, WebSurfer)
   - "The reasoning process is wrong."
2. **`WW-AG-3f57289b-8c60-48be-bd80-01f8099ca449`** (step 8, Validation_Expert)
   - "Give the wrong final answer and directly reach an incorrect conclusion."
3. **`WW-AG-e0c10771-d627-4fd7-9694-05348e54ee36`** (step 1, Verification_Expert)
   - "The answer provided by Verification_Expert was incorrect."
4. **`WW-AG-a0068077-79f4-461a-adfe-75c1a4148545`** (step 5, Clinical_Trial_Data_Analysis_Expert)
   - "The answer provided by Clinical_Trial_Data_Analysis_Expert was incorrect."

My default suggestion for all four is **N1 (hallucination / factual fabrication)** — since the failure signature is "wrong answer delivered" without cascade language. But you might want to drop them from the eval entirely if the label is too thin to score against.

---

## Notable observations

1. **Goal drift (P5) and causal misattribution (P6) aren't represented** in this 158-record subset. The `CLAUDE.md` taxonomy listed them as expected categories, but neither AEB nor W&W annotators flagged any trajectory that way. We may need to adjust expectations for what the Google ADK eval can be scored on — or accept that these will only show up on different benchmarks.
2. **N2 (code bug) is the single largest W&W failure mode** — 24 of 108 W&W records are "code wrong / script wrong / DFS wrong / pandas wrong / etc." This reflects the multi-agent architecture of W&W (AutoGen / Magentic-One expert agents that write a lot of code). AEB doesn't exhibit this at all because its agents don't execute Python.
3. **AEB is process-heavy (39/50 = 78% process-level)**; **W&W is node-heavy (74/108 = 69% node-level)**. This matters for evaluation design: if the Google ADK eval is stress-tested only on AEB, we'll underrate how well it handles localized fabrication; if stress-tested only on W&W, we'll underrate cascading-error detection.
4. **The hardest case the eval has to get right** (per `CLAUDE.md` — process-level failure that originates early but surfaces late) is most represented by the **P3 cluster (12 records)**. Those are the rows where the reasoning text explicitly says "X caused Y downstream" — ideal eval candidates.

---

## Decisions applied (2026-04-17)

- **N1 and N2 kept separate** — rationale: test methodology differs. N2 (code bug) is runtime-verifiable by executing the code; N1 (hallucination) requires a ground-truth reference answer to detect fabrication.
- **All 4 ambiguous records dropped** — reasoning text was too thin to classify or to score the eval against. Final dataset size: **154 records**.
- **P4 (constraint ignorance) retained as its own cluster** — data-driven, doesn't fit any CLAUDE.md example category; that's acceptable per the working agreement.
- **P5 (goal drift) and P6 (causal misattribution) accepted as absent** from this library — no trajectories exhibit them; we don't fabricate examples.

The finalized classifications are embedded as `proposed_cluster` and `proposed_level` fields in the consolidated JSONL.

### Files

- [Consolidated dataset (JSONL, 154 rows)](computer:///Users/mel/Documents/GitHub/failure_experiment/data/consolidated/gaia_consolidated.jsonl) — now includes `proposed_cluster` and `proposed_level` on every record.
- [Per-record classification table (CSV)](computer:///Users/mel/Documents/GitHub/failure_experiment/data/consolidated/failure_classifications.csv)
