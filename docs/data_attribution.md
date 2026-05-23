# Data attribution

This repository publishes **evaluator code, configuration, and examples only**. It does **not** redistribute benchmark trajectories or upstream dataset files.

## Upstream datasets

| Dataset | Source | Used for |
|---------|--------|----------|
| **AgentErrorBench** (GAIA slice) | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) | Multi-agent failure labels and trajectories |
| **Who&When** | [Kevin355/Who_and_When](https://huggingface.co/datasets/Kevin355/Who_and_When) | Hand-crafted and algorithm-generated failure attributions |
| **GAIA** | [gaia-benchmark/GAIA](https://huggingface.co/datasets/gaia-benchmark/GAIA) | Task substrate referenced by both libraries |

Download these datasets directly from the upstream projects. Do not commit them to a public fork of this repo.

## Local layout (outside git)

Set `BENCHMARK_DATA_DIR` to a directory **outside** this repository (default: `local/benchmark/`):

```
$BENCHMARK_DATA_DIR/
├── raw/
│   ├── agenterrorbench/
│   │   ├── gaia_labels.json
│   │   └── GAIA/*.json
│   └── who_and_when/
│       ├── Hand-Crafted/
│       └── Algorithm-Generated/
├── consolidated/          # built by benchmark/build/
├── splits/
└── evalsets/
```

## Who&When download (Hugging Face)

```python
from datasets import load_dataset

root = "local/benchmark/raw/who_and_when"  # or your BENCHMARK_DATA_DIR
load_dataset("Kevin355/Who_and_When", "Hand-Crafted").save_to_disk(f"{root}/Hand-Crafted")
load_dataset("Kevin355/Who_and_When", "Algorithm-Generated").save_to_disk(f"{root}/Algorithm-Generated")
```

## AgentErrorBench download

Follow the [AgentDebug](https://github.com/ulab-uiuc/AgentDebug) instructions for GAIA labels and trajectory JSON files. Place them under `$BENCHMARK_DATA_DIR/raw/agenterrorbench/`.

## What this repo tracks

| Tracked | Purpose |
|---------|---------|
| `benchmark/refs/split_manifest.json` | Split seeds and trajectory IDs (no message text) |
| `benchmark/refs/cluster_review_patch.jsonl` | Taxonomy review decisions for the GAIA consolidation |
| `config/rubrics/`, `config/taxonomy.json` | Rubric and cluster definitions |
| `examples/*.evalset.json` | Synthetic smoke-test cases |

## Citations

If you use the upstream datasets or reproduce published numbers, cite the original works:

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
