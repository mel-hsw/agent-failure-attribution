# Step 1 — Data Cleaning Report

_Date: 2026-04-17 · Scope: AgentErrorBench + Who_and_When_

## Summary

| Source | Total rows | GAIA rows | Other-benchmark rows | Has standardized failure label? |
|---|---|---|---|---|
| AgentErrorBench (`gaia_labels.json`) | 50 | 50 | 0 | Yes (per-module `failure_type`) |
| Who_and_When / Algorithm-Generated | 126 | 98 | 28 (AssistantBench) | No (`mistake_reason` is free text) |
| Who_and_When / Hand-Crafted | 58 | 30 | 28 (AssistantBench) | Partial (`mistake_type` set on 4/58 rows) |
| **GAIA-only consolidated total (after Step 2)** | — | **178** | — | — |

## How GAIA was identified

- **AgentErrorBench**: every record's `task_type` field is already `"gaia"` — no filtering needed.
- **Who_and_When**: the `question_ID` field is the discriminator. UUID-format IDs (`8-4-4-4-12` hex) are GAIA; 64-char SHA-256-style hex IDs are AssistantBench. Sampled questions confirm this: UUIDs map to canonical GAIA-style multi-hop research questions ("How many edits were made to the Wikipedia page on Antidisestablishmentarianism…"), hex IDs map to AssistantBench-style web tasks ("Which gyms in West Virginia within 5 miles of the Mothman Museum…").
- Note: there is **zero overlap** between the 10 unique GAIA UUIDs in AgentErrorBench and the 128 GAIA UUIDs in Who_and_When — they cover different GAIA tasks, so no de-duplication will be needed in Step 2.

## AgentErrorBench — schema and label inventory

Each record:
```
trajectory_id, LLM, task_type, critical_failure_step, critical_failure_module, step_annotations[]
```

LLM coverage (50 trajectories): GPT-4o 16, Llama3.3-70B-Turbo 17, Qwen3-8B 17.

`critical_failure_module` distribution: planning 26, reflection 9, action 6, memory 5, system 4.

`critical_failure_step` distribution: most failures are early (step 1: 9, step 2: 13, step 3: 6, step 4: 10, step 5: 5; long-tail to step 10).

Standardized `failure_type` values found (after normalization):

| Module | Failure type | Count |
|---|---|---|
| planning | inefficient_plan | 18 |
| planning | constraint_ignorance | 4 |
| planning | impossible_action | 4 |
| action | misalignment | 3 |
| action | parameter_error | 3 |
| memory | over_simplification | 4 |
| memory | hallucination | 1 |
| reflection | outcome_misinterpretation | 5 |
| reflection | progress_misjudge | 4 |
| system | tool_execution_error | 3 |
| system | llm_limit | 1 |

Each annotation also carries a free-text `reasoning` field that paraphrases the failure (e.g. "Inefficient plan by redo similar stuffs", "misinterpretation of the result as it was successful").

### Data-quality issues found

| Issue | Field | Variant(s) | Records affected | Recommended fix |
|---|---|---|---|---|
| Capitalization mismatch | `step_annotations[*].action.failure_type` | `Parameter_error` vs `parameter_error` | 1 | Lowercase-normalize to `parameter_error` |
| Trailing whitespace | `step_annotations[*].system.failure_type` | `tool_execution_error ` vs `tool_execution_error` | 1 | `.strip()` during ingest |

No missing-field issues. No duplicate `trajectory_id`s.

## Who_and_When — schema and label inventory

Each split is a Hugging Face Arrow dataset with a `train` split and **only failure cases** (`is_correct`/`is_corrected` is `False` for every row).

### Schema divergence between the two splits

| Field | Algorithm-Generated | Hand-Crafted | Notes |
|---|---|---|---|
| Correctness flag | `is_correct` | `is_corrected` | Rename to a single field on consolidation |
| Ground truth | `ground_truth` | `groundtruth` | Rename to a single field on consolidation |
| `history` element shape | `{role, name, content}` | `{role, content}` | AG carries an extra `name` field |
| `mistake_type` | _absent_ | present (but mostly null) | See below |

### Failure-label situation

- **Algorithm-Generated has no standardized failure-type field** — only the free-text `mistake_reason` (avg 124 chars, no nulls).
- **Hand-Crafted has a `mistake_type` field, but it is effectively unusable as-is**: 54/58 rows are `"None"`, the remaining 4 are ad-hoc strings (`wrong_reasoning` ×2, `Processing Error` ×1, `Tool failure` ×1). This matches the project assumption that Who_and_When labels are not standardized.

→ **Step 3 will need to derive failure types from `mistake_reason` text** rather than rely on the existing `mistake_type` column.

### Multi-agent role distributions (where the failure originated)

Algorithm-Generated `mistake_agent` (top): Verification_Expert 18, PythonDebugging_Expert 7, DataAnalysis_Expert 6, DataVerification_Expert 5, Validation_Expert 5, WebServing_Expert 4, … (40+ unique "Expert" agent names — looks AutoGen / Magentic-style).

Hand-Crafted `mistake_agent`: WebSurfer 31, Orchestrator 18, Assistant 4, FileSurfer 3, Websurfer 2 (note capitalization issue).

### Other data-quality issues

| Issue | Field | Detail | Recommended fix |
|---|---|---|---|
| Capitalization mismatch | `mistake_agent` (Hand-Crafted) | `WebSurfer` ×31 vs `Websurfer` ×2 | Title-case-normalize |
| Type inconsistency | `mistake_step` (both splits) | Stored as string ("0".."82"), all int-castable | Cast to int on ingest |
| Field-name divergence | `is_correct`/`is_corrected`, `ground_truth`/`groundtruth` | Splits use different names | Rename to common schema |
| `history` shape divergence | `history[].name` only in AG | Hand-Crafted records lack `name` | Default missing `name` to `null` |
| Effectively-null `mistake_type` | Hand-Crafted | 54/58 are `"None"` (string, not actual null) | Treat as missing; rely on `mistake_reason` |

## Recommended consolidated schema (target for Step 2)

```
{
  "source": "AgentErrorBench" | "WhoAndWhen-AlgorithmGenerated" | "WhoAndWhen-HandCrafted",
  "trajectory_id": str,         // AEB: trajectory_id; W&W: question_ID + run salt
  "gaia_question_id": str,      // UUID format
  "llm": str | null,            // AEB only
  "agent_role": str | null,     // W&W: mistake_agent (normalized capitalization)
  "history": [ { "role": str, "name": str|null, "content": str } ],
  "ground_truth": str,
  "critical_failure_step": int,
  "critical_failure_module": str | null,    // AEB: planning/action/memory/reflection/system
  "raw_failure_type": str | null,           // AEB failure_type (normalized) OR W&W mistake_type
  "failure_reasoning_text": str             // AEB reasoning OR W&W mistake_reason
}
```

A second pass (Step 3) will then add a `normalized_failure_label` and `taxonomy_level` (`node` vs `process`) by mapping `raw_failure_type` and `failure_reasoning_text` onto the unified taxonomy in `CLAUDE.md`.

## Open questions for Mel before Step 2

1. **W&W same GAIA question, multiple traces?** Several AG records share UUIDs across runs (e.g. `a1e91b78-…` appears in both Algorithm-Generated and Hand-Crafted). Confirm: should we keep them as independent trajectories, or de-duplicate to one per GAIA question?
2. **AssistantBench records** (56 rows total across W&W) — confirm we're dropping them entirely per the GAIA-only scope, rather than parking them for a later cross-benchmark comparison.
3. **AEB step granularity** — every AEB record carries exactly one `step_annotation` covering the *critical* step only. Is that single-annotation-per-trajectory format sufficient for the Google eval suite, or do we need to back-fill per-step annotations from the trajectory itself?
