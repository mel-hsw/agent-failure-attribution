# Failure Attribution on GAIA — Google ADK evaluation code

This repository holds the **benchmark data, ADK EvalSets, and evaluation scripts** for the project described in the paper draft (`paper/draft/draft_fixed.docx`, mirrored as `paper/draft/draft.md`): *Evaluating Failure Attribution on Multi-Agent GAIA Trajectories with the Google ADK Evaluation Suite*.

**Task.** Given a failed GAIA trajectory, predict the **earliest failure step** and a **nine-cluster failure category** (five node-level N1–N5, four process-level P1–P4), using Google’s Agent Development Kit (ADK) evaluators and custom judges on Vertex AI.

## What the paper tests

- **H1 (structural mismatch).** The off-the-shelf ADK rubric evaluator (`rubric_based_final_response_quality_v1`) should recall **node-level** failures much more often than **process-level** failures on GAIA — operationalized as ≥40 percentage points gap on the eval split, with paired McNemar vs the stronger custom configuration.
- **Three reported configurations:** **Baseline** (off-the-shelf rubric batch), **AllAtOnce** (one-pass structured JSON judge), **ConstraintGrounded** (two-step judge with a per-trajectory constraint-violation log). *Binary search localization (`phase_c_binary_search.py`) is implemented but not part of the paper narrative.*

Headline numbers from the draft (eval split, *n* = 123): Baseline recalls ~90% of node-level vs ~18% of process-level failures (paired McNemar *p* = 0.002 vs ConstraintGrounded); custom evaluators raise process recall (AllAtOnce ~36%, ConstraintGrounded ~47%); step match at tolerance ±3 is ~65% for the custom methods and not meaningfully available for the Baseline rubric setup.

## What belongs in this repo (vs local-only)

| Tracked for GitHub | Purpose |
|-------------------|---------|
| `data/consolidated/` | Canonical benchmark: JSONL (clean / with ground truth / review lineage), cluster-review patch, classifications CSV |
| `data/splits/` | dev (5) / calibration (5) / eval (123); seed in `split_manifest.json` |
| `data/evalsets/` | ADK `EvalSet` JSON — judge-visible and `with_gt` for scoring |
| `data/rubrics/` | Phase B rubric definition used by the Baseline |
| `data/AgentErrorBench/` | GAIA slice of AgentErrorBench — **only needed if you re-run consolidation from primary sources** (`scripts/consolidate.py` / `finalize.py`) |
| `data/Who_and_When/` | Hugging Face–layout Who&When train splits — **same** |
| `scripts/` | Phase A–D pipelines, batch helpers, `scripts/archive/` retired tools |
| `docs/` | Step reports and scorecards **cited by the paper** (methods, results, appendices) |
| `paper/draft/` | Draft text and figures |

**You do not need every folder under `data/` to reproduce the paper’s evaluation.** For **rerunning judges and metrics** after clone, the necessary artifacts are `data/consolidated/`, `data/splits/`, `data/evalsets/`, and `data/rubrics/`. The two upstream library trees are for **rebuilding** the consolidated JSONL from the original releases; omit them only if you treat the consolidated JSONL as the source of truth.

**Local / not for publication** (see `.gitignore`): `data/EDA/` (exploratory EDA and nested tooling), `outputs/` (Vertex batch runs and logs), root `archive/`, `.claude/` worktree state, and optional working docs under `docs/` (`PROJECT.md`, `HANDOVER*.md`) if you keep them only on your machine.

## Repository layout

```
.
├── README.md
├── docs/
│   └── reports/                # Stepwise reports (cited from the paper)
├── data/
│   ├── consolidated/           # 133-record benchmark + patches (required)
│   ├── splits/                 # dev / calibration / eval (required)
│   ├── evalsets/               # ADK EvalSet JSON (required)
│   ├── rubrics/                # Phase B rubrics (required)
│   ├── AgentErrorBench/        # Optional: rebuild-from-source
│   └── Who_and_When/           # Optional: rebuild-from-source
├── scripts/
│   ├── batch_utils.py
│   ├── phase_a_*.py            # Clean / split / build evalsets / verify
│   ├── phase_b_batch.py        # Baseline (off-the-shelf rubric)
│   ├── phase_c_all_at_once.py  # AllAtOnce
│   ├── phase_c_constraint_grounded.py  # ConstraintGrounded
│   ├── phase_c_binary_search.py      # Not in paper scope
│   ├── trajectory_replayer.py
│   ├── reparse_batch.py
│   ├── render_dev_review.py
│   ├── {consolidate,finalize,…}.py   # Pre–Phase-A data prep
│   └── archive/
├── paper/draft/                # draft.md / draft_fixed.docx + figures
└── outputs/                    # gitignored — regenerate locally
```

## Reproducibility

```bash
# Phase A — clean + split + build EvalSets (must exit 0)
python3 scripts/phase_a_verify.py

# Phase B — off-the-shelf rubric baseline (Vertex batch; default judge in scripts)
python3 scripts/phase_b_batch.py --split dev
python3 scripts/phase_b_batch.py --split eval

# Phase C — custom evaluators (paper’s AllAtOnce + ConstraintGrounded)
python3 scripts/phase_c_all_at_once.py --split dev
python3 scripts/phase_c_all_at_once.py --split eval
python3 scripts/phase_c_constraint_grounded.py --split eval   # plus other flags as in script --help

# Re-align batch predictions if row order drifted
python3 scripts/reparse_batch.py --phase b --predictions <path-to-predictions.jsonl>

# Human-readable dev review (Phase B + C side-by-side)
python3 scripts/render_dev_review.py
```

## Config

- `.env` (gitignored): set `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` as in your Vertex setup; preview models may use `global`.
- Default judge model in scripts is aligned with the paper runs (`gemini-3.1-pro-preview` class on Vertex).
- Batch artifacts are uploaded under `gs://agenttracebucket/` for long runs (see script output and your local run logs).

## Documentation map

- **Paper-facing narrative and tables:** `docs/reports/step4_results.md`, `docs/reports/step4_scorecard.md` (+ `.json`).
- **Methods / dataset construction:** `docs/reports/step1_data_cleaning.md`, `step2_consolidation.md`, `step3_taxonomy_review.md`, `step4_plan.md`.
