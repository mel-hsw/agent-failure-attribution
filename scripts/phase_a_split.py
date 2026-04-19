"""Phase A — Dataset split.

Reads data/consolidated/gaia_consolidated_with_gt.jsonl (the scoring-side
file produced by phase_a_clean.py) and emits a 3-way split:

  - data/splits/dev.jsonl          (~5 records; prompt iteration + debugging)
  - data/splits/calibration.jsonl  (~5 records; inter-rater kappa check)
  - data/splits/eval.jsonl         (all remaining records; frozen for scoring)

The split is stratified by (source, proposed_cluster) where possible, then
random-sampled within strata using a fixed seed for reproducibility. Dev and
calibration are drawn first (small sets); everything else falls into eval.

The same trajectory never appears in more than one split. Clean/judge-visible
versions of each split are also written (dev_clean.jsonl, etc.) so downstream
phases can load either flavor without re-stripping annotations.

Usage:
    python3 scripts/phase_a_split.py [--seed 20260418]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "consolidated"
SPLIT_DIR = REPO_ROOT / "data" / "splits"

WITH_GT_FILE = DATA_DIR / "gaia_consolidated_with_gt.jsonl"
CLEAN_FILE = DATA_DIR / "gaia_consolidated_clean.jsonl"

DEFAULT_SEED = 20260418

# Target split sizes. Dev/calibration are pulled first; eval gets the remainder.
DEV_TARGET = 5
CALIBRATION_TARGET = 5


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def stratified_pick(
    pool: list[dict],
    n: int,
    strata_key,
    rng: random.Random,
) -> tuple[list[dict], list[dict]]:
    """Pick n records from pool, stratified by strata_key(rec).

    Strategy: round-robin across strata in descending-size order, shuffling
    within each stratum before picking. Returns (picked, remaining).
    """
    buckets: dict = defaultdict(list)
    for rec in pool:
        buckets[strata_key(rec)].append(rec)

    # Shuffle each bucket for reproducibility.
    for recs in buckets.values():
        rng.shuffle(recs)

    # Sort strata by size desc so we hit the largest clusters first — keeps
    # rare clusters intact in the remaining eval set.
    strata_order = sorted(buckets.keys(), key=lambda s: -len(buckets[s]))

    picked: list[dict] = []
    while len(picked) < n:
        progress = False
        for s in strata_order:
            if not buckets[s]:
                continue
            picked.append(buckets[s].pop())
            progress = True
            if len(picked) >= n:
                break
        if not progress:
            break  # pool exhausted

    remaining = [r for recs in buckets.values() for r in recs]
    return picked, remaining


def summarize(name: str, records: list[dict]) -> None:
    by_source = Counter(r["source"] for r in records)
    by_cluster = Counter(r["gt"]["proposed_cluster"] for r in records)
    by_level = Counter(r["gt"]["proposed_level"] for r in records)
    print(f"\n{name} (n={len(records)}):")
    print(f"  source:  {dict(by_source)}")
    print(f"  level:   {dict(by_level)}")
    print(f"  cluster: {dict(sorted(by_cluster.items()))}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dev", type=int, default=DEV_TARGET)
    parser.add_argument("--calibration", type=int, default=CALIBRATION_TARGET)
    args = parser.parse_args()

    if not WITH_GT_FILE.exists():
        print(f"ERROR: run phase_a_clean.py first; missing {WITH_GT_FILE}", file=sys.stderr)
        return 1

    with_gt = load_jsonl(WITH_GT_FILE)
    clean_by_id = {r["trajectory_id"]: r for r in load_jsonl(CLEAN_FILE)}
    print(f"Loaded {len(with_gt)} scoring records, {len(clean_by_id)} clean records.")
    assert len(with_gt) == len(clean_by_id), "clean/with_gt record counts diverge"

    rng = random.Random(args.seed)

    # Stratify on (source, cluster) — preserves both axes in the small splits.
    strata_key = lambda r: (r["source"], r["gt"]["proposed_cluster"])

    dev, rest = stratified_pick(with_gt, args.dev, strata_key, rng)
    calibration, eval_set = stratified_pick(rest, args.calibration, strata_key, rng)

    # Integrity check — trajectory_ids are disjoint.
    ids = [r["trajectory_id"] for r in dev + calibration + eval_set]
    assert len(ids) == len(set(ids)), "split produced duplicate trajectory_ids"
    assert len(ids) == len(with_gt), "records lost during split"

    # Write with_gt splits.
    write_jsonl(dev, SPLIT_DIR / "dev.jsonl")
    write_jsonl(calibration, SPLIT_DIR / "calibration.jsonl")
    write_jsonl(eval_set, SPLIT_DIR / "eval.jsonl")

    # Write parallel clean (judge-visible) splits.
    for name, recs in (("dev", dev), ("calibration", calibration), ("eval", eval_set)):
        write_jsonl([clean_by_id[r["trajectory_id"]] for r in recs], SPLIT_DIR / f"{name}_clean.jsonl")

    print(f"\nSeed: {args.seed}")
    print(f"Wrote splits to {SPLIT_DIR}/")
    summarize("dev", dev)
    summarize("calibration", calibration)
    summarize("eval", eval_set)

    # Also record the split manifest for reproducibility.
    manifest = {
        "seed": args.seed,
        "sizes": {"dev": len(dev), "calibration": len(calibration), "eval": len(eval_set)},
        "source_input": str(WITH_GT_FILE.relative_to(REPO_ROOT)),
        "trajectory_ids": {
            "dev": [r["trajectory_id"] for r in dev],
            "calibration": [r["trajectory_id"] for r in calibration],
        },
    }
    manifest_path = SPLIT_DIR / "split_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
