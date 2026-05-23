# Google ADK failure-attribution evaluators

Reference implementations for **localizing where agent trajectories fail**: predict the earliest failure step and a failure category using Google's Agent Development Kit (ADK) data format and Vertex AI batch judges.

This repo ships three evaluator patterns you can adapt to your own agents, plus a reproducible Phase A–D pipeline. Trajectory data is not included; see [Data sources](#data-sources).

**Task.** Given a failed trajectory, predict **origin step** + **failure cluster** (nine clusters: five node-level N1–N5, four process-level P1–P4).

## Three evaluators

### Baseline (`phase_b_batch.py`)

Off-the-shelf ADK-style rubric judge: 9 yes/no rubrics, one per cluster; no origin step. Use this to show what the default rubric path can and cannot do.

### AllAtOnce (`phase_c_all_at_once.py`)

One-pass structured JSON judge over the full trajectory. Simplest custom evaluator; good starting point for your own agents.

### ConstraintGrounded (`phase_c_constraint_grounded.py`)

Static violation log (Python) plus a two-pass LLM judge grounded in constraint evidence. Best for harder cases, especially process-level and modular traces.

All three read ADK `EvalSet` cases from `data/evalsets/`, submit Vertex batch jobs, and write `per_case.jsonl` + `summary.json` under `outputs/`.

> **Headline result (133-case eval split):** the Baseline recalls ~90% of node-level failures but only ~18% of process-level ones. AllAtOnce and ConstraintGrounded narrow that gap; details in [`docs/reports/step4_results.md`](docs/reports/step4_results.md).

## Quickstart

**Prerequisites:** Python 3.10+, a GCP project with Vertex AI enabled, Application Default Credentials (`gcloud auth application-default login`), and a GCS bucket for batch I/O (default `agenttracebucket`; override with `--bucket`).

```bash
git clone https://github.com/mel-hsw/agent-failure-attribution.git
cd agent-failure-attribution

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env: at minimum set GOOGLE_CLOUD_PROJECT
```

### 1. Prepare data

Download the benchmark inputs listed under [Data sources](#data-sources), then build EvalSets locally:

```bash
python3 scripts/consolidate.py
python3 scripts/finalize.py
python3 scripts/phase_a_verify.py   # re-runs Phase A and must exit 0
```

This writes consolidated JSONL, splits, and ADK EvalSets under `data/` (gitignored).

### 2. Run evaluators

Smoke-test each evaluator on the 5-case dev split:

```bash
python3 scripts/phase_b_batch.py --split dev --limit 5
python3 scripts/phase_c_all_at_once.py --split dev --limit 5
python3 scripts/phase_c_constraint_grounded.py --split dev --limit 3
```

Each script uploads batch input to GCS, polls the Vertex batch job, downloads predictions, and writes results to `outputs/phase_*/`.

Score a run (after you have `per_case.jsonl` outputs):

```bash
python3 scripts/phase_d_scorecard.py
```

## Running at scale

```bash
# Full eval split (123 cases); expect long batch runtimes
python3 scripts/phase_b_batch.py --split eval
python3 scripts/phase_c_all_at_once.py --split eval
python3 scripts/phase_c_constraint_grounded.py --split eval

# Re-parse predictions if batch row order drifted
python3 scripts/reparse_batch.py --phase b --predictions outputs/phase_b_batch/eval/<run-id>/predictions.jsonl
```

Common flags (all Phase B/C batch scripts): `--judge-model` (default `gemini-3.1-pro-preview`), `--bucket`, `--gcs-prefix`, `--limit`. Preview models use location `global` (set automatically).

## Adapting to your trajectories

1. **Format:** Build ADK `EvalSet` JSON with one `eval_case` per failed trajectory. After `phase_a_build_evalset.py`, see `data/evalsets/` for the metadata shape (`gt` lives only in `*.with_gt.evalset.json`).
2. **Baseline rubrics:** Edit or replace `data/rubrics/option_b_rubric.json` (one rubric per failure cluster).
3. **Custom judges:** Copy prompt + schema logic from `phase_c_all_at_once.py` or the two-pass flow in `phase_c_constraint_grounded.py`. Shared batch plumbing is in `scripts/batch_utils.py`.
4. **Static constraints:** `scripts/trajectory_replayer.py` implements Tier-1 heuristics used by ConstraintGrounded pass 0.

For what ADK ships out of the box vs what you must add yourself, see [`docs/reports/adk_eval_suite_notes.md`](docs/reports/adk_eval_suite_notes.md).

## What is in this repo

| Tracked in git | Purpose |
|----------------|---------|
| `scripts/` | Evaluators, consolidation, Phase A–D pipeline |
| `data/rubrics/` | Phase B rubric definition |
| `data/splits/split_manifest.json` | Split seed + trajectory IDs (no trajectory text) |
| `data/consolidated/cluster_review_patch.jsonl` | Taxonomy review decisions for Phase A clean |
| `docs/`, `paper/draft/` | Methods, results, paper draft |

| Local only (gitignored) | Purpose |
|-------------------------|---------|
| `data/` (except rubrics, split manifest, review patch) | Downloaded + built benchmark artifacts |
| `outputs/` | Evaluation run artifacts |

## Data sources

This repo publishes **evaluator code only**. Benchmark trajectories belong to the projects below; fetch them locally and do not republish via this repository.

| Dataset | Source | Notes |
|---------|--------|-------|
| **AgentErrorBench** | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) | GAIA slice → `data/AgentErrorBench/` ([README](data/AgentErrorBench/README.md)) |
| **Who&When** | [Kevin355/Who_and_When](https://huggingface.co/datasets/Kevin355/Who_and_When) | HF export → `data/Who_and_When/` ([README](data/Who_and_When/README.md)) |
| **GAIA** | [gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA) | Task substrate for both libraries |

**Who&When (Hugging Face):**

```python
from datasets import load_dataset

load_dataset("Kevin355/Who_and_When", "Hand-Crafted").save_to_disk("data/Who_and_When/Hand-Crafted")
load_dataset("Kevin355/Who_and_When", "Algorithm-Generated").save_to_disk("data/Who_and_When/Algorithm-Generated")
```

**AgentErrorBench:** follow [AgentDebug](https://github.com/ulab-uiuc/AgentDebug) download instructions for the GAIA labels + trajectory files.

Consolidation details: [`data/consolidated/README.md`](data/consolidated/README.md), `docs/reports/step1_data_cleaning.md` through `step3_taxonomy_review.md`.

### Citation

If you use the upstream datasets or reproduce the reported numbers, cite:

```bibtex
@article{zhu2025agentdebug,
  title={Where LLM Agents Fail and How They Can Learn From Failures},
  author={Zhu, Kunlun and Liu, Zijia and Li, Bingxuan and others},
  journal={arXiv preprint arXiv:2509.25370},
  year={2025}
}

@inproceedings{zhang2025which,
  title={Which Agent Causes Task Failures and When? On Automated Failure Attribution of {LLM} Multi-Agent Systems},
  author={Zhang, Shaokun and Yin, Ming and Zhang, Jieyu and others},
  booktitle={Forty-second International Conference on Machine Learning},
  year={2025},
  url={https://openreview.net/forum?id=GazlTYxZss}
}

@article{mialon2023gaia,
  title={{GAIA}: a benchmark for General {AI} Assistants},
  author={Mialon, Gr{\'e}goire and Fourrier, Cl{\'e}mentine and Swift, Craig and Wolf, Thomas and LeCun, Yann and Scialom, Thomas},
  journal={arXiv preprint arXiv:2311.12983},
  year={2023}
}
```

## Repository layout

```
.
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   ├── consolidated/       # local build output
│   ├── splits/
│   ├── evalsets/
│   └── rubrics/
├── scripts/
│   ├── batch_utils.py      # Vertex batch + GCS helpers
│   ├── phase_a_*.py        # Clean, split, build evalsets, verify
│   ├── phase_b_batch.py    # Baseline
│   ├── phase_c_all_at_once.py
│   ├── phase_c_constraint_grounded.py
│   ├── phase_d_scorecard.py
│   ├── trajectory_replayer.py
│   └── archive/            # Retired experiments and smoke tests
├── docs/reports/           # Methods, scorecards, ADK reference notes
├── paper/draft/            # Academic write-up (companion to this repo)
└── outputs/                # gitignored; run artifacts
```

## Configuration

| Variable | Purpose |
|----------|---------|
| `GOOGLE_GENAI_USE_VERTEXAI` | Must be `True` |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | `global` for preview models (scripts set this) |

Batch artifacts default to `gs://agenttracebucket/<phase>/<run-id>/`. Ensure your service account can read/write the bucket, or pass `--bucket` / `--gcs-prefix`.

## Documentation

| Topic | File |
|-------|------|
| ADK built-ins vs gaps | [`docs/reports/adk_eval_suite_notes.md`](docs/reports/adk_eval_suite_notes.md) |
| Results and scorecards | [`docs/reports/step4_results.md`](docs/reports/step4_results.md), [`step4_scorecard.md`](docs/reports/step4_scorecard.md) |
| Dataset construction | [`step1_data_cleaning.md`](docs/reports/step1_data_cleaning.md) → [`step3_taxonomy_review.md`](docs/reports/step3_taxonomy_review.md) |
| Evaluation protocol | [`step4_plan.md`](docs/reports/step4_plan.md) |
| Paper draft | [`paper/draft/draft.md`](paper/draft/draft.md) |

## Other scripts

| Script | Notes |
|--------|-------|
| `phase_c_binary_search.py` | Step-localization via binary search; implemented, not in the paper comparison |
| `phase_c_all_at_once_v3.py` | Prompt variant (rejected in paper runs) |
| `scripts/archive/render_dev_review.py` | Side-by-side dev review HTML |
