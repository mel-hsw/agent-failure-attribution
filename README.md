# Google ADK failure-attribution evaluators

Reference implementations for **localizing where agent trajectories fail** — predicting the earliest failure step and a failure category — using Google's Agent Development Kit (ADK) data format and Vertex AI batch judges.

This repo ships three evaluator patterns you can adapt to your own agents, plus a 133-case GAIA benchmark, ADK `EvalSet` JSON, and a reproducible Phase A–D pipeline.

**Task.** Given a failed trajectory, predict **origin step** + **failure cluster** (nine clusters: five node-level N1–N5, four process-level P1–P4).

## Three evaluators

| Config | Script | What it does | Best for |
|--------|--------|--------------|----------|
| **Baseline** | `phase_b_batch.py` | Off-the-shelf ADK-style rubric judge — 9 yes/no rubrics, one per cluster; no origin step | Showing what the default rubric path can and cannot do |
| **AllAtOnce** | `phase_c_all_at_once.py` | One-pass structured JSON judge over the full trajectory | Simple custom evaluator; good starting point |
| **ConstraintGrounded** | `phase_c_constraint_grounded.py` | Static violation log (Python) + two-pass LLM judge grounded in constraint evidence | Harder cases — especially process-level / modular traces |

All three read ADK `EvalSet` cases from `data/evalsets/`, submit Vertex batch jobs, and write `per_case.jsonl` + `summary.json` under `outputs/`.

> **Headline result on the bundled benchmark:** the Baseline recalls ~90% of node-level failures but only ~18% of process-level ones on the eval split. AllAtOnce and ConstraintGrounded narrow that gap; details in [`docs/reports/step4_results.md`](docs/reports/step4_results.md).

## Quickstart

**Prerequisites:** Python 3.10+, a GCP project with Vertex AI enabled, Application Default Credentials (`gcloud auth application-default login`), and a GCS bucket for batch I/O (default `agenttracebucket` — override with `--bucket`).

```bash
git clone https://github.com/mel-hsw/agent-failure-attribution.git
cd agent-failure-attribution

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — at minimum set GOOGLE_CLOUD_PROJECT
```

Verify the bundled data and EvalSets (no Vertex calls):

```bash
python3 scripts/phase_a_verify.py   # must exit 0
```

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
# Full eval split (123 cases) — expect long batch runtimes
python3 scripts/phase_b_batch.py --split eval
python3 scripts/phase_c_all_at_once.py --split eval
python3 scripts/phase_c_constraint_grounded.py --split eval

# Re-parse predictions if batch row order drifted
python3 scripts/reparse_batch.py --phase b --predictions outputs/phase_b_batch/eval/<run-id>/predictions.jsonl
```

Common flags (all Phase B/C batch scripts): `--judge-model` (default `gemini-3.1-pro-preview`), `--bucket`, `--gcs-prefix`, `--limit`. Preview models use location `global` (set automatically).

## Adapting to your trajectories

1. **Format** — Build ADK `EvalSet` JSON with one `eval_case` per failed trajectory. See the bundled files in `data/evalsets/` for the metadata shape (`gt` lives only in `*.with_gt.evalset.json`).
2. **Baseline rubrics** — Edit or replace `data/rubrics/option_b_rubric.json` (one rubric per failure cluster).
3. **Custom judges** — Copy prompt + schema logic from `phase_c_all_at_once.py` or the two-pass flow in `phase_c_constraint_grounded.py`. Shared batch plumbing is in `scripts/batch_utils.py`.
4. **Static constraints** — `scripts/trajectory_replayer.py` implements Tier-1 heuristics used by ConstraintGrounded pass 0.

For what ADK ships out of the box vs what you must add yourself, see [`docs/reports/adk_eval_suite_notes.md`](docs/reports/adk_eval_suite_notes.md).

## Bundled benchmark

| Asset | Location |
|-------|----------|
| 133 labelled trajectories | `data/consolidated/` — see [`data/consolidated/README.md`](data/consolidated/README.md) |
| dev / calibration / eval splits | `data/splits/` |
| ADK EvalSets (judge + with_gt) | `data/evalsets/` |
| Phase B rubric definition | `data/rubrics/option_b_rubric.json` |

Primary sources for rebuilding from scratch (optional): `data/AgentErrorBench/`, `data/Who_and_When/` via `scripts/consolidate.py` and `scripts/finalize.py`.

See [Data sources & attribution](#data-sources--attribution) for upstream repos and citation info.

## Data sources & attribution

The bundled benchmark is a **derived GAIA-only subset** of two upstream failure-annotation libraries, unified into a single schema and 9-cluster taxonomy in this repo. Trajectories use tasks from the [GAIA benchmark](https://huggingface.co/datasets/gaia-benchmark/GAIA); failure labels come from the sources below.

| Source | Upstream | What we use | Local copy |
|--------|----------|-------------|------------|
| **AgentErrorBench** | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) | 50 GAIA failure trajectories (single-agent; GPT-4o, Llama3.3-70B, Qwen3-8B) | `data/AgentErrorBench/` |
| **Who&When** | [ag2ai/Agents_Failure_Attribution](https://github.com/ag2ai/Agents_Failure_Attribution) · [HF dataset](https://huggingface.co/datasets/Kevin355/Who_and_When) | Hand-Crafted + Algorithm-Generated splits; GAIA UUID rows only (AssistantBench excluded) | `data/Who_and_When/` |
| **GAIA** (task substrate) | [gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA) | Underlying questions/tasks referenced by both libraries | — |

This repo's consolidated labels (`data/consolidated/`), splits, and EvalSets are **new derivatives** — not redistributions of the upstream annotation formats. If you use the benchmark or results, please cite the upstream works:

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

Per-source READMEs: [`data/AgentErrorBench/README.md`](data/AgentErrorBench/README.md), [`data/Who_and_When/README.md`](data/Who_and_When/README.md), [`data/consolidated/README.md`](data/consolidated/README.md).

## Repository layout

```
.
├── README.md
├── requirements.txt
├── .env.example
├── data/
│   ├── consolidated/       # 133-record benchmark
│   ├── splits/             # dev (5) / calibration (5) / eval (123)
│   ├── evalsets/           # ADK EvalSet JSON
│   └── rubrics/            # Baseline rubric set
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
└── outputs/                # gitignored — run artifacts
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
| `phase_c_binary_search.py` | Step-localization via binary search — implemented, not in the paper comparison |
| `phase_c_all_at_once_v3.py` | Prompt variant (rejected in paper runs) |
| `scripts/archive/render_dev_review.py` | Side-by-side dev review HTML |
