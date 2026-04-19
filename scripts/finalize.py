"""Finalize the consolidated dataset:
- Drop the 4 ambiguous records.
- Embed proposed_cluster and proposed_level into gaia_consolidated.jsonl.
- Rewrite failure_classifications.csv to match.
"""
import json
import csv

BASE = "/sessions/festive-sweet-mendel/mnt/failure_experiment"
IN_JSONL = BASE + "/data/consolidated/gaia_consolidated.jsonl"
OUT_JSONL = BASE + "/data/consolidated/gaia_consolidated.jsonl"
OUT_CSV = BASE + "/data/consolidated/failure_classifications.csv"
OLD_REVIEW_CSV = BASE + "/data/consolidated/failure_classifications_for_review.csv"

# --- Cluster definitions ---
CLUSTER_LABELS = {
    "N1": "Hallucination / factual fabrication",
    "N2": "Code implementation bug",
    "N3": "Tool execution or retrieval failure",
    "N4": "Wrong tool selection",
    "N5": "Invalid tool parameters / input",
    "P1": "Improper task decomposition / bad plan",
    "P2": "Progress misassessment",
    "P3": "Cascading error (explicit propagation)",
    "P4": "Constraint ignorance / unchecked assumption",
}

# AEB mapping (module, failure_type) -> (cluster, level)
aeb_map = {
    ("action", "parameter_error"): ("N5", "node"),
    ("action", "misalignment"): ("N4", "node"),
    ("memory", "hallucination"): ("N1", "node"),
    ("system", "tool_execution_error"): ("N3", "node"),
    ("system", "llm_limit"): ("N3", "node"),
    ("planning", "inefficient_plan"): ("P1", "process"),
    ("planning", "constraint_ignorance"): ("P4", "process"),
    ("planning", "impossible_action"): ("P1", "process"),
    ("memory", "over_simplification"): ("P3", "process"),
    ("reflection", "outcome_misinterpretation"): ("P2", "process"),
    ("reflection", "progress_misjudge"): ("P2", "process"),
}

# W&W Hand-Crafted classifications (by row index within the filtered HC-GAIA set)
ww_hc = {
    0: ("N3", "node"), 1: ("N1", "node"), 2: ("P2", "process"),
    3: ("P3", "process"), 4: ("N5", "node"), 5: ("N3", "node"),
    6: ("N2", "node"), 7: ("N4", "node"), 8: ("N1", "node"),
    9: ("N3", "node"), 10: ("P1", "process"), 11: ("N3", "node"),
    12: ("N1", "node"), 13: ("N1", "node"), 14: ("N3", "node"),
    15: ("N1", "node"), 16: ("DROP", "drop"),  # ambiguous → drop
    17: ("P2", "process"), 18: ("N3", "node"), 19: ("N3", "node"),
    20: ("P1", "process"), 21: ("P3", "process"), 22: ("P3", "process"),
    23: ("N2", "node"), 24: ("N2", "node"), 25: ("P2", "process"),
    26: ("P4", "process"), 27: ("N3", "node"), 28: ("N3", "node"),
    29: ("P2", "process"),
}

ww_ag = {
    0: ("P1", "process"), 1: ("N2", "node"), 2: ("N2", "node"),
    3: ("N1", "node"), 4: ("N1", "node"), 5: ("N2", "node"),
    6: ("N3", "node"), 7: ("N2", "node"), 8: ("N3", "node"),
    9: ("N1", "node"), 10: ("P4", "process"), 11: ("P4", "process"),
    12: ("N2", "node"), 13: ("N1", "node"), 14: ("P3", "process"),
    15: ("N1", "node"), 16: ("N1", "node"), 17: ("P1", "process"),
    18: ("P1", "process"), 19: ("P2", "process"), 20: ("N1", "node"),
    21: ("N2", "node"), 22: ("N1", "node"), 23: ("DROP", "drop"),  # ambiguous → drop
    24: ("N1", "node"), 25: ("N4", "node"), 26: ("N2", "node"),
    27: ("N1", "node"), 28: ("N2", "node"), 29: ("P3", "process"),
    30: ("N1", "node"), 31: ("N2", "node"), 32: ("N4", "node"),
    33: ("P1", "process"), 34: ("N2", "node"), 35: ("N2", "node"),
    36: ("N1", "node"), 37: ("N2", "node"), 38: ("N1", "node"),
    39: ("P1", "process"), 40: ("N4", "node"), 41: ("N1", "node"),
    42: ("N1", "node"), 43: ("P1", "process"), 44: ("N2", "node"),
    45: ("N1", "node"), 46: ("N2", "node"), 47: ("N1", "node"),
    48: ("N2", "node"), 49: ("N1", "node"), 50: ("N1", "node"),
    51: ("P2", "process"), 52: ("N1", "node"), 53: ("N1", "node"),
    54: ("N4", "node"), 55: ("N1", "node"), 56: ("P3", "process"),
    57: ("N1", "node"), 58: ("N1", "node"), 59: ("P3", "process"),
    60: ("P1", "process"), 61: ("N2", "node"), 62: ("N2", "node"),
    63: ("P1", "process"), 64: ("DROP", "drop"),  # ambiguous → drop
    65: ("N2", "node"), 66: ("DROP", "drop"),  # ambiguous → drop
    67: ("P3", "process"), 68: ("N2", "node"), 69: ("P2", "process"),
    70: ("P2", "process"), 71: ("P1", "process"), 72: ("N1", "node"),
    73: ("N2", "node"), 74: ("N2", "node"), 75: ("N1", "node"),
    76: ("N1", "node"), 77: ("N4", "node"),
}

# Load input
records = []
with open(IN_JSONL) as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

# Classify + drop
kept = []
dropped = []
hc_idx = 0
ag_idx = 0
for r in records:
    if r["source"] == "AgentErrorBench":
        key = (r["critical_failure_module"], r["raw_failure_type"])
        cluster, level = aeb_map[key]
    elif r["source"] == "WhoAndWhen-HandCrafted":
        cluster, level = ww_hc[hc_idx]
        hc_idx += 1
    elif r["source"] == "WhoAndWhen-AlgorithmGenerated":
        cluster, level = ww_ag[ag_idx]
        ag_idx += 1
    else:
        continue

    if level == "drop":
        dropped.append(r)
        continue
    r["proposed_cluster"] = cluster
    r["proposed_cluster_label"] = CLUSTER_LABELS[cluster]
    r["proposed_level"] = level
    kept.append(r)

print("Kept:", len(kept))
print("Dropped (ambiguous):", len(dropped))
for r in dropped:
    print("  ", r["trajectory_id"])

# Write finalized JSONL
with open(OUT_JSONL, "w") as f:
    for r in kept:
        f.write(json.dumps(r) + "\n")

# Write clean CSV (no review-override columns)
with open(OUT_CSV, "w", newline="") as f:
    fieldnames = [
        "source", "trajectory_id", "llm", "agent_role",
        "critical_failure_step", "critical_failure_module", "raw_failure_type",
        "proposed_cluster", "proposed_cluster_label", "proposed_level",
        "failure_reasoning_text",
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for r in kept:
        w.writerow({
            "source": r["source"],
            "trajectory_id": r["trajectory_id"],
            "llm": r.get("llm"),
            "agent_role": r.get("agent_role"),
            "critical_failure_step": r["critical_failure_step"],
            "critical_failure_module": r.get("critical_failure_module"),
            "raw_failure_type": r.get("raw_failure_type"),
            "proposed_cluster": r["proposed_cluster"],
            "proposed_cluster_label": r["proposed_cluster_label"],
            "proposed_level": r["proposed_level"],
            "failure_reasoning_text": (r.get("failure_reasoning_text") or "").replace("\n", " ").strip()[:500],
        })

# Remove the old review CSV; it's been superseded
import os
if os.path.exists(OLD_REVIEW_CSV):
    os.remove(OLD_REVIEW_CSV)
    print("Removed:", OLD_REVIEW_CSV)

print("\nFinal JSONL:", OUT_JSONL)
print("Final CSV:  ", OUT_CSV)

# Summary
from collections import Counter
by_level = Counter(r["proposed_level"] for r in kept)
by_cluster = Counter(r["proposed_cluster"] for r in kept)
by_source = Counter(r["source"] for r in kept)
print("\nBy source:", dict(by_source))
print("By level:", dict(by_level))
print("By cluster:")
for c, n in by_cluster.most_common():
    print("  " + c + " " + CLUSTER_LABELS[c] + ": " + str(n))
