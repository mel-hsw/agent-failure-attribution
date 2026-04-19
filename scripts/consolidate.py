"""Step 2 — Consolidate AgentErrorBench + Who_and_When into a single GAIA-only JSONL.

Rules:
- Keep only GAIA trajectories (AEB task_type=='gaia'; W&W question_ID in UUID format).
- Drop AssistantBench (hex64 question_IDs).
- W&W dedup: when a GAIA UUID appears in both Hand-Crafted and Algorithm-Generated,
  keep only the Hand-Crafted row.
- Normalize:
    * AEB failure_type: lowercase + strip whitespace
    * W&W mistake_agent: Title-case normalize (e.g. 'Websurfer' -> 'WebSurfer')
    * W&W mistake_step: cast string to int
    * Unify field names: is_correct/is_corrected -> is_correct,
                        ground_truth/groundtruth -> ground_truth
    * Hand-Crafted history rows: add name=None
"""

import json
import os
import re
from datasets import load_from_disk

BASE = "/sessions/festive-sweet-mendel/mnt/failure_experiment"
OUT_DIR = BASE + "/data/consolidated"
os.makedirs(OUT_DIR, exist_ok=True)
OUT_JSONL = OUT_DIR + "/gaia_consolidated.jsonl"

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def normalize_ft(s):
    """Normalize AEB failure_type strings (strip + lowercase)."""
    if s is None:
        return None
    return s.strip().lower()


def normalize_agent(name):
    """Normalize W&W mistake_agent capitalization: keep canonical forms."""
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


# --- AgentErrorBench ---
with open(BASE + "/data/AgentErrorBench/gaia_labels.json") as f:
    aeb_labels = json.load(f)

aeb_records = []
for r in aeb_labels:
    # Extract the single step_annotation
    ann = (r.get("step_annotations") or [{}])[0]
    crit_mod = r.get("critical_failure_module")
    block = ann.get(crit_mod) if crit_mod else None
    raw_ft = normalize_ft(block.get("failure_type")) if isinstance(block, dict) else None
    reasoning = block.get("reasoning") if isinstance(block, dict) else None

    # Try to load the full trajectory messages
    tid = r["trajectory_id"]
    traj_path = BASE + "/data/AgentErrorBench/GAIA/" + tid + ".json"
    history = []
    metadata = {}
    if os.path.exists(traj_path):
        with open(traj_path) as tf:
            traj = json.load(tf)
        for m in traj.get("messages", []) or []:
            history.append({
                "role": m.get("role"),
                "name": m.get("name"),
                "content": m.get("content"),
            })
        metadata = traj.get("metadata", {}) or {}

    # Extract the GAIA question UUID from the trajectory_id suffix
    suffix = tid.split("-")[-1] if "-" in tid else None

    aeb_records.append({
        "source": "AgentErrorBench",
        "trajectory_id": tid,
        "gaia_question_id_prefix": suffix,
        "llm": r.get("LLM"),
        "agent_role": crit_mod,
        "history": history,
        "ground_truth": None,  # AEB does not carry GT string in labels
        "critical_failure_step": r.get("critical_failure_step"),
        "critical_failure_module": crit_mod,
        "raw_failure_type": raw_ft,
        "failure_reasoning_text": reasoning,
        "metadata": metadata,
    })

print("AEB records built:", len(aeb_records))

# --- Who_and_When ---
hc = load_from_disk(BASE + "/data/Who_and_When/Hand-Crafted")["train"]
ag = load_from_disk(BASE + "/data/Who_and_When/Algorithm-Generated")["train"]

# Build Hand-Crafted GAIA records first (they win on conflicts)
hc_records = []
hc_gaia_ids = set()
for row in hc:
    qid = row["question_ID"]
    if not UUID_RE.match(qid):
        continue  # drop AssistantBench
    hc_gaia_ids.add(qid)
    history = [
        {"role": m.get("role"), "name": None, "content": m.get("content")}
        for m in (row.get("history") or [])
    ]
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

# Build Algorithm-Generated GAIA records, skipping any question_ID already in HC
ag_records = []
ag_skipped = 0
for row in ag:
    qid = row["question_ID"]
    if not UUID_RE.match(qid):
        continue  # drop AssistantBench
    if qid in hc_gaia_ids:
        ag_skipped += 1
        continue  # dedup: HC wins
    history = [
        {"role": m.get("role"), "name": m.get("name"), "content": m.get("content")}
        for m in (row.get("history") or [])
    ]
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
        "raw_failure_type": None,  # AG has no mistake_type field
        "failure_reasoning_text": row.get("mistake_reason"),
        "metadata": {"question": row.get("question"), "is_correct": row.get("is_correct")},
    })

print("W&W HC records built:", len(hc_records))
print("W&W AG records built:", len(ag_records), "(skipped", ag_skipped, "duplicates)")

# --- Write consolidated JSONL ---
all_records = aeb_records + hc_records + ag_records
with open(OUT_JSONL, "w") as f:
    for rec in all_records:
        f.write(json.dumps(rec) + "\n")

print("\nWrote", len(all_records), "records to", OUT_JSONL)

# Per-source summary
from collections import Counter
src = Counter(r["source"] for r in all_records)
for k, v in src.items():
    print("  " + k + ": " + str(v))
