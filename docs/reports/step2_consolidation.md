# Step 2 — Consolidation Report

_Date: 2026-04-17 · Output: `data/consolidated/gaia_consolidated.jsonl`_

## Final counts

| Source | Records |
|---|---|
| AgentErrorBench | 50 |
| Who_and_When / Hand-Crafted (GAIA only) | 30 |
| Who_and_When / Algorithm-Generated (GAIA only, post-dedup) | 78 |
| **Total consolidated GAIA trajectories** | **158** |

## Rules applied

1. **GAIA-only filter** — kept AEB rows where `task_type == "gaia"` (all 50), kept W&W rows with UUID-format `question_ID`. Dropped 56 AssistantBench rows (28 AG + 28 HC).
2. **W&W dedup** — 20 GAIA question_IDs appeared in both Hand-Crafted and Algorithm-Generated. Per your decision, Hand-Crafted wins; those 20 AG rows were dropped.
3. **Normalizations**
   - AEB `failure_type`: stripped + lowercased → `Parameter_error` → `parameter_error` and `"tool_execution_error "` → `tool_execution_error`.
   - W&W `mistake_agent`: canonical casing → `Websurfer` → `WebSurfer`.
   - W&W `mistake_step`: cast from string to int.
4. **Schema unification**: `is_correct`/`is_corrected` merged, `ground_truth`/`groundtruth` merged, Hand-Crafted history entries get `name: null` to match the Algorithm-Generated shape.
5. **Full trajectory attachment** — for AEB rows, the full 30-step `messages` list from `data/AgentErrorBench/GAIA/*.json` was joined in so the evaluation suite has the entire trace, not just the single annotated step.

## Verification checks (all passed)

- Total records: 158.
- Duplicate `trajectory_id`s: 0.
- AssistantBench (hex64) IDs leaked through: 0.
- W&W GAIA question_IDs appearing twice: 0.
- Records missing `critical_failure_step`: 0.
- Records missing `failure_reasoning_text`: 0.
- AEB `raw_failure_type` strings still not normalized: 0.
- Rows still carrying pre-normalization `'Websurfer'`: 0.
- W&W rows with non-int `critical_failure_step`: 0.

## AEB failure-type distribution after normalization

`inefficient_plan` 18 · `outcome_misinterpretation` 5 · `constraint_ignorance` 4 · `over_simplification` 4 · `impossible_action` 4 · `progress_misjudge` 4 · `misalignment` 3 · `parameter_error` 3 · `tool_execution_error` 3 · `hallucination` 1 · `llm_limit` 1.

(`Parameter_error` and `tool_execution_error ` duplicates are now merged, taking those two cells from 2+1 pairs down to single normalized values as expected.)

## Origin-step distribution across all 158 trajectories

Step 0–2: 64 records · step 3–5: 53 · step 6–10: 23 · step 11+: 18 (max 51).

Notable shift vs AEB-only: W&W contributes a long tail of late-origin failures (up to step 51), which matters for Step 3 because process-level failures that originate early *but surface late* are the hardest case for the evaluation suite.

## Consolidated record schema

Each line in `gaia_consolidated.jsonl` has:

```
source                    : "AgentErrorBench" | "WhoAndWhen-HandCrafted" | "WhoAndWhen-AlgorithmGenerated"
trajectory_id             : unique identifier
gaia_question_id          : GAIA UUID (W&W rows) — AEB rows carry a UUID-prefix field instead
llm                       : model name (AEB only)
agent_role                : mistake_agent (W&W) or critical_failure_module (AEB)
history                   : full trajectory as [{role, name, content}, ...]
ground_truth              : correct answer (W&W only)
critical_failure_step     : int — the failure-origin step (ground truth for Google ADK eval)
critical_failure_module   : planning | action | memory | reflection | system (AEB only)
raw_failure_type          : normalized AEB failure_type or W&W mistake_type (mostly null for W&W)
failure_reasoning_text    : free-text description of why this step is the failure origin
metadata                  : source-specific extras (question, is_correct, AEB run metadata)
```

This is the file the evaluation suite will be run against in later steps.

## Ready for Step 3

In Step 3 we'll enumerate every distinct failure label / reasoning signature present in the 158 records and map them onto the node-level vs process-level taxonomy in `CLAUDE.md`. I'll surface a list of failure types with 1–2 representative `failure_reasoning_text` excerpts each so you can sanity-check the node/process classifications before we commit them.
