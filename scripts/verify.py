"""Step 2 — Verification of consolidated dataset."""
import json
import re
from collections import Counter

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

JSONL = "/sessions/festive-sweet-mendel/mnt/failure_experiment/data/consolidated/gaia_consolidated.jsonl"

records = []
with open(JSONL) as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

print("=" * 60)
print("Total records:", len(records))

# Source distribution
src = Counter(r["source"] for r in records)
print("\nBy source:")
for k, v in src.items():
    print("  " + k + ": " + str(v))

# Uniqueness of trajectory_id
tids = [r["trajectory_id"] for r in records]
dups = [k for k, v in Counter(tids).items() if v > 1]
print("\nDuplicate trajectory_ids:", len(dups))

# No AssistantBench leakage
ab_leak = 0
for r in records:
    qid = r.get("gaia_question_id") or ""
    if HEX64_RE.match(qid):
        ab_leak += 1
print("AssistantBench (hex64) IDs leaked through:", ab_leak)

# No W&W dedup collisions — every GAIA UUID from W&W should appear at most once
ww_qids = [r.get("gaia_question_id") for r in records
           if r["source"].startswith("WhoAndWhen") and r.get("gaia_question_id")]
ww_dupes = [k for k, v in Counter(ww_qids).items() if v > 1]
print("W&W GAIA question_IDs appearing in multiple rows:", len(ww_dupes))

# Every record has critical_failure_step
missing_step = sum(1 for r in records if r.get("critical_failure_step") is None)
print("Records missing critical_failure_step:", missing_step)

# Every record has failure_reasoning_text
missing_reason = sum(1 for r in records if not r.get("failure_reasoning_text"))
print("Records missing failure_reasoning_text:", missing_reason)

# Normalization checks
# 1. AEB failure_type: no trailing whitespace / no mixed case
print("\nNormalization checks:")
ft_issues = [r["raw_failure_type"] for r in records
             if r["source"] == "AgentErrorBench"
             and r["raw_failure_type"] is not None
             and (r["raw_failure_type"] != r["raw_failure_type"].strip().lower())]
print("  AEB failure_type rows still not normalized:", len(ft_issues))

# 2. W&W mistake_agent: 'Websurfer' should be gone
bad_agents = [r["agent_role"] for r in records
              if r["agent_role"] == "Websurfer"]
print("  Rows still carrying 'Websurfer' (pre-normalization):", len(bad_agents))

# 3. mistake_step is int for W&W rows
non_int_steps = [r for r in records
                 if r["source"].startswith("WhoAndWhen")
                 and r["critical_failure_step"] is not None
                 and not isinstance(r["critical_failure_step"], int)]
print("  W&W rows with non-int critical_failure_step:", len(non_int_steps))

# 4. AEB failure_type distribution after normalization
print("\nAEB failure_type values after normalization:")
aeb_ft = Counter(r["raw_failure_type"] for r in records if r["source"] == "AgentErrorBench")
for k, v in aeb_ft.most_common():
    print("  " + repr(k) + ": " + str(v))

# 5. W&W agent_role distribution after normalization
print("\nW&W agent_role distribution (Hand-Crafted only, to check WebSurfer merge):")
hc_agents = Counter(r["agent_role"] for r in records if r["source"] == "WhoAndWhen-HandCrafted")
for k, v in hc_agents.most_common():
    print("  " + repr(k) + ": " + str(v))

# 6. critical_failure_step distribution across the whole consolidated set
print("\nOrigin-step distribution across all 158 records:")
steps = Counter(r["critical_failure_step"] for r in records)
for k, v in sorted(steps.items(), key=lambda x: (x[0] is None, x[0])):
    print("  step " + str(k) + ": " + str(v))

print("\nAll verification checks complete.")
