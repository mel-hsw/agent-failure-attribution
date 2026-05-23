# Google ADK failure-attribution evaluators

Reference implementations for **localizing where agent trajectories fail**: predict the earliest failure step and a failure category using Google's Agent Development Kit (ADK) EvalSet format and Vertex AI batch judges.

Bring your own failed trajectories as ADK EvalSets, or optionally rebuild the GAIA consolidation benchmark from upstream sources. **This repo does not ship trajectory data**; see [Data attribution](docs/data_attribution.md).

**Task.** Given a failed trajectory, predict **origin step** + **failure cluster** (nine clusters: five node-level N1–N5, four process-level P1–P4).

## Quickstart (your trajectories)

**Prerequisites:** Python 3.10+, GCP project with Vertex AI, Application Default Credentials (`gcloud auth application-default login`), and a GCS bucket for batch I/O (default `agenttracebucket`; override with `--bucket`).

```bash
git clone https://github.com/mel-hsw/agent-failure-attribution.git
cd agent-failure-attribution

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: set GOOGLE_CLOUD_PROJECT at minimum
```

Run on the included synthetic example:

```bash
python3 evaluators/rubric_baseline.py --evalset examples/minimal.with_gt.evalset.json --limit 1
python3 evaluators/all_at_once.py --evalset examples/minimal.with_gt.evalset.json --limit 1
python3 evaluators/constraint_grounded.py --evalset examples/minimal.with_gt.evalset.json --limit 1
```

Or use the helper script: `bash examples/run_smoke.sh`

Each evaluator uploads batch input to GCS, polls the Vertex batch job, downloads predictions, and writes `per_case.jsonl` + `summary.json` under `outputs/`.

## Three evaluators

### Baseline (`evaluators/rubric_baseline.py`)

Off-the-shelf ADK-style rubric judge: nine yes/no rubrics, one per cluster; no origin step. Shows what the default rubric path can and cannot do.

### AllAtOnce (`evaluators/all_at_once.py`)

One-pass structured JSON judge over the full trajectory. Simplest custom evaluator; good starting point for your own agents.

### ConstraintGrounded (`evaluators/constraint_grounded.py`)

Static violation log (Python) plus a two-pass LLM judge grounded in constraint evidence. Best for harder cases, especially process-level and modular traces.

## Scoring a run

After you have `per_case.jsonl` outputs:

```bash
python3 evaluators/scorecard.py
```

Default output: `outputs/scorecards/scorecard.md`

## Adapting to your trajectories

1. **Format:** Build ADK EvalSet JSON per [`docs/evalset_schema.md`](docs/evalset_schema.md). Ground truth belongs in `*.with_gt.evalset.json` only.
2. **Rubrics:** Edit [`config/rubrics/nine_cluster_rubric.json`](config/rubrics/nine_cluster_rubric.json).
3. **Taxonomy:** Cluster definitions in [`config/taxonomy.json`](config/taxonomy.json).
4. **Custom judges:** Copy prompt logic from `evaluators/all_at_once.py` or the two-pass flow in `evaluators/constraint_grounded.py`. Shared batch plumbing is in `evaluators/batch_utils.py`.
5. **Static constraints:** `evaluators/trajectory_replayer.py` implements Tier-1 heuristics for ConstraintGrounded pass 0.

For what ADK ships out of the box vs what you must add, see [`docs/adk_eval_suite_notes.md`](docs/adk_eval_suite_notes.md).

## Optional: GAIA benchmark reproduction

To reproduce the 133-case eval split from AgentErrorBench + Who&When:

1. Download upstream data ([`docs/data_attribution.md`](docs/data_attribution.md)).
2. Run the build pipeline ([`benchmark/README.md`](benchmark/README.md)).
3. Evaluate with `--split eval` instead of `--evalset`:

```bash
python3 evaluators/rubric_baseline.py --split eval
python3 evaluators/all_at_once.py --split eval
python3 evaluators/constraint_grounded.py --split eval
```

Set `BENCHMARK_DATA_DIR` if data lives outside `local/benchmark/`.

## Repository layout

```
.
├── README.md
├── requirements.txt
├── .env.example
├── config/
│   ├── rubrics/nine_cluster_rubric.json
│   └── taxonomy.json
├── evaluators/              # Vertex batch judges + scorecard
├── examples/                # Synthetic EvalSets + run_smoke.sh
├── benchmark/
│   ├── README.md            # Optional GAIA build pipeline
│   ├── build/               # consolidate, Phase A scripts
│   └── refs/                # Split manifest, taxonomy patch (no trajectories)
├── docs/
│   ├── evalset_schema.md
│   ├── data_attribution.md
│   └── adk_eval_suite_notes.md
├── local/                   # gitignored; default BENCHMARK_DATA_DIR
└── outputs/                 # gitignored; run artifacts
```

## CLI reference

All three evaluators accept:

| Flag | Purpose |
|------|---------|
| `--evalset PATH` | ADK EvalSet JSON (primary path for BYO data) |
| `--split {dev,calibration,eval}` | Benchmark split (requires built evalsets) |
| `--data-dir PATH` | Override `BENCHMARK_DATA_DIR` |
| `--output PATH` | Output directory |
| `--limit N` | Cap cases (smoke tests) |
| `--judge-model` | Default `gemini-3.1-pro-preview` |
| `--bucket`, `--gcs-prefix` | GCS batch I/O |

Re-parse predictions if batch row order drifted:

```bash
python3 evaluators/reparse_batch.py --phase b --predictions outputs/rubric_baseline/eval/<run-id>/predictions.jsonl
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `GOOGLE_GENAI_USE_VERTEXAI` | Must be `True` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | `global` for preview models |
| `BENCHMARK_DATA_DIR` | Optional; benchmark artifacts outside repo |

Batch artifacts default to `gs://agenttracebucket/<phase>/<run-id>/`.

## Data attribution

Benchmark trajectories come from [AgentErrorBench](https://github.com/ulab-uiuc/AgentDebug), [Who&When](https://huggingface.co/datasets/Kevin355/Who_and_When), and [GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA). Download instructions and citations: [`docs/data_attribution.md`](docs/data_attribution.md).
