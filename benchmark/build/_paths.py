"""Paths for the optional GAIA benchmark build pipeline."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def refs_dir() -> Path:
    return repo_root() / "benchmark" / "refs"


def benchmark_data_dir() -> Path:
    raw = os.environ.get("BENCHMARK_DATA_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root() / "local" / "benchmark"


def raw_agenterrorbench_dir() -> Path:
    return benchmark_data_dir() / "raw" / "agenterrorbench"


def raw_who_and_when_dir() -> Path:
    return benchmark_data_dir() / "raw" / "who_and_when"


def consolidated_dir() -> Path:
    return benchmark_data_dir() / "consolidated"


def splits_dir() -> Path:
    return benchmark_data_dir() / "splits"


def evalsets_dir() -> Path:
    return benchmark_data_dir() / "evalsets"


def cluster_review_patch_file() -> Path:
    return refs_dir() / "cluster_review_patch.jsonl"


def split_manifest_file() -> Path:
    return refs_dir() / "split_manifest.json"
