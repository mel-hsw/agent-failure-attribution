# Consolidated benchmark (local build output)

JSONL and EvalSet files built from upstream sources live here **locally only**. They are gitignored and must not be republished from this repo.

## What this repo tracks instead

| File | Purpose |
|------|---------|
| `cluster_review_patch.jsonl` | Row-level taxonomy review (DROP / FLAG / relabel) applied during Phase A clean |
| (generated locally) `gaia_consolidated*.jsonl` | Consolidated trajectories + labels |
| (generated locally) `failure_classifications.csv` | Human-readable classification export |

Split assignment for reproducibility: `data/splits/split_manifest.json` (trajectory IDs + seed only, no trajectory text).

## Build locally

After fetching upstream data (see root [README](../../README.md#data-sources-not-redistributed)):

```bash
python3 scripts/consolidate.py
python3 scripts/finalize.py
python3 scripts/phase_a_clean.py
python3 scripts/phase_a_split.py
python3 scripts/phase_a_build_evalset.py
python3 scripts/phase_a_verify.py   # must exit 0
```

Or run `phase_a_verify.py` alone: it re-runs the Phase A scripts and checks outputs.

## Upstream sources

| Source | Repository |
|--------|------------|
| AgentErrorBench | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) |
| Who&When | [ag2ai/Agents_Failure_Attribution](https://github.com/ag2ai/Agents_Failure_Attribution) · [HF dataset](https://huggingface.co/datasets/Kevin355/Who_and_When) |
| GAIA (tasks) | [gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA) |

Construction notes: `docs/reports/step1_data_cleaning.md` through `step3_taxonomy_review.md`.
