"""Tier-1 static constraint checker for ConstraintGroundedAttribution.

Walks a pre-recorded trajectory and emits `ConstraintEvent`s for the five
Tier-1 static constraints retained in `docs/reports/step4_plan.md` §7.3:

- S4  no repeated identical tool call within 3 steps
- S5  no terminal "final answer" action before any info-gathering step (heuristic)
- S6  no tool calls after a terminal "final answer" action (heuristic)
- S8  tool-result error signals (404 / 500 / "not found" / timeout / empty)
- S9  per-agent step budget (default threshold: 30 steps from a single author)

All constraints here are pure Python (no LLM). The AgentRx-style dynamic
constraints D1-D9 are evaluated by an LLM in `phase_c_constraint_grounded.py`
and are merged with these static events into the final violation log.

Tool calls are detected by pattern-matching the inline `<action>...</action>`
blocks used by AEB (and partially by W&W) because our trajectories don't
expose structured tool-call objects — they're embedded in message `content`
strings. Detection is best-effort: when we can't parse a block we emit an
UNCLEAR verdict rather than pretending to have signal.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable


# ---------------------------------------------------------------------------
# Event model


@dataclass
class ConstraintEvent:
    step: int
    constraint_id: str
    verdict: str          # "CLEAR_PASS" | "CLEAR_FAIL" | "UNCLEAR"
    evidence: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Regexes. All constraints share this pool.

ACTION_BLOCK = re.compile(
    r"<action>\s*tool:\s*([A-Za-z0-9_.\-]+)\s*parameters:\s*(\{.*?\})\s*</action>",
    re.DOTALL,
)

# Terminal-action heuristic: strings that most commonly mark a "final answer"
# commit in the recorded systems. We never treat any single signal as definitive —
# S5/S6 emit UNCLEAR when the signal is ambiguous (e.g. just a "FINAL" token in
# prose) and CLEAR_FAIL only when the pattern is canonical (explicit action tag
# or `submit_final_answer`).
TERMINAL_STRONG = re.compile(
    r"(?:submit_final_answer|FINAL ANSWER\s*:|<final_answer>|\bfinal_answer\s*=)",
    re.IGNORECASE,
)
TERMINAL_WEAK = re.compile(r"\bFINAL ANSWER\b", re.IGNORECASE)

# S8 — tool-result error signatures. Kept conservative: only match when a
# message is plausibly a tool response (role is non-assistant / non-orchestrator
# or content starts with a status-like prefix).
ERROR_SIGNALS = re.compile(
    r"(?:\b(?:404|500|502|503)\b"
    r"|\btimeout(?:ed)?\b"
    r"|\bnot found\b"
    r"|context_length_exceeded"
    r"|\bERROR\b"
    r"|\bException\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers


def _content_text(msg: dict) -> str:
    c = msg.get("content")
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    return json.dumps(c, ensure_ascii=False)


def _author(msg: dict) -> str:
    return msg.get("name") or msg.get("role") or "unknown"


def _call_signature(tool_name: str, raw_args: str) -> str:
    """Stable hash over (tool, normalized args) for S4's duplicate check."""
    try:
        normalized = json.dumps(json.loads(raw_args), sort_keys=True)
    except Exception:
        normalized = raw_args.strip()
    h = hashlib.sha1(f"{tool_name}|{normalized}".encode()).hexdigest()[:12]
    return h


# ---------------------------------------------------------------------------
# Individual constraint functions


def _is_agent_action_step(msg: dict) -> bool:
    """True when the step plausibly represents the agent ISSUING a tool call,
    vs. a user message that's echoing the agent's prior action blocks as
    context. AEB-style trajectories re-emit prior `<action>` blocks inside
    user turns on every step; counting those as fresh calls inflates S4.

    Heuristic: only `assistant`/`model`/tool-like roles issue tool calls.
    W&W step names like `Orchestrator (thought)` are kept because they can
    embed action blocks in the generated plan text.
    """
    role = (msg.get("role") or "").lower()
    name = (msg.get("name") or "").lower()
    if role in ("assistant", "model", "tool", "function"):
        return True
    # W&W uses named roles like "Orchestrator (thought)" / "WebSurfer" / etc.
    if name and role not in ("user", "human"):
        return True
    if "orchestrator" in role or "agent" in role or "surfer" in role:
        return True
    return False


def check_s4_repeated_tool_calls(
    history: list[dict], window: int = 3
) -> list[ConstraintEvent]:
    """Flag any identical (tool, args) call that repeats within a sliding window
    of `window` tool-call invocations (not raw steps — info-gathering often
    alternates with assistant turns that don't fire tools)."""
    events: list[ConstraintEvent] = []
    recent: list[tuple[int, str]] = []  # (step, signature) over last `window` calls
    for i, msg in enumerate(history):
        if not _is_agent_action_step(msg):
            continue
        text = _content_text(msg)
        for match in ACTION_BLOCK.finditer(text):
            tool_name = match.group(1)
            raw_args = match.group(2)
            sig = _call_signature(tool_name, raw_args)
            duplicate = next(((s, _) for s, _ in recent if _ == sig), None)
            if duplicate is not None:
                events.append(
                    ConstraintEvent(
                        step=i,
                        constraint_id="S4",
                        verdict="CLEAR_FAIL",
                        evidence=(
                            f"Identical call to `{tool_name}` repeats step "
                            f"{duplicate[0]} → step {i} (sig {sig})."
                        ),
                    )
                )
            recent.append((i, sig))
            if len(recent) > window:
                recent.pop(0)
    return events


def _find_terminal_step(history: list[dict]) -> tuple[int | None, str]:
    """Return the first AGENT step whose content strongly signals a final-answer
    commit, plus confidence ("strong" | "weak"). Step 0 is always the user
    task (AEB and W&W both), so it's excluded — "FINAL ANSWER" appears there
    only as formatting instructions, not as a commit."""
    # Strong signal on agent steps only; skip step 0 (user task).
    for i, msg in enumerate(history):
        if i == 0 or not _is_agent_action_step(msg):
            continue
        if TERMINAL_STRONG.search(_content_text(msg)):
            return i, "strong"
    # Fall back to weak signal, same restrictions.
    for i, msg in enumerate(history):
        if i == 0 or not _is_agent_action_step(msg):
            continue
        if TERMINAL_WEAK.search(_content_text(msg)):
            return i, "weak"
    return None, "none"


def check_s5_early_terminal(history: list[dict]) -> list[ConstraintEvent]:
    """Fail if a terminal action is emitted before any tool call or substantive
    info-gathering step. Emits UNCLEAR on weak-signal terminal detections."""
    terminal_step, confidence = _find_terminal_step(history)
    if terminal_step is None:
        return []
    # Count tool calls strictly before the terminal step
    tool_calls_before = 0
    for i in range(terminal_step):
        if ACTION_BLOCK.search(_content_text(history[i])):
            tool_calls_before += 1
    if tool_calls_before == 0 and terminal_step <= 1:
        verdict = "CLEAR_FAIL" if confidence == "strong" else "UNCLEAR"
        return [
            ConstraintEvent(
                step=terminal_step,
                constraint_id="S5",
                verdict=verdict,
                evidence=(
                    f"Terminal-answer signal at step {terminal_step} with "
                    f"{tool_calls_before} tool calls beforehand (confidence={confidence})."
                ),
            )
        ]
    return []


def check_s6_tools_after_terminal(history: list[dict]) -> list[ConstraintEvent]:
    """Fail if any tool call appears after the detected terminal-action step.
    Only emits events when the terminal signal was STRONG; weak-signal matches
    are too noisy (e.g. the model narrating "this is my final answer" mid-trajectory)."""
    terminal_step, confidence = _find_terminal_step(history)
    if terminal_step is None or confidence != "strong":
        return []
    events: list[ConstraintEvent] = []
    for i in range(terminal_step + 1, len(history)):
        if not _is_agent_action_step(history[i]):
            continue
        if ACTION_BLOCK.search(_content_text(history[i])):
            events.append(
                ConstraintEvent(
                    step=i,
                    constraint_id="S6",
                    verdict="CLEAR_FAIL",
                    evidence=(
                        f"Tool call at step {i} follows terminal-answer signal "
                        f"at step {terminal_step} (confidence={confidence})."
                    ),
                )
            )
    return events


def check_s8_tool_errors(history: list[dict]) -> list[ConstraintEvent]:
    """Flag steps whose content contains an unhandled-looking error signature.

    AEB re-embeds the full task preamble (tool docstrings, few-shot examples)
    into every subsequent user message, so any error token present in step 0
    will spuriously match at every step thereafter. To suppress this, we
    compute the set of error tokens present in step 0 and require later
    matches to introduce a NEW token — i.e. a token not already in the task
    preamble. Only those represent fresh runtime errors.
    """
    events: list[ConstraintEvent] = []
    step0_text = _content_text(history[0]) if history else ""
    baseline_tokens = {m.group(0).lower() for m in ERROR_SIGNALS.finditer(step0_text)}

    for i, msg in enumerate(history):
        if i == 0:
            continue
        text = _content_text(msg)
        matches = [m.group(0).lower() for m in ERROR_SIGNALS.finditer(text)]
        fresh = [t for t in matches if t not in baseline_tokens]
        if not fresh:
            continue
        author = _author(msg).lower()
        is_tool_looking = (
            author == "tool"
            or "tool_result" in author
            or "result" in author
            or "response" in author
            or "(output)" in author
            or (author == "user" and i > 0)  # AEB user = tool output + prior context
        )
        verdict = "CLEAR_FAIL" if is_tool_looking else "UNCLEAR"
        excerpt = text.strip().replace("\n", " ")
        if len(excerpt) > 200:
            excerpt = excerpt[:200] + "..."
        events.append(
            ConstraintEvent(
                step=i,
                constraint_id="S8",
                verdict=verdict,
                evidence=f"Error signal(s) {fresh[:3]} in step {i} ({author}): {excerpt}",
            )
        )
    return events


def check_s9_step_budget(
    history: list[dict], threshold: int = 30
) -> list[ConstraintEvent]:
    """Flag when any single author produces more than `threshold` steps. Emits
    one summary event per over-budget author at the step where the budget was
    first exceeded."""
    events: list[ConstraintEvent] = []
    per_author: Counter = Counter()
    flagged: set[str] = set()
    for i, msg in enumerate(history):
        author = _author(msg)
        per_author[author] += 1
        if per_author[author] > threshold and author not in flagged:
            flagged.add(author)
            events.append(
                ConstraintEvent(
                    step=i,
                    constraint_id="S9",
                    verdict="CLEAR_FAIL",
                    evidence=(
                        f"Author `{author}` exceeded step budget (> {threshold}) "
                        f"first at step {i}."
                    ),
                )
            )
    return events


# ---------------------------------------------------------------------------
# Public orchestration


def replay(history: list[dict], step_budget: int = 30) -> list[ConstraintEvent]:
    """Run all five Tier-1 static constraints and return their events, sorted
    by step then constraint id."""
    events: list[ConstraintEvent] = []
    events.extend(check_s4_repeated_tool_calls(history))
    events.extend(check_s5_early_terminal(history))
    events.extend(check_s6_tools_after_terminal(history))
    events.extend(check_s8_tool_errors(history))
    events.extend(check_s9_step_budget(history, threshold=step_budget))
    events.sort(key=lambda e: (e.step, e.constraint_id))
    return events


def format_violation_log(events: Iterable[ConstraintEvent]) -> str:
    """Markdown-ish rendering for injection into a judge prompt."""
    events = list(events)
    if not events:
        return "_No static-constraint violations detected._"
    lines = ["| step | constraint | verdict | evidence |", "|---|---|---|---|"]
    for e in events:
        ev = e.evidence.replace("|", "\\|").replace("\n", " ")
        if len(ev) > 240:
            ev = ev[:240] + "..."
        lines.append(f"| {e.step} | {e.constraint_id} | {e.verdict} | {ev} |")
    return "\n".join(lines)
