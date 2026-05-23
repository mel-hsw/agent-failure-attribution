#!/usr/bin/env bash
# Smoke-test evaluators on the synthetic minimal example (requires Vertex creds).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EVALSET="${ROOT}/examples/minimal.with_gt.evalset.json"

echo "=== Rubric baseline (limit 1) ==="
python3 evaluators/rubric_baseline.py --evalset "$EVALSET" --limit 1

echo "=== All-at-once (limit 1) ==="
python3 evaluators/all_at_once.py --evalset "$EVALSET" --limit 1

echo "=== Constraint-grounded (limit 1) ==="
python3 evaluators/constraint_grounded.py --evalset "$EVALSET" --limit 1

echo "Done. Outputs under outputs/"
