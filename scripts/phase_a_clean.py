"""Phase A — Data-hygiene pass.

Reads data/consolidated/gaia_consolidated.jsonl (+ cluster_review_patch.jsonl),
applies cluster patches, and emits two files:

  1. data/consolidated/gaia_consolidated_clean.jsonl
     Judge-visible record. Contains only fields safe to expose to an LLM judge:
     trajectory_id, source, llm, agent_role, history, and non-revealing metadata.
     Annotation fields (ground_truth, critical_failure_*, failure_reasoning_text,
     raw_failure_type, proposed_cluster*, proposed_level) are stripped.

  2. data/consolidated/gaia_consolidated_with_gt.jsonl
     Scoring-side record. Keeps everything from the clean record plus ground-truth
     metadata under a `gt` key so the scorer can read annotations without them
     being accidentally exposed to the judge.

Runs a pre-flight leakage scan on clean records: greps clean_trajectory strings
for annotation keywords and flags matches for manual review.

Usage:
    python3 scripts/phase_a_clean.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

# --- Paths ------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "consolidated"
INPUT_FILE = DATA_DIR / "gaia_consolidated.jsonl"
PATCH_FILE = DATA_DIR / "cluster_review_patch.jsonl"
CLEAN_FILE = DATA_DIR / "gaia_consolidated_clean.jsonl"
WITH_GT_FILE = DATA_DIR / "gaia_consolidated_with_gt.jsonl"

# --- Fields ----------------------------------------------------------------

# Top-level keys that encode annotations and must not appear in the clean record.
ANNOTATION_KEYS = {
    "ground_truth",  # reference answer; indirect leakage if judge sees it
    "critical_failure_step",
    "critical_failure_module",
    "raw_failure_type",
    "failure_reasoning_text",
    "proposed_cluster",
    "proposed_cluster_label",
    "proposed_level",
}

# Metadata keys inside the `metadata` dict that reveal the failure. `won` is
# technically just a task-success flag, but keeping it in metadata for the judge
# is unnecessary (we already pre-filter to failures).
ANNOTATION_METADATA_KEYS = {"won"}

# Regex patterns used by the leakage scan. Matches are flagged for review.
LEAKAGE_PATTERNS = [
    re.compile(r"critical[_ ]failure", re.IGNORECASE),
    re.compile(r"failure[_ ]type", re.IGNORECASE),
    re.compile(r"proposed[_ ]cluster", re.IGNORECASE),
    re.compile(r"proposed[_ ]level", re.IGNORECASE),
    re.compile(r"\bmistake[_ ]reason\b", re.IGNORECASE),
    re.compile(r"\bmistake[_ ]step\b", re.IGNORECASE),
    re.compile(r"\bfailure[_ ]reasoning\b", re.IGNORECASE),
]

# --- Helpers ---------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(records: list[dict], path: Path) -> None:
    with path.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def apply_cluster_patches(records: list[dict], patches: list[dict]) -> tuple[list[dict], dict]:
    """Apply cluster_review_patch.jsonl patches to records.

    Each patch re-assigns a trajectory's `proposed_cluster`. The level
    (node/process) is inferred from the new cluster's ID prefix (N = node,
    P = process). Patches with new_cluster == "DROP" remove the record
    entirely; "FLAG" records are also removed from the eval set because
    they indicate unscorable annotations (e.g. step 0 = manager prompt).

    Returns (patched_records, stats).
    """
    patch_by_id = {p["trajectory_id"]: p for p in patches}
    stats = {
        "patches_provided": len(patches),
        "patches_applied": 0,
        "patches_skipped_no_record": 0,
        "patches_skipped_cluster_mismatch": 0,
        "level_flips": 0,
        "dropped": 0,
        "flagged_removed": 0,
    }

    patched: list[dict] = []
    for rec in records:
        tid = rec.get("trajectory_id")
        if tid in patch_by_id:
            p = patch_by_id[tid]
            old = rec.get("proposed_cluster")
            if old != p["old_cluster"]:
                stats["patches_skipped_cluster_mismatch"] += 1
                patched.append(rec)
                continue

            new_cluster = p["new_cluster"]

            # Sentinel clusters remove the record from the eval set.
            if new_cluster == "DROP":
                stats["dropped"] += 1
                stats["patches_applied"] += 1
                continue
            if new_cluster == "FLAG":
                stats["flagged_removed"] += 1
                stats["patches_applied"] += 1
                continue

            new_level = "node" if new_cluster.startswith("N") else "process"
            if rec.get("proposed_level") != new_level:
                stats["level_flips"] += 1

            rec = {**rec, "proposed_cluster": new_cluster, "proposed_level": new_level}
            stats["patches_applied"] += 1
        patched.append(rec)

    # Count patches that referenced non-existent records
    record_ids = {r.get("trajectory_id") for r in records}
    for p in patches:
        if p["trajectory_id"] not in record_ids:
            stats["patches_skipped_no_record"] += 1

    return patched, stats


def build_clean_record(rec: dict) -> dict:
    """Produce the judge-visible record. No annotation fields, no ground truth."""
    clean_metadata = {
        k: v
        for k, v in (rec.get("metadata") or {}).items()
        if k not in ANNOTATION_METADATA_KEYS
    }
    clean = {
        "trajectory_id": rec["trajectory_id"],
        "source": rec["source"],
        "llm": rec.get("llm"),
        "agent_role": rec.get("agent_role"),
        "history": rec["history"],
        "metadata": clean_metadata,
    }
    # Carry the GAIA question id in whatever form it exists (the key differs
    # across sources: gaia_question_id vs gaia_question_id_prefix).
    for key in ("gaia_question_id", "gaia_question_id_prefix"):
        if key in rec:
            clean[key] = rec[key]
    return clean


def build_with_gt_record(rec: dict, clean: dict) -> dict:
    """Scoring-side record: clean record + gt block."""
    gt = {
        "ground_truth_answer": rec.get("ground_truth"),
        "critical_failure_step": rec.get("critical_failure_step"),
        "critical_failure_module": rec.get("critical_failure_module"),
        "raw_failure_type": rec.get("raw_failure_type"),
        "failure_reasoning_text": rec.get("failure_reasoning_text"),
        "proposed_cluster": rec.get("proposed_cluster"),
        "proposed_cluster_label": rec.get("proposed_cluster_label"),
        "proposed_level": rec.get("proposed_level"),
        "won": (rec.get("metadata") or {}).get("won"),
    }
    return {**clean, "gt": gt}


def scan_for_leakage(clean_records: list[dict]) -> list[dict]:
    """Grep every string in every clean record for annotation-shaped patterns.

    Returns a list of flagged (trajectory_id, pattern, matched_snippet) dicts.
    """
    flags = []

    def walk(obj, path: str, trajectory_id: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}", trajectory_id)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]", trajectory_id)
        elif isinstance(obj, str):
            for pat in LEAKAGE_PATTERNS:
                m = pat.search(obj)
                if m:
                    flags.append({
                        "trajectory_id": trajectory_id,
                        "path": path,
                        "pattern": pat.pattern,
                        "snippet": obj[max(0, m.start() - 40): m.end() + 40],
                    })
                    break  # one flag per string is enough

    for rec in clean_records:
        walk(rec, "", rec["trajectory_id"])
    return flags


# --- Main ------------------------------------------------------------------

def main() -> int:
    if not INPUT_FILE.exists():
        print(f"ERROR: input not found: {INPUT_FILE}", file=sys.stderr)
        return 1

    records = load_jsonl(INPUT_FILE)
    patches = load_jsonl(PATCH_FILE) if PATCH_FILE.exists() else []
    print(f"Loaded {len(records)} records, {len(patches)} patches.")

    # 1. Apply cluster patches
    patched_records, patch_stats = apply_cluster_patches(records, patches)
    print(f"Patch stats: {patch_stats}")

    # 2. Build clean and with-gt records
    clean_records = [build_clean_record(r) for r in patched_records]
    with_gt_records = [
        build_with_gt_record(r, clean) for r, clean in zip(patched_records, clean_records)
    ]

    # 3. Verify no annotation keys slipped into clean records
    for rec in clean_records:
        for k in ANNOTATION_KEYS:
            assert k not in rec, f"Leak: annotation key {k} in clean record {rec['trajectory_id']}"
        for k in ANNOTATION_METADATA_KEYS:
            assert k not in (rec.get("metadata") or {}), (
                f"Leak: annotation metadata key {k} in clean record {rec['trajectory_id']}"
            )

    # 4. String-level leakage scan on clean records
    flags = scan_for_leakage(clean_records)
    if flags:
        print(f"\nLEAKAGE SCAN: {len(flags)} potentially suspicious string match(es):")
        for f in flags[:10]:
            print(f"  {f['trajectory_id']} @ {f['path']}: {f['pattern']} -> {f['snippet']!r}")
        if len(flags) > 10:
            print(f"  ... and {len(flags) - 10} more")
    else:
        print("\nLEAKAGE SCAN: clean.")

    # 5. Write outputs
    write_jsonl(clean_records, CLEAN_FILE)
    write_jsonl(with_gt_records, WITH_GT_FILE)
    print(f"\nWrote {len(clean_records)} records to:")
    print(f"  {CLEAN_FILE}")
    print(f"  {WITH_GT_FILE}")

    # 6. Summary stats (post-patch)
    print("\nPost-patch cluster distribution:")
    for cluster, count in sorted(Counter(r["gt"]["proposed_cluster"] for r in with_gt_records).items()):
        print(f"  {cluster}: {count}")
    print("\nPost-patch level distribution:")
    for level, count in sorted(Counter(r["gt"]["proposed_level"] for r in with_gt_records).items()):
        print(f"  {level}: {count}")

    return 0 if not flags else 2  # exit 2 signals manual review needed


if __name__ == "__main__":
    sys.exit(main())
