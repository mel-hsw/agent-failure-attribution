# GAIA benchmark build (optional)

Use this pipeline when you want to **reproduce paper-scale numbers** on the AgentErrorBench + Who&When GAIA consolidation. For your own agents, skip this and pass `--evalset` directly (see root [README](../README.md)).

## Prerequisites

1. Download upstream data per [`docs/data_attribution.md`](../docs/data_attribution.md).
2. Set `BENCHMARK_DATA_DIR` (optional; defaults to `local/benchmark/` at repo root).
3. Python deps from root `requirements.txt` (`datasets`, etc.).

## Directory layout

```
$BENCHMARK_DATA_DIR/
├── raw/agenterrorbench/     # gaia_labels.json + GAIA/*.json
├── raw/who_and_when/        # Hand-Crafted/ + Algorithm-Generated/
├── consolidated/            # JSONL build outputs
├── splits/
└── evalsets/
```

Repo-tracked references (no trajectory text):

- [`refs/split_manifest.json`](refs/split_manifest.json)
- [`refs/cluster_review_patch.jsonl`](refs/cluster_review_patch.jsonl)

## Build steps

From the repository root:

```bash
export BENCHMARK_DATA_DIR="${BENCHMARK_DATA_DIR:-$(pwd)/local/benchmark}"

python3 benchmark/build/consolidate.py
python3 benchmark/build/finalize.py      # optional taxonomy CSV pass
python3 benchmark/build/phase_a_clean.py
python3 benchmark/build/phase_a_split.py
python3 benchmark/build/phase_a_build_evalset.py
```

End-to-end verification (re-runs clean → split → evalsets and validates outputs):

```bash
python3 benchmark/build/phase_a_verify.py
```

## Run evaluators on built splits

```bash
python3 evaluators/rubric_baseline.py --split dev --limit 5
python3 evaluators/all_at_once.py --split dev --limit 5
python3 evaluators/constraint_grounded.py --split dev --limit 3
python3 evaluators/scorecard.py
```

Use `--data-dir "$BENCHMARK_DATA_DIR"` if your data lives outside the default path.

## Scripts

| Script | Output |
|--------|--------|
| `build/consolidate.py` | `consolidated/gaia_consolidated.jsonl` |
| `build/finalize.py` | Patches consolidated JSONL from review CSV |
| `build/phase_a_clean.py` | `*_clean.jsonl`, `*_with_gt.jsonl` |
| `build/phase_a_split.py` | `splits/{dev,calibration,eval}*.jsonl`, updates `refs/split_manifest.json` |
| `build/phase_a_build_evalset.py` | `evalsets/*.evalset.json` |
| `build/phase_a_verify.py` | Validates full Phase A pipeline |
