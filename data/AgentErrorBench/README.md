# AgentErrorBench (local, not redistributed)

This directory is a **local cache** for the GAIA slice of [AgentErrorBench](https://github.com/ulab-uiuc/AgentDebug). Trajectory data is **not** included in this GitHub repo; download it from the upstream project.

## Upstream

| | |
|---|---|
| **Repository** | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) |
| **Paper** | Zhu et al. (2025), *Where LLM Agents Fail and How They Can Learn From Failures*, [arXiv:2509.25370](https://arxiv.org/abs/2509.25370) |

Follow the AgentDebug README to obtain **AgentErrorBench** (Google Drive link in that repo). For this project you need the GAIA subset only.

## Expected layout after download

```
data/AgentErrorBench/
├── gaia_labels.json          # 50 GAIA failure labels
└── GAIA/
    └── {trajectory_id}.json  # full message logs (one file per label)
```

`scripts/consolidate.py` reads these paths and joins labels with trajectories.

## Citation

```bibtex
@article{zhu2025agentdebug,
  title={Where LLM Agents Fail and How They Can Learn From Failures},
  author={Zhu, Kunlun and Liu, Zijia and Li, Bingxuan and others},
  journal={arXiv preprint arXiv:2509.25370},
  year={2025}
}
```
