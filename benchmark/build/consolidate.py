"""Consolidate AgentErrorBench + Who&When into a single GAIA-only JSONL."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from datasets import load_from_disk

BUILD_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BUILD_DIR))
from _paths import (  # noqa: E402
    consolidated_dir,
    raw_agenterrorbench_dir,
    raw_who_and_when_dir,
)

OUT_JSONL = consolidated_dir() / "gaia_consolidated.jsonl"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def normalize_ft(s):
    if s is None:
        return None
    return s.strip().lower()


def normalize_agent(name):
    if name is None:
        return None
    lower = name.lower()
    canonical = {
        "websurfer": "WebSurfer",
        "filesurfer": "FileSurfer",
        "orchestrator": "Orchestrator",
        "assistant": "Assistant",
    }
    return canonical.get(lower, name)


def cast_step(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main() -> int:
    aeb_dir = raw_agenterrorbench_dir()
    ww_dir = raw_who_and_when_dir()
    labels_path = aeb_dir / "gaia_labels.json"
    if not labels_path.exists():
        print(f"ERROR: missing {labels_path}", file=sys.stderr)
        print("Download AgentErrorBench GAIA slice; see docs/data_attribution.md", file=sys.stderr)
        return 1
    if not (ww_dir / "Hand-Crafted").exists():
        print(f"ERROR: missing {ww_dir / 'Hand-Crafted'}", file=sys.stderr)
        print("Download Who&When; see docs/data_attribution.md", file=sys.stderr)
        return 1

    consolidated_dir().mkdir(parents=True, exist_ok=True)

    with open(labels_path) as f:
        aeb_labels = json.load(f)

    aeb_records = []
    for r in aeb_labels:
        ann = (r.get("step_annotations") or [{}])[0]
        crit_mod = r.get("critical_failure_module")
        block = ann.get(crit_mod) if crit_mod else None
        raw_ft = normalize_ft(block.get("failure_type")) if isinstance(block, dict) else None
        reasoning = block.get("reasoning") if isinstance(block, dict) else None
        tid = r["trajectory_id"]
        traj_path = aeb_dir / "GAIA" / f"{tid}.json"
        history = []
        metadata = {}
        if traj_path.exists():
            with open(traj_path) as tf:
                traj = json.load(tf)
            for m in traj.get("messages", []) or []:
                history.append({"role": m.get("role"), "name": m.get("name"), "content": m.get("content")})
            metadata = traj.get("metadata", {}) or {}
        suffix = tid.split("-")[-1] if "-" in tid else None
        aeb_records.append({
            "source": "AgentErrorBench",
            "trajectory_id": tid,
            "gaia_question_id_prefix": suffix,
            "llm": r.get("LLM"),
            "agent_role": crit_mod,
            "history": history,
            "ground_truth": None,
            "critical_failure_step": r.get("critical_failure_step"),
            "critical_failure_module": crit_mod,
            "raw_failure_type": raw_ft,
            "failure_reasoning_text": reasoning,
            "metadata": metadata,
        })

    hc = load_from_disk(str(ww_dir / "Hand-Crafted"))["train"]
    ag = load_from_disk(str(ww_dir / "Algorithm-Generated"))["train"]

    hc_records = []
    hc_gaia_ids = set()
    for row in hc:
        qid = row["question_ID"]
        if not UUID_RE.match(qid):
            continue
        hc_gaia_ids.add(qid)
        history = [{"role": m.get("role"), "name": None, "content": m.get("content")} for m in (row.get("history") or [])]
        hc_records.append({
            "source": "WhoAndWhen-HandCrafted",
            "trajectory_id": "WW-HC-" + qid,
            "gaia_question_id": qid,
            "llm": None,
            "agent_role": normalize_agent(row.get("mistake_agent")),
            "history": history,
            "ground_truth": row.get("groundtruth"),
            "critical_failure_step": cast_step(row.get("mistake_step")),
            "critical_failure_module": None,
            "raw_failure_type": row.get("mistake_type") if row.get("mistake_type") not in (None, "None", "") else None,
            "failure_reasoning_text": row.get("mistake_reason"),
            "metadata": {"question": row.get("question"), "is_correct": row.get("is_corrected")},
        })

    ag_records = []
    ag_skipped = 0
    for row in ag:
        qid = row["question_ID"]
        if not UUID_RE.match(qid):
            continue
        if qid in hc_gaia_ids:
            ag_skipped += 1
            continue
        history = [{"role": m.get("role"), "name": m.get("name"), "content": m.get("content")} for m in (row.get("history") or [])]
        ag_records.append({
            "source": "WhoAndWhen-AlgorithmGenerated",
            "trajectory_id": "WW-AG-" + qid,
            "gaia_question_id": qid,
            "llm": None,
            "agent_role": normalize_agent(row.get("mistake_agent")),
            "history": history,
            "ground_truth": row.get("ground_truth"),
            "critical_failure_step": cast_step(row.get("mistake_step")),
            "critical_failure_module": None,
            "raw_failure_type": None,
            "failure_reasoning_text": row.get("mistake_reason"),
            "metadata": {"question": row.get("question"), "is_correct": row.get("is_correct")},
        })

    all_records = aeb_records + hc_records + ag_records
    with open(OUT_JSONL, "w") as f:
        for rec in all_records:
            f.write(json.dumps(rec) + "\n")

    print("Wrote", len(all_records), "records to", OUT_JSONL)
    for k, v in Counter(r["source"] for r in all_records).items():
        print(" ", k + ":", v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
