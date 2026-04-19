# Cluster Review — Handoff Instructions

_Last updated: 2026-04-18 after Batch 4_

## What you are doing

We are going row-by-row through `data/consolidated/gaia_consolidated.jsonl` (154 records) to verify that each record's `proposed_cluster` / `proposed_cluster_label` is correct under the **extended cluster definitions** that now live in `docs/reports/step3_taxonomy_review.md` (lines 44–150).

Mel wants one batch at a time, with reasoning shown. Do not try to grind through everything in one turn. The point of the review is that Mel reads each proposed change and confirms it before it's written into the patch file.

## The taxonomy (9 clusters)

| ID | Label | Level |
|---|---|---|
| N1 | Hallucination / factual fabrication | node |
| N2 | Code implementation bug | node |
| N3 | Tool execution / retrieval failure | node |
| N4 | Wrong tool selection | node |
| N5 | Invalid parameters / malformed input | node |
| P1 | Improper task decomposition / bad plan | process |
| P2 | Progress misassessment | process |
| P3 | Cascading error from earlier step | process |
| P4 | Constraint ignorance | process |

**Always read the extended definitions in `docs/reports/step3_taxonomy_review.md` before judging — the section-specific tests (counterfactual tests, boundary language against nearest neighbors) are what you apply, not the one-line labels above.**

Quick recall tests that keep coming up:

- **P1** — "If every step of this plan were executed perfectly, would the task succeed?" If no, it's P1.
- **N2** — code that *runs* but returns wrong output. If the code has no bug, it's not N2, even if "code" is mentioned in the reasoning.
- **N5** — right tool, malformed/wrong argument (includes URLs that don't correspond to the target, placeholder strings like `example_video_id`, etc.).
- **P2** — agent misassesses its own state of progress (includes misreading tool output, pretending to have done work it didn't do, claiming a capability it doesn't have).
- **N3** — tool *was* invoked and the tool/environment failed. If no tool was invoked, it's probably not N3.
- **N1** — asserts a concrete factual claim without grounding. If the claim came from a tool's output (even if misread), it's P2, not N1.

## The workflow

1. **Pull a batch of 5 records** using the helper script at `outputs/pull_batch.py`:
   ```bash
   cd /sessions/festive-sweet-mendel/mnt/outputs && python3 pull_batch.py <source> <start> 5
   ```
   where `<source>` is one of:
   - `WhoAndWhen-AlgorithmGenerated` (75 records, indices 0–74)
   - `WhoAndWhen-HandCrafted` (29 records, indices 0–28)
   - `AgentErrorBench` (50 records, indices 0–49)

   The script prints, for each record: trajectory_id, agent_role, critical_failure_step, proposed cluster, the failure reasoning, the task (from step 0), the critical step content, and the prior step for context.

2. **For each record in the batch, write an analysis block** with this structure (keep it tight):
   - Header: `### #<index> · <trajectory_id> · <agent_role> · step <n> · Current: **<cluster>**`
   - **Task.** one-sentence summary.
   - **Agent at step N.** what the agent actually said/did, concretely — quote key phrases if it helps.
   - **Annotator.** the failure reasoning text, short.
   - **Reasoning.** walk through the extended definition that matches (or doesn't). Name nearest-neighbor clusters and say why they don't fit.
   - **Verdict.** one of:
     - `KEEP <cluster>` — current label stands
     - `CHANGE <old> → <new>` — propose a different cluster
     - `FLAG` — something's off (e.g. step 0 that is actually the prompt delivery, not an agent action; reasoning too thin to pin a mechanism)
     - `DROP` — parallel to the thin-reasoning rows Mel already dropped

3. **End the batch with a summary table** and any emergent patterns you noticed across the batch.

4. **Wait for Mel's verdicts** before writing to the patch file or pulling the next batch. Mel will say things like "keep p1", "change 22 to n5", "drop 17 and 18". Apply only what Mel accepted.

5. **When Mel accepts CHANGE or DROP verdicts, append to the patch file**:
   `data/consolidated/cluster_review_patch.jsonl` — one JSON line per change:
   ```json
   {"trajectory_id": "<id>", "old_cluster": "<old>", "new_cluster": "<new-or-DROP>", "reason": "<1–2 sentence justification>"}
   ```
   KEEP verdicts do not go in the patch file.

6. **Pull the next batch.**

## Progress so far

**Reviewed: 20 of 154 (WhoAndWhen-AlgorithmGenerated #0–19)**

Patch file currently has 5 entries:

| # | trajectory_id | change | note |
|---|---|---|---|
| 3 | `WW-AG-9318445f` | N1 → P2 | OCR misread, not fabrication |
| 6 | `WW-AG-0512426f` | N1 → N5 | `example_video_id` placeholder |
| 4 | `WW-AG-0383a3ee` | N3 → P2 | Agent didn't invoke any tool |
| 8 | `WW-AG-48eb8242` | N3 → N5 | Fabricated USGS URL |
| 13 | `WW-AG-50ec8903` | N1 → DROP | Thin reasoning, matches prior drops |

**Batch 4 (#15–19) decisions (just confirmed by Mel, 2026-04-18):**
- #15 N1 → KEEP (fabricated cuneiform symbol values)
- #16 N1 → KEEP (clean N1 — fabricated population figures)
- #17 P1 → **KEEP** (degenerate trajectory, but P1 stands)
- #18 P1 → **KEEP** (degenerate trajectory, but P1 stands)
- #19 P2 → KEEP (textbook P2 — hypothetical board, didn't view image)

## Where to pick up

**Next: Batch 5 — WhoAndWhen-AlgorithmGenerated records #20–24.**

Run:
```bash
cd /sessions/festive-sweet-mendel/mnt/outputs && python3 pull_batch.py WhoAndWhen-AlgorithmGenerated 20 5
```

Then continue in batches of 5 until all 75 WW-AG rows are done (batches 5–15 cover #20–74).

After WW-AG, move to **WhoAndWhen-HandCrafted** (29 records, ~6 batches of 5):
```bash
python3 pull_batch.py WhoAndWhen-HandCrafted 0 5
```

Then **AgentErrorBench** (50 records, ~10 batches):
```bash
python3 pull_batch.py AgentErrorBench 0 5
```

## Known patterns to watch for

From the first 20 records, these were the recurring mislabels:

1. **N1 over-applied to non-fabrication failures.** If the "wrong fact" was read from actual tool output, the mechanism is P2 (misread) or N5 (bad query), not N1. N1 requires the agent to *invent* the claim with no retrieval backing it.

2. **N3 over-applied to cases where no tool was invoked.** N3 is about the tool/environment failing. If the agent just declared progress without calling a tool, that's P2. If the agent called the right tool with a bad URL / placeholder argument, that's N5.

3. **"Made a mistake in [operation]" pulled toward N2 even for prose arithmetic.** N2 needs executable code with a bug. Arithmetic done in a chat bubble without code is not N2. If the agent said 2+2=5 with no code involved, look at whether it's P1 (bad approach) or N1 (invented number).

4. **"The answer was incorrect" rows are too thin to classify.** Mel has been dropping these (4 were dropped pre-session, 1 dropped in batch 3). If you see one, flag for drop.

5. **Step 0 labeled as the agent's failure step is suspect.** In Who_and_When, step 0 is the manager/user delivering the task+plan to the agent. If the annotator flagged step 0, ask whether the problem is actually in the *prompt* (manager's plan) rather than agent behavior. Can still be P1 but worth flagging. (See #17 and #18.)

## When review is complete

After all 154 → 153 records are reviewed:

1. **Apply the patch** — write a script that reads `data/consolidated/cluster_review_patch.jsonl` and updates `data/consolidated/gaia_consolidated.jsonl`:
   - For `new_cluster == "DROP"`: remove the record.
   - Otherwise: set `proposed_cluster` to the new ID, update `proposed_cluster_label` to the new label, update `proposed_level` (N* → node, P* → process).
2. **Update `failure_classifications.csv`** with the same changes (derived from the consolidated file).
3. **Update `docs/reports/step3_taxonomy_review.md`** with the post-review cluster counts.
4. **Update `docs/PROJECT.md`** — note final dataset size (starts from 154; subtract every DROP in the patch) and that Step 3 cluster verification is complete.

## Quick reference — file locations

| Purpose | Path |
|---|---|
| Main dataset | `data/consolidated/gaia_consolidated.jsonl` |
| Patch file (running) | `data/consolidated/cluster_review_patch.jsonl` |
| Extended cluster defs | `docs/reports/step3_taxonomy_review.md` (lines 44–150) |
| Project contract | `CLAUDE.md` |
| Project state | `docs/PROJECT.md` |
| Batch puller | `outputs/pull_batch.py` (in Cowork outputs dir) |

## Tone / style

Mel wants evidence-based, concise reasoning — quote the agent verbatim when the actual output is the deciding factor, name the nearest-neighbor cluster explicitly when arguing against it, and don't pad. A single batch of 5 analyses should fit comfortably in one response. Wait for Mel's verdicts — don't auto-advance.
