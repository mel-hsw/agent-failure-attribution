# Failure Attribution Experiment — Claude Instructions

## Core goal

Evaluate whether the **Google ADK evaluation suite** can accurately perform **failure attribution** on execution trajectories from multi-agent systems tested on the **GAIA benchmark**. The eval suite's job is to identify the **failure origin** — the earliest step at which the error enters the trajectory — regardless of whether the failure is node-level (localized) or process-level (cascading, surfaces later).

## Working agreement

- Before classifying anything, list every distinct label / reasoning signature with representative examples so Mel can validate.
- Keep GAIA as the canonical benchmark scope.
- Treat CLAUDE.md as the **stable** contract (objective + working agreement). Evolving details — taxonomy iterations, data sources, report status, next steps — live in `docs/PROJECT.md`.
- Node-level vs process-level is the core conceptual framework. Specific category names within each level are guidelines, not mandates — let the data suggest the right clusters.
- When the data suggests a cluster that doesn't map onto an existing category, keep it as its own cluster rather than forcing it in.

## Where to find project state

- `docs/PROJECT.md` — evolving taxonomy, data sources, decisions log, next steps.
- `docs/reports/` — stepwise reports (data cleaning, consolidation, taxonomy review).
- `data/consolidated/` — finalized inputs for the evaluation suite.
- `paper/` — research paper draft and reference materials.
- `scripts/` — consolidation, classification, and verification scripts.
