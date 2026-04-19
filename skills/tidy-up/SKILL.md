---
name: tidy-up
description: Organize a messy project folder into a sensible directory structure. Trigger whenever the user asks to "tidy up", "clean up", "organize", "restructure", or "reorganize" their files, folder, project, or workspace — even when they phrase it casually ("this folder is a mess", "can you sort out my downloads"). Also trigger when the user is clearly working in a sprawling folder with mixed file types (notes, code, data, PDFs, docs) and wants to impose structure before continuing. Do NOT use this skill to draft documents or research papers — it is scoped to folder organization only; file drafting is a separate concern.
---

# Tidy Up — Project Folder Organization

## What this skill does

Imposes a coherent directory structure on a project folder based on what's actually inside it. It is deliberately **non-destructive**: nothing is deleted, all moves are proposed to the user before execution, and the user can override any proposed move.

## When to use it

- A folder has accumulated mixed file types (notes, scripts, data files, PDFs, draft docs, random exports) without obvious structure.
- The user is about to start a new phase of work and wants a clean slate.
- A collaborator or Claude has been producing output files in the root of a project and clutter is building up.
- Reports, drafts, and ad-hoc notes are mingled with raw data, reference material, or code.

## What this skill does NOT do

- **No file drafting.** This skill does not write reports, papers, summaries, or consolidations — those are separate tasks. If the user asks to tidy up AND draft something, do the tidy-up first, then treat the drafting as a follow-on request.
- **No deletion.** Never rm files. If the user wants to prune, surface candidates and ask them to confirm, then use the appropriate delete-permission tool.
- **No blind moves.** Always show the proposed plan before executing.

## Workflow

### 1. Survey the folder

Before proposing anything, understand what's there. Run a recursive listing (excluding obvious noise like `.DS_Store`, `node_modules/`, `.git/`, `~$` lock files). Note:

- Total file count and approximate size distribution.
- File-type clusters: Markdown/Word docs, PDFs, code (`.py`, `.js`, `.ipynb`, etc.), data (`.csv`, `.json`, `.jsonl`, `.xlsx`, `.parquet`, `.arrow`), images, archives.
- Files that look like outputs vs inputs vs source vs references.
- Any existing subfolders — those are signals about the user's intent.

### 2. Infer the project type

The right structure depends on the kind of work happening in the folder. Pick the closest match:

- **Research / experiment project** — mix of data, scripts, reports, reference PDFs, draft paper. Suggests:
  ```
  ├── docs/
  │   ├── PROJECT.md (evolving state)
  │   └── reports/    (stepwise notes)
  ├── data/
  │   ├── raw/        (source datasets)
  │   └── processed/  (cleaned/consolidated outputs)
  ├── scripts/        (processing code)
  └── paper/
      ├── draft.md
      └── references/ (citations, PDFs)
  ```
- **Software project** — source code dominates. Suggests: `src/`, `tests/`, `docs/`, `scripts/`, `data/`, `README.md`.
- **Writing project** — narrative docs dominate. Suggests: `drafts/`, `references/`, `notes/`, `assets/`, `final/`.
- **General scratch / Downloads** — no coherent project. Suggest clustering by file type: `documents/`, `spreadsheets/`, `code/`, `images/`, `archives/`, `misc/`, with a date-based subfolder if files are old.

The user's existing folders should bias the choice — don't invent a structure that conflicts with an obvious pattern already in use.

### 3. Propose the plan

Before moving anything, show the user a plan with:

- The proposed target folder structure (as a tree).
- A concrete list of "this file → that folder" moves.
- Files that are ambiguous and need user guidance.
- Files that look like noise and could be deleted (but ask, never assume).

Good format:
```
Proposed structure:
  data/raw/
  data/processed/
  scripts/
  docs/reports/

Moves:
  old_report.md       → docs/reports/
  old_report_v2.md    → docs/reports/
  consolidate.py      → scripts/
  raw_dataset.json    → data/raw/

Needs your input:
  notes_april.txt     → ? (docs/notes/ or drop into scratch/?)

Noise candidates (leave in place unless you confirm):
  .DS_Store (3 files)
  ~$draft.docx (lock file)
```

Wait for the user to approve or adjust before executing.

### 4. Execute

Use `mv` (shell) to perform moves. Create target directories with `mkdir -p` before moving into them. Do this in a single batch so the user sees one summary rather than a play-by-play.

After moving, run a final `find` (or `ls -R`) to confirm the result matches the plan, and show the user the new tree.

### 5. Update cross-references

File moves often break links in existing docs. After the reorganization:

- Scan Markdown files for links that pointed at moved files (`](./old/path`) and update them.
- Flag any code that references moved files by relative path.
- If there's a `CLAUDE.md` or `README.md`, check whether it points to any of the moved files and update those paths.

This step is easy to forget but important — broken links are the most common regret after a reorganization.

## Design principles

**Ask before destructive operations.** Moves feel destructive to users because they break muscle memory. Show the plan, let them veto.

**Match the project type.** A code project wants `src/tests/`; a research project wants `data/scripts/docs/paper/`. Don't force one pattern onto the wrong context.

**Respect existing structure.** If half the folder is already organized and half is messy, extend the existing pattern instead of inventing a new one.

**Keep names short and predictable.** `docs/` not `documentation/`. `data/` not `datasets_and_experimental_inputs/`. Use plural names for folders containing multiple items (`reports/`, `scripts/`) and singular for single-purpose folders (`paper/`, `src/`).

**One top-level concept per folder.** Each folder should answer "what kind of thing lives here?" in one word.

## Common mistakes to avoid

- **Moving files before the user has agreed.** Always confirm the plan first.
- **Deleting what looks like junk.** Lock files (`~$foo.docx`), hidden OS files (`.DS_Store`), editor backups (`foo.py~`) — only remove these if the user explicitly asks.
- **Inventing structure the user didn't ask for.** If the folder just needs three files moved, don't propose a 10-folder refactor.
- **Forgetting to update references.** After moves, update `CLAUDE.md`, `README.md`, and any docs that linked to moved files.
- **Silently handling ambiguity.** If you can't tell where a file belongs, ask. Don't guess.

## Example interaction

> User: "can you tidy up this folder? it's a mess"

1. Survey → find 18 files in root: 3 reports (`.md`), 5 Python scripts, 2 JSONL data files, 4 reference PDFs, 1 Excel sheet from the user, 3 draft docs.
2. Infer → research project pattern.
3. Propose:
   - Target: `docs/reports/`, `scripts/`, `data/`, `paper/references/`, `paper/draft/`.
   - Moves enumerated.
   - Flag: the Excel sheet (user-created, unclear if it should move).
4. User approves.
5. Execute, update links in `CLAUDE.md`, show final tree.

Done. Takes 2-3 minutes for a typical research folder.
