# EvalSet schema for failure attribution

Evaluators in this repo consume **Google ADK EvalSet JSON**. You can build EvalSets yourself or run the optional [benchmark build pipeline](../benchmark/README.md).

## Required shape

Each file is a JSON object with an `eval_cases` array. Every case needs:

| Field | Purpose |
|-------|---------|
| `eval_id` | Stable case identifier (string) |
| `conversation` | At least one ADK `Invocation` so the file validates as ADK JSON |
| `session_input` | ADK session stub (`app_name`, `user_id`, `state`) |
| `metadata.trajectory` | Full native message list the judges read |

For **scoring**, use a `*.with_gt.evalset.json` file and include `metadata.gt` on every case.

## Minimal example

See [`examples/minimal.with_gt.evalset.json`](../examples/minimal.with_gt.evalset.json).

```json
{
  "eval_set_id": "my_failures",
  "eval_cases": [
    {
      "eval_id": "case-001",
      "conversation": [ /* one synthetic Invocation */ ],
      "session_input": { "app_name": "my_app", "user_id": "u1", "state": {} },
      "metadata": {
        "trajectory": [
          {"role": "user", "content": "..."},
          {"role": "assistant", "content": "..."}
        ],
        "gt": {
          "critical_failure_step": 3,
          "proposed_cluster": "N1",
          "proposed_level": "node",
          "proposed_cluster_label": "Hallucination / factual fabrication"
        }
      }
    }
  ]
}
```

## Trajectory messages

Each entry in `metadata.trajectory` should include:

- `role`: `user`, `assistant`, or tool-specific roles your agent uses
- `content`: message text (string)
- `name` (optional): agent or tool name in multi-agent traces

Step indices are **1-based** and refer to positions in this list. Evaluators treat the earliest violating step as the failure origin.

## Ground truth (`gt`)

| Field | Type | Notes |
|-------|------|-------|
| `critical_failure_step` | int | 1-based index into `metadata.trajectory` |
| `proposed_cluster` | string | One of `N1`–`N5`, `P1`–`P4` (see [`config/taxonomy.json`](../config/taxonomy.json)) |
| `proposed_level` | `node` or `process` | Must match cluster family |
| `proposed_cluster_label` | string | Human-readable label (optional but recommended) |

Judge-visible EvalSets (`*.evalset.json` without `.with_gt`) must **omit** `metadata.gt` so labels never leak into prompts.

## Rubrics (baseline evaluator)

The rubric baseline reads [`config/rubrics/nine_cluster_rubric.json`](../config/rubrics/nine_cluster_rubric.json). Each rubric is a yes/no property aligned with one cluster.

## ADK compatibility notes

We store the full trace under `metadata` because ADK's native `Invocation` shape does not represent every multi-agent conversation cleanly. ADK loaders ignore unknown fields; custom evaluators read `metadata.trajectory` directly. See [`docs/adk_eval_suite_notes.md`](adk_eval_suite_notes.md).
