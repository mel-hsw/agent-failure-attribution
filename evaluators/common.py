"""Shared paths and CLI helpers for failure-attribution evaluators."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return repo_root() / "config"


def rubric_file() -> Path:
    return config_dir() / "rubrics" / "nine_cluster_rubric.json"


def default_benchmark_data_dir() -> Path:
    raw = os.environ.get("BENCHMARK_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root() / "local" / "benchmark"


def resolve_evalset_path(
    *,
    evalset: str | None,
    split: str | None,
    with_gt: bool = True,
    data_dir: Path | None = None,
) -> Path:
    if evalset:
        path = Path(evalset).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"EvalSet not found: {path}")
        return path
    if not split:
        raise ValueError("Provide --evalset or --split")
    base = data_dir or default_benchmark_data_dir()
    suffix = ".with_gt.evalset.json" if with_gt else ".evalset.json"
    path = base / "evalsets" / f"{split}{suffix}"
    if not path.exists():
        raise FileNotFoundError(
            f"EvalSet not found: {path}\n"
            "Build the benchmark (see benchmark/README.md) or pass --evalset."
        )
    return path


def resolve_output_dir(
    *,
    output: str | None,
    default_parent: Path,
    run_id: str,
) -> Path:
    if output:
        out = Path(output).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        return out
    out = default_parent / run_id
    out.mkdir(parents=True, exist_ok=True)
    return out
