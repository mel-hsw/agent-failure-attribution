# Google ADK Evaluation Suite — Reference Notes

_Date: 2026-04-18 · Research notes compiled for Step 4 and paper drafting. Not a step deliverable; this is a factual reference of what ADK ships today and what it does not._

## Purpose

Catalogue what the Google ADK (Agent Development Kit) evaluation suite provides out of the box, so we can (a) use what's useful as-is in Step 4 and (b) cite it accurately when the paper describes the off-the-shelf baseline.

## Built-in evaluators

ADK registers evaluators via `MetricEvaluatorRegistry`. Five are currently shipped:

| Evaluator name | What it measures | Output | Notes for this project |
|---|---|---|---|
| `tool_trajectory_avg_score` (TrajectoryEvaluator) | Compares the agent's actual tool-call sequence against an `expected_tool_use` list. Match modes: EXACT, IN_ORDER, ANY_ORDER. | Per-invocation binary (1 if match, 0 otherwise), averaged across invocations. | Gives a "first divergence step" signal for free — but only if we can supply the expected trajectory. AEB / W&W do not ship expected trajectories. |
| `response_match_score` (ResponseEvaluator) | ROUGE-1 unigram overlap between agent's final response and a reference. | Float [0,1]; default threshold 0.8. | Purely lexical. Not appropriate for GAIA final-answer semantic matching. |
| `final_response_match_v2` | LLM-as-judge on semantic equivalence of final response vs reference. | Binary pass/fail (or confidence). Configurable judge model via `judge_model_options` (LiteLLM). | Useful as a failure-detector gate, not for attribution. |
| `rubric_based_final_response_quality_v1` | LLM-as-judge against a user-supplied rubric. **Reference-free**. | Per-rubric-item verdict. | Most adaptable built-in. Can be configured with our 9-cluster rubric to produce All-at-Once attribution without writing a new evaluator class. |
| `safety_v1` (SafetyEvaluator) | Harmful-content detection. | Pass/fail per safety dimension. | Not relevant to failure attribution. |

## EvalSet / EvalCase schema

ADK represents evaluation data as an `EvalSet` of `EvalCase`s. Each case carries:

- `conversation`: list of `Invocation`s, each with input, intermediate tool calls, and final response.
- `initial_session`: optional session state at start.
- `expected_tool_use`: flat list of tool names (strings) — no per-call argument structure.
- `reference`: golden final response string.
- Arbitrary metadata (unknown fields are ignored at load, addressable from a custom evaluator).

**Gap for this project**: no first-class fields for `origin_step`, `failure_category`, or `failure_level`. These must be stored as metadata and read by custom evaluators.

## Custom evaluator API

`Evaluator` is the abstract base class (`src/google/adk/evaluation/evaluator.py`).

```python
class Evaluator(ABC):
    async def evaluate_invocations(
        self,
        actual_invocations: List[Invocation],
        expected_invocations: Optional[List[Invocation]] = None,
    ) -> EvaluationResult: ...
```

`EvaluationResult` fields (observed): `score` (float), `status` (EvalStatus.PASSED/FAILED), `metric_name`, `details` (free-form, where we'll stash predicted origin step + category + evidence).

Register custom evaluators with `MetricEvaluatorRegistry`.

## Callbacks (6 hook points)

| Hook | Receives | Can return | Role for us |
|---|---|---|---|
| `before_agent_callback` | `CallbackContext` | `Content` to short-circuit, or `None` | Task-level dynamic constraint synthesis |
| `after_agent_callback` | `CallbackContext` | `Content` or `None` | Post-hoc validation-log capture |
| `before_model_callback` | `CallbackContext`, `LlmRequest` | `LlmResponse` to skip, or `None` | Per-turn instruction-following checks |
| `after_model_callback` | `CallbackContext`, `LlmResponse` | `LlmResponse` or `None` | Streaming IF checks (role, termination) |
| `before_tool_callback` | `BaseTool`, `args`, `ToolContext` | modified `args` or `None` | Tool-schema / precondition enforcement |
| `after_tool_callback` | `tool_result`, `ToolContext` | modified result or `None` | Postcondition / assertion logging |

Callbacks can emit events into the session's event bus — this is where AgentRx-style "validation logs" get assembled without extending ADK.

## Event bus / observability

Every significant runtime event (user message, agent reply, tool call, tool result, state change, error) is an immutable `google.adk.events.Event` with `invocation_id` and `event.id`. Stored in `session.events`. Third-party integrations (Arize, Langfuse, Phoenix, AgentOps) hook in via `BasePlugin` and `after_run_callback`. OpenTelemetry instrumentation available.

**Key point for the paper**: ADK emits execution traces but does not attach semantic failure-category metadata to events. That annotation is our job.

## Gaps (what ADK does not provide for failure attribution)

1. Per-step error localization — no built-in.
2. Cascading-error / error-propagation detection — no built-in.
3. Goal-drift / objective-divergence detection — no built-in.
4. Late-symptom bias penalty — no built-in.
5. Failure-taxonomy annotation schema in EvalCase — must be encoded in metadata.
6. Intermediate-step quality evaluation inside SequentialAgent / ParallelAgent — only root final response is scored.
7. Declarative constraint / rule engine analogous to AgentRx — callbacks are reactive, not a constraint synthesis layer.

## Practical usability for Step 4

| Built-in | Use directly? | Role in our pipeline |
|---|---|---|
| `rubric_based_final_response_quality_v1` | Yes | Primary off-the-shelf baseline — 9-cluster rubric = All-at-Once attribution |
| `final_response_match_v2` | Yes | Failure-detector gate (sanity check, not attribution) |
| `tool_trajectory_avg_score` | Only if we generate expected trajectories | Optional baseline for N4 / N5 node-level clusters |
| `response_match_score` | No | Lexical only; inadequate for GAIA |
| `safety_v1` | No | Unrelated |

Everything else (Step-by-Step attribution, Binary-Search attribution, constraint-grounded attribution, 3-part match scoring) requires custom `Evaluator` subclasses plus callbacks.

## Version

Notes based on `adk-python` v1.22.x / v1.23.0 as documented on 2026-04-18. ADK is active; re-verify before the paper's camera-ready.

## Primary sources

- [Why Evaluate Agents — ADK](https://google.github.io/adk-docs/evaluate/)
- [Criteria — ADK](https://google.github.io/adk-docs/evaluate/criteria/)
- [Callbacks — ADK](https://google.github.io/adk-docs/callbacks/)
- [Types of Callbacks — ADK](https://google.github.io/adk-docs/callbacks/types-of-callbacks/)
- [Events — ADK](https://google.github.io/adk-docs/events/)
- [evaluator.py — adk-python v1.23.0](https://github.com/google/adk-python/blob/v1.23.0/src/google/adk/evaluation/evaluator.py)
- [eval_metrics.py — adk-python v1.22.1](https://github.com/google/adk-python/blob/v1.22.1/src/google/adk/evaluation/eval_metrics.py)
- [custom_metric_evaluator.py — adk-python v1.23.0](https://github.com/google/adk-python/blob/v1.23.0/src/google/adk/evaluation/custom_metric_evaluator.py)
- [Evaluating Agents with ADK — Google Codelabs](https://codelabs.developers.google.com/adk-eval/instructions)
- [Tracing, Evaluation, and Observability for Google ADK — Arize](https://arize.com/blog/tracing-evaluation-and-observability-for-google-adk-how-to/)
