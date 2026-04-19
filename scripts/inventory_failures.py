"""Enumerate every distinct failure label in the consolidated dataset,
with representative reasoning excerpts and counts, separated by source."""
import json
from collections import defaultdict, Counter

JSONL = "/sessions/festive-sweet-mendel/mnt/failure_experiment/data/consolidated/gaia_consolidated.jsonl"

records = []
with open(JSONL) as f:
    for line in f:
        if line.strip():
            records.append(json.loads(line))

print("=" * 70)
print("AgentErrorBench — grouped by (module, failure_type)")
print("=" * 70)

aeb_by_key = defaultdict(list)
for r in records:
    if r["source"] != "AgentErrorBench":
        continue
    key = (r["critical_failure_module"], r["raw_failure_type"])
    aeb_by_key[key].append(r)

for key, recs in sorted(aeb_by_key.items(), key=lambda x: (-len(x[1]), x[0])):
    mod, ft = key
    print("\n[" + str(mod) + " :: " + str(ft) + "]  count=" + str(len(recs)))
    # Up to 2 representative reasoning excerpts, preferring longer ones
    sorted_recs = sorted(recs, key=lambda r: -(len(r.get("failure_reasoning_text") or "")))
    for r in sorted_recs[:2]:
        reasoning = (r.get("failure_reasoning_text") or "").strip()
        if len(reasoning) > 220:
            reasoning = reasoning[:220] + "..."
        print("  - step=" + str(r["critical_failure_step"]) + " | " + reasoning)

print("\n")
print("=" * 70)
print("Who_and_When — full dump of failure_reasoning_text (for clustering)")
print("=" * 70)

for src in ("WhoAndWhen-HandCrafted", "WhoAndWhen-AlgorithmGenerated"):
    print("\n--- " + src + " ---")
    ww = [r for r in records if r["source"] == src]
    print("count=" + str(len(ww)))
    for i, r in enumerate(ww):
        reasoning = (r.get("failure_reasoning_text") or "").strip()
        agent = r.get("agent_role")
        step = r.get("critical_failure_step")
        print("  [" + str(i) + "] agent=" + str(agent) + " step=" + str(step))
        print("    " + reasoning)
