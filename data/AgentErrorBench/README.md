# AgentErrorBench (GAIA slice)

Local copy of the **AgentErrorBench** GAIA failure annotations from the AgentDebug project.

## Upstream

| | |
|---|---|
| **Repository** | [ulab-uiuc/AgentDebug](https://github.com/ulab-uiuc/AgentDebug) |
| **Paper** | Zhu et al. (2025), *Where LLM Agents Fail and How They Can Learn From Failures*, [arXiv:2509.25370](https://arxiv.org/abs/2509.25370) |

AgentErrorBench annotates failed agent trajectories across ALFWorld, WebShop, and GAIA. **This directory contains only the 50 GAIA records** used in the consolidated benchmark (`data/consolidated/`).

## Files here

| File / dir | Description |
|------------|-------------|
| `gaia_labels.json` | Step-level failure labels (module, type, reasoning) |
| `GAIA/*.json` | Full trajectory message logs joined during consolidation |

## Label format

Each label follows this structure:

```json
{
    "trajectory_id": "Model_Index_OriginalName",
    "LLM": "Model Name",
    "task_type": "Environment",
    "critical_failure_step": 1,
    "critical_failure_module": "planning",
    "step_annotations": []
}
```

## Statistics (GAIA slice)

- Total GAIA labels: **50**
- Models: GPT-4o, Llama3.3-70B-Turbo, Qwen3-8B

## Citation

```bibtex
@article{zhu2025agentdebug,
  title={Where LLM Agents Fail and How They Can Learn From Failures},
  author={Zhu, Kunlun and Liu, Zijia and Li, Bingxuan and others},
  journal={arXiv preprint arXiv:2509.25370},
  year={2025}
}
```

Obtain the full AgentErrorBench release from the [AgentDebug repository](https://github.com/ulab-uiuc/AgentDebug).
