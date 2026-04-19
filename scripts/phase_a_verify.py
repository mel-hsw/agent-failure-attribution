"""Phase A — End-to-end verification.

Re-runs every Phase A script from scratch, then validates the outputs:

  1. Clean/with_gt JSONL: counts match, annotation keys stripped, leakage
     scan clean, cluster distribution sums to post-patch total.
  2. Splits: dev/calibration/eval are disjoint; trajectory_ids from
     clean/with_gt line up; stratification preserved vs source & cluster.
  3. EvalSets: parse as JSON, case count matches splits, judge-visible has
     no `gt` key anywhere, with_gt has `gt` on every case, trajectory
     length inside metadata matches the source record.

Exits non-zero if any check fails.

Usage:
    python3 scripts/phase_a_verify.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
DATA_DIR = REPO_ROOT / "data" / "consolidated"
SPLIT_DIR = REPO_ROOT / "data" / "splits"
EVALSET_DIR = REPO_ROOT / "data" / "evalsets"

EXPECTED_POST_PATCH_TOTAL = 133  # 154 - 14 DROP - 7 FLAG

# Top-level annotation keys that must not appear in judge-visible records.
ANNOTATION_KEYS = {
    "ground_truth",
    "critical_failure_step",
    "critical_failure_module",
    "raw_failure_type",
    "failure_reasoning_text",
    "proposed_cluster",
    "proposed_cluster_label",
    "proposed_level",
}

# Regex patterns that would indicate annotation-shaped text leaking into
# judge-visible content (mirrors phase_a_clean.py).
LEAKAGE_PATTERNS = [
    re.compile(r"critical[_ ]failure", re.IGNORECASE),
    re.compile(r"failure[_ ]type", re.IGNORECASE),
    re.compile(r"proposed[_ ]cluster", re.IGNORECASE),
    re.compile(r"proposed[_ ]level", re.IGNORECASE),
    re.compile(r"\bmistake[_ ]reason\b", re.IGNORECASE),
    re.compile(r"\bmistake[_ ]step\b", re.IGNORECASE),
    re.compile(r"\bfailure[_ ]reasoning\b", re.IGNORECASE),
]


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"  OK: {msg}")


def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def run(script: str) -> None:
    print(f"\n>>> {script}")
    r = subprocess.run([sys.executable, str(SCRIPTS / script)], cwd=REPO_ROOT)
    if r.returncode != 0:
        fail(f"{script} exited with code {r.returncode}")


def check_clean_and_with_gt() -> None:
    print("\n[1] Clean / with_gt JSONL")
    clean = load_jsonl(DATA_DIR / "gaia_consolidated_clean.jsonl")
    gt = load_jsonl(DATA_DIR / "gaia_consolidated_with_gt.jsonl")
    if len(clean) != EXPECTED_POST_PATCH_TOTAL:
        fail(f"clean count {len(clean)} != expected {EXPECTED_POST_PATCH_TOTAL}")
    ok(f"clean.jsonl has {len(clean)} records")
    if len(gt) != len(clean):
        fail(f"gt count {len(gt)} != clean count {len(clean)}")
    ok(f"with_gt.jsonl has {len(gt)} records")

    # No annotation keys in clean.
    for rec in clean:
        for k in ANNOTATION_KEYS:
            if k in rec:
                fail(f"annotation key {k!r} leaked into clean record {rec['trajectory_id']}")
    ok("no annotation keys at top level of clean records")

    # All clean records must have expected structure.
    for rec in clean:
        for k in ("trajectory_id", "source", "history", "metadata"):
            if k not in rec:
                fail(f"clean record {rec.get('trajectory_id')} missing key {k!r}")
    ok("all clean records have required keys")

    # gt records all have a gt block with the canonical fields.
    for rec in gt:
        g = rec.get("gt")
        if not isinstance(g, dict):
            fail(f"gt record {rec['trajectory_id']} missing gt block")
        for k in ("proposed_cluster", "proposed_level", "critical_failure_step"):
            if k not in g:
                fail(f"gt record {rec['trajectory_id']} missing gt.{k}")
    ok("all with_gt records carry a complete gt block")

    # Leakage scan on serialized clean records.
    blob = json.dumps(clean, ensure_ascii=False)
    hits = [p.pattern for p in LEAKAGE_PATTERNS if p.search(blob)]
    if hits:
        fail(f"leakage patterns matched in clean blob: {hits}")
    ok("leakage scan on clean blob: no matches")

    # DROP / FLAG must not appear as clusters.
    clusters = Counter(r["gt"]["proposed_cluster"] for r in gt)
    for bad in ("DROP", "FLAG"):
        if bad in clusters:
            fail(f"sentinel cluster {bad!r} still present in with_gt (n={clusters[bad]})")
    ok(f"no DROP/FLAG clusters; distribution: {dict(sorted(clusters.items()))}")


def check_splits() -> None:
    print("\n[2] Splits")
    splits: dict[str, list[dict]] = {}
    for name in ("dev", "calibration", "eval"):
        gt = load_jsonl(SPLIT_DIR / f"{name}.jsonl")
        clean = load_jsonl(SPLIT_DIR / f"{name}_clean.jsonl")
        if len(gt) != len(clean):
            fail(f"{name}: gt={len(gt)} vs clean={len(clean)}")
        if {r["trajectory_id"] for r in gt} != {r["trajectory_id"] for r in clean}:
            fail(f"{name}: gt/clean trajectory_id sets differ")
        splits[name] = gt
        ok(f"{name}: n={len(gt)}; clean and gt aligned")

    total = sum(len(v) for v in splits.values())
    if total != EXPECTED_POST_PATCH_TOTAL:
        fail(f"split total {total} != {EXPECTED_POST_PATCH_TOTAL}")
    ok(f"splits sum to {total}")

    dev_ids = {r["trajectory_id"] for r in splits["dev"]}
    cal_ids = {r["trajectory_id"] for r in splits["calibration"]}
    eval_ids = {r["trajectory_id"] for r in splits["eval"]}
    if dev_ids & cal_ids or dev_ids & eval_ids or cal_ids & eval_ids:
        fail("splits overlap")
    ok("splits are disjoint")

    # Stratification sanity check — every cluster present in eval.
    eval_clusters = {r["gt"]["proposed_cluster"] for r in splits["eval"]}
    expected_clusters = {"N1", "N2", "N3", "N4", "N5", "P1", "P2", "P3", "P4"}
    missing = expected_clusters - eval_clusters
    if missing:
        fail(f"eval split missing clusters: {missing}")
    ok(f"eval split covers all 9 clusters: {sorted(eval_clusters)}")


def check_evalsets() -> None:
    print("\n[3] EvalSets")
    for name in ("dev", "calibration", "eval"):
        split_clean = load_jsonl(SPLIT_DIR / f"{name}_clean.jsonl")
        split_ids = {r["trajectory_id"] for r in split_clean}
        traj_len_by_id = {r["trajectory_id"]: len(r["history"]) for r in split_clean}

        # Judge-visible EvalSet: must NOT contain gt anywhere.
        judge = json.loads((EVALSET_DIR / f"{name}.evalset.json").read_text())
        if len(judge["eval_cases"]) != len(split_ids):
            fail(f"{name}.evalset.json case count mismatch")
        if {c["eval_id"] for c in judge["eval_cases"]} != split_ids:
            fail(f"{name}.evalset.json eval_ids do not match split")
        blob = json.dumps(judge, ensure_ascii=False)
        if '"gt"' in blob:
            fail(f"{name}.evalset.json contains a 'gt' key (should be judge-visible only)")
        # Same regex leakage scan.
        hits = [p.pattern for p in LEAKAGE_PATTERNS if p.search(blob)]
        if hits:
            fail(f"{name}.evalset.json leakage patterns matched: {hits}")
        ok(f"{name}.evalset.json clean ({len(judge['eval_cases'])} cases, no gt, no leakage)")

        # Scoring EvalSet: every case carries a gt block; trajectory lengths preserved.
        scored = json.loads((EVALSET_DIR / f"{name}.with_gt.evalset.json").read_text())
        if len(scored["eval_cases"]) != len(split_ids):
            fail(f"{name}.with_gt.evalset.json case count mismatch")
        for case in scored["eval_cases"]:
            tid = case["eval_id"]
            if "gt" not in case["metadata"]:
                fail(f"{name}.with_gt: case {tid} missing metadata.gt")
            n_msgs = len(case["metadata"]["trajectory"])
            if n_msgs != traj_len_by_id[tid]:
                fail(f"{name}.with_gt: case {tid} trajectory length {n_msgs} != source {traj_len_by_id[tid]}")
        ok(f"{name}.with_gt.evalset.json: gt present on all cases, trajectories preserved")


def main() -> int:
    # Re-run the pipeline from scratch for a true end-to-end check.
    run("phase_a_clean.py")
    run("phase_a_split.py")
    run("phase_a_build_evalset.py")

    check_clean_and_with_gt()
    check_splits()
    check_evalsets()

    print("\n=== Phase A verification PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
