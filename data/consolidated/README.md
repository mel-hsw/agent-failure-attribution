# GAIA failure-attribution benchmark

133 annotated failed GAIA trajectories bundled as the test harness for the ADK evaluators in this repo.

## Files

| File | Use |
|------|-----|
| `gaia_consolidated_with_gt.jsonl` | Canonical records with ground-truth labels (split input) |
| `gaia_consolidated_clean.jsonl` | Judge-visible records; annotation keys stripped |
| `gaia_consolidated.jsonl` | Pre-review consolidation |
| `gaia_consolidated_reviewed.jsonl` | Post cluster-review pass |
| `cluster_review_patch.jsonl` | Row-level review decisions (DROP / FLAG / relabel) |
| `failure_classifications.csv` | Human-readable classification export |

## Splits

Defined in `data/splits/split_manifest.json` (seed `20260418`):

| Split | n | Purpose |
|-------|---|---------|
| dev | 5 | Prompt iteration |
| calibration | 5 | Human–judge agreement (κ) |
| eval | 123 | Primary reported metrics |

ADK `EvalSet` JSON for each split lives in `data/evalsets/` (`*.evalset.json` = judge-visible, `*.with_gt.evalset.json` = scoring).

## Taxonomy (9 clusters)

**Node-level:** N1 hallucination · N2 code bug · N3 tool failure · N4 wrong tool · N5 bad parameters

**Process-level:** P1 bad plan · P2 progress misassessment · P3 cascading error · P4 constraint ignorance

Full definitions: `docs/reports/step3_taxonomy_review.md`.

## Sources

Consolidated from two upstream failure-annotation libraries (GAIA task substrate only):

| Source | Upstream repo | Records in benchmark | Notes |
|--------|---------------|---------------------|-------|
| [AgentErrorBench](../AgentErrorBench/README.md) | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) | 45 on eval · 50 upstream GAIA | Single-agent; GPT-4o, Llama3.3-70B, Qwen3-8B |
| [Who&When](../Who_and_When/README.md) | [ag2ai/Agents_Failure_Attribution](https://github.com/ag2ai/Agents_Failure_Attribution) · [HF](https://huggingface.co/datasets/Kevin355/Who_and_When) | 78 on eval · 108 upstream GAIA | Multi-agent; Hand-Crafted + Algorithm-Generated |

Task questions come from the [GAIA benchmark](https://huggingface.co/datasets/gaia-benchmark/GAIA) ([arXiv:2311.12983](https://arxiv.org/abs/2311.12983)).

133 active records = 158 consolidated GAIA rows minus 14 DROP and 7 FLAG from cluster review (`cluster_review_patch.jsonl`).

Construction pipeline: [`docs/reports/step1_data_cleaning.md`](../../docs/reports/step1_data_cleaning.md), [`step2_consolidation.md`](../../docs/reports/step2_consolidation.md), [`step3_taxonomy_review.md`](../../docs/reports/step3_taxonomy_review.md).

## Citation

If you use this consolidated benchmark, cite the upstream datasets (see [`README.md`](../../README.md#data-sources--attribution)) and note that labels were re-mapped to this repo's 9-cluster taxonomy.
