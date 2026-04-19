# AgentErrorBench

Created on: 2025-09-30 17:18:23

## Label Format

Each label follows this structure:
```json
{
    "trajectory_id": "Model_Index_OriginalName",
    "LLM": "Model Name",
    "task_type": "Environment",
    "critical_failure_step": step_number,
    "critical_failure_module": "module_name",
    "step_annotations": [...]
}
```

## Statistics

- Total GAIA labels: 50

## Models

- GPT-4o
- Llama3.3-70B-Turbo
- Qwen3-8B
