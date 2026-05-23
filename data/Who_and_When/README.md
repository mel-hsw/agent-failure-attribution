# Who&When (local, not redistributed)

This directory is a **local cache** for the [Who&When](https://github.com/ag2ai/Agents_Failure_Attribution) dataset. Trajectory data is **not** included in this GitHub repo; download it from Hugging Face.

## Upstream

| | |
|---|---|
| **Repository** | [ag2ai/Agents_Failure_Attribution](https://github.com/ag2ai/Agents_Failure_Attribution) |
| **Dataset (HF)** | [Kevin355/Who_and_When](https://huggingface.co/datasets/Kevin355/Who_and_When) (linked from the upstream repo) |
| **Paper** | Zhang et al. (2025), *Which Agent Causes Task Failures and When?*, ICML 2025 · [arXiv:2505.00212](https://arxiv.org/abs/2505.00212) |

## Download into this repo

```python
from datasets import load_dataset

hc = load_dataset("Kevin355/Who_and_When", "Hand-Crafted")
ag = load_dataset("Kevin355/Who_and_When", "Algorithm-Generated")

hc.save_to_disk("data/Who_and_When/Hand-Crafted")
ag.save_to_disk("data/Who_and_When/Algorithm-Generated")
```

Run from the repo root after `pip install datasets`.

## Expected layout

```
data/Who_and_When/
├── Hand-Crafted/
└── Algorithm-Generated/
```

Consolidation keeps GAIA UUID rows only and drops AssistantBench (see `docs/reports/step2_consolidation.md`).

## Citation

```bibtex
@inproceedings{zhang2025which,
  title={Which Agent Causes Task Failures and When? On Automated Failure Attribution of {LLM} Multi-Agent Systems},
  author={Zhang, Shaokun and Yin, Ming and Zhang, Jieyu and others},
  booktitle={Forty-second International Conference on Machine Learning},
  year={2025},
  url={https://openreview.net/forum?id=GazlTYxZss}
}
```

Task substrate: [GAIA benchmark](https://huggingface.co/datasets/gaia-benchmark/GAIA) (Mialon et al., [arXiv:2311.12983](https://arxiv.org/abs/2311.12983)).
