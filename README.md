# Failure Attribution Experiment — GAIA

Evaluating whether the Google ADK evaluation suite can accurately identify the **failure origin** (earliest step at which the error enters) on pre-recorded multi-agent GAIA trajectories.

## Start here

- **[CLAUDE.md](CLAUDE.md)** — stable project contract (goal, working agreement). Read first.
- **[docs/PROJECT.md](docs/PROJECT.md)** — live project state. Evolving taxonomy, decisions log, current status.
- **[docs/HANDOVER.md](docs/HANDOVER.md)** — how to resume mid-flight work as a fresh agent / collaborator.
- **[docs/reports/step4_plan.md](docs/reports/step4_plan.md)** — experimental design for the Phase A–D pipeline.
- **[docs/reports/step4_results.md](docs/reports/step4_results.md)** — current results (tables fill in as batches complete).

## Repo layout

```
.
├── CLAUDE.md                    # Stable contract
├── README.md                    # This file
├── docs/
│   ├── PROJECT.md               # Live state
│   ├── HANDOVER.md              # Resume guide
│   └── reports/                 # Stepwise reports
│       └── archive/             # Superseded review artifacts
├── data/
│   ├── AgentErrorBench/         # Source dataset 1
│   ├── Who_and_When/            # Source dataset 2
│   ├── consolidated/            # Reviewed + patched unified JSONL
│   ├── splits/                  # dev / calibration / eval (seed 20260418)
│   ├── evalsets/                # ADK EvalSet JSON (judge-visible + with_gt)
│   └── rubrics/                 # Phase B rubric set (positive-correctness polarity)
├── scripts/
│   ├── batch_utils.py           # Shared Vertex batch-prediction helpers
│   ├── phase_a_*.py             # Clean / split / build evalsets / verify
│   ├── phase_b_batch.py         # Phase B (off-the-shelf rubric baseline)
│   ├── phase_c_all_at_once.py   # Phase C.1
│   ├── phase_c_binary_search.py # Phase C.2
│   ├── phase_c_constraint_grounded.py  # Phase C.3
│   ├── trajectory_replayer.py   # Constraint checker used by C.3
│   ├── reparse_batch.py         # Re-align predictions.jsonl by trajectory_id
│   ├── render_dev_review.py     # Human-readable Phase B+C side-by-side review
│   ├── {consolidate,finalize,inventory_failures,profile_all,verify}.py  # Pre-Phase-A data prep
│   └── archive/                 # Retired helpers
├── outputs/
│   ├── phase_b_batch/           # Phase B batch runs (per-split)
│   ├── phase_c/{all_at_once,binary_search,constraint_grounded}/  # Phase C runs
│   ├── phase_b/debug/           # Polarity-finding raw LLM responses (cited in step4_results.md §7.1)
│   └── archive/                 # Superseded / one-off runs
├── paper/                       # Draft + references
└── archive/                     # Superseded root-level artifacts
```

## Reproducibility

```bash
# Phase A — clean + split + build EvalSets (idempotent; must exit green)
python3 scripts/phase_a_verify.py

# Phase B — off-the-shelf rubric baseline (Vertex batch; gemini-3.1-pro-preview, global)
python3 scripts/phase_b_batch.py --split dev           # 5-case smoke (~6min)
python3 scripts/phase_b_batch.py --split eval          # 123 cases (~15-25min)

# Phase C.1 — AllAtOnceAttribution (structured JSON via prompt discipline)
python3 scripts/phase_c_all_at_once.py --split dev
python3 scripts/phase_c_all_at_once.py --split eval

# Reparse any predictions.jsonl by trajectory_id (Vertex batch does NOT preserve row order)
python3 scripts/reparse_batch.py --phase b --predictions <path-to-predictions.jsonl>

# Side-by-side dev review
python3 scripts/render_dev_review.py
```

## Config

- `.env` (gitignored): sets `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT=agentevaluationtest`, `GOOGLE_CLOUD_LOCATION=us-central1` (overridden to `global` in scripts that need Gemini 3.x preview models).
- GCS bucket: `gs://agenttracebucket/{phase_b,phase_c}/<run_id>/`.
- Judge model default: `gemini-3.1-pro-preview` via Vertex `global` endpoint.

## Active workstream

See [docs/PROJECT.md §Current status](docs/PROJECT.md) for what's in flight.
