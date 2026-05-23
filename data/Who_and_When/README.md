# Who&When (Hugging Face export)

Local copy of the **Who&When** failure-attribution dataset — Hand-Crafted and Algorithm-Generated splits — saved in Hugging Face `datasets` on-disk format.

## Upstream

| | |
|---|---|
| **Repository** | [ag2ai/Agents_Failure_Attribution](https://github.com/ag2ai/Agents_Failure_Attribution) |
| **Dataset (HF)** | [Kevin355/Who_and_When](https://huggingface.co/datasets/Kevin355/Who_and_When) (linked from the upstream repo) |
| **Paper** | Zhang et al. (2025), *Which Agent Causes Task Failures and When?*, ICML 2025 · [arXiv:2505.00212](https://arxiv.org/abs/2505.00212) |

Who&When covers 184 annotated multi-agent failure tasks on GAIA and AssistantBench queries. **This repo keeps GAIA UUID rows only** (AssistantBench hex IDs are dropped during consolidation; see `docs/reports/step2_consolidation.md`).

## Layout

```
Who_and_When/
├── Hand-Crafted/train/           # Magentic-One traces (58 rows upstream; 30 GAIA)
└── Algorithm-Generated/train/    # CaptainAgent traces (126 rows upstream; 78 GAIA post-dedup)
```

## Key fields

| Field | Description |
|-------|-------------|
| `question_ID` | GAIA task UUID (AssistantBench uses 64-char hex — excluded here) |
| `history` | Multi-agent conversation trace |
| `mistake_agent` | Agent responsible for the failure |
| `mistake_step` | Decisive error step |
| `mistake_reason` | Free-text failure explanation |

## Reload from Hugging Face

```python
from datasets import load_dataset

hc = load_dataset("Kevin355/Who_and_When", "Hand-Crafted")
ag = load_dataset("Kevin355/Who_and_When", "Algorithm-Generated")
```

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
