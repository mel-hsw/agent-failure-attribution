import json, re
from collections import Counter
from datasets import load_from_disk

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
BASE = "/sessions/festive-sweet-mendel/mnt/failure_experiment/data"

with open(BASE + "/AgentErrorBench/gaia_labels.json") as f:
    aeb = json.load(f)

ft_raw = Counter()
mod_step = Counter()
for r in aeb:
    mod_step[(r.get("critical_failure_module"), r.get("critical_failure_step"))] += 1
    for sa in r.get("step_annotations") or []:
        for mod in ("planning", "action", "memory", "reflection", "system"):
            blk = sa.get(mod)
            if isinstance(blk, dict) and "failure_type" in blk:
                ft_raw[blk["failure_type"]] += 1

seen_norm = {}
for ft in ft_raw:
    norm = ft.strip().lower()
    seen_norm.setdefault(norm, []).append(ft)

issues = []
for norm, variants in seen_norm.items():
    if len(variants) > 1:
        issues.append({
            "kind": "label_normalization",
            "normalized": norm,
            "variants": variants,
            "counts": [ft_raw[v] for v in variants],
        })
    else:
        v0 = variants[0]
        if v0.strip() != v0:
            issues.append({"kind": "trailing_whitespace", "value": v0, "count": ft_raw[v0]})

print("AEB total records:", len(aeb))
print("AEB unique failure_type strings:", len(ft_raw))
print("AEB normalized unique failure_types:", len(seen_norm))
print("AEB data-quality issues:")
for x in issues:
    print(" ", x)

ww_summary = {}
for split in ("Algorithm-Generated", "Hand-Crafted"):
    train = load_from_disk(BASE + "/Who_and_When/" + split)["train"]
    gaia = sum(1 for q in train["question_ID"] if UUID_RE.match(q))
    ab = len(train) - gaia
    agents = Counter(train["mistake_agent"])
    norm_agents = {}
    for a in agents:
        norm_agents.setdefault(a.lower(), []).append(a)
    cap_issues = {k: v for k, v in norm_agents.items() if len(v) > 1}
    steps = train["mistake_step"]
    int_castable = sum(1 for s in steps if s is not None and str(s).lstrip("-").isdigit())
    ww_summary[split] = {
        "rows": len(train),
        "gaia_uuid_rows": gaia,
        "assistantbench_hex_rows": ab,
        "mistake_agent_cap_issues": cap_issues,
        "mistake_step_dtype": str(type(steps[0]).__name__),
        "mistake_step_int_castable": int_castable,
        "fields": list(train.column_names),
    }

print("\nWho_and_When summary:")
print(json.dumps(ww_summary, indent=2))

# Final consolidated GAIA counts
total_gaia = len(aeb) + ww_summary["Algorithm-Generated"]["gaia_uuid_rows"] + ww_summary["Hand-Crafted"]["gaia_uuid_rows"]
print("\n=== Consolidated GAIA-only counts ===")
print("AgentErrorBench:", len(aeb))
print("Who_and_When/Algorithm-Generated GAIA:", ww_summary["Algorithm-Generated"]["gaia_uuid_rows"])
print("Who_and_When/Hand-Crafted GAIA:", ww_summary["Hand-Crafted"]["gaia_uuid_rows"])
print("TOTAL GAIA trajectories after consolidation:", total_gaia)
