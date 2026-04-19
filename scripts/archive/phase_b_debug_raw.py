"""Debug helper — run Phase B on 1 case and dump the raw auto_rater_response.

Monkey-patches DefaultAutoRaterResponseParser.parse to log every raw LLM
response into outputs/phase_b/debug/raw_responses.txt, then calls the same
code path as phase_b_rubric_baseline.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phase_b_rubric_baseline import (  # noqa: E402
    build_evaluator,
    build_invocation,
    load_env,
    load_rubrics,
    EVALSET_DIR,
)

OUT = REPO_ROOT / "outputs" / "phase_b" / "debug"
OUT.mkdir(parents=True, exist_ok=True)
RAW_LOG = OUT / "raw_responses.txt"


async def main() -> int:
    load_env()

    # Monkey-patch the parser to log raw LLM responses.
    from google.adk.evaluation import rubric_based_evaluator as rbe

    original_parse = rbe.DefaultAutoRaterResponseParser.parse
    raw_log = RAW_LOG.open("w")
    call_idx = {"n": 0}

    def patched_parse(self, auto_rater_response: str):
        call_idx["n"] += 1
        raw_log.write(f"\n\n===== RAW LLM RESPONSE #{call_idx['n']} =====\n")
        raw_log.write(auto_rater_response)
        raw_log.write("\n===== END =====\n")
        raw_log.flush()
        return original_parse(self, auto_rater_response)

    rbe.DefaultAutoRaterResponseParser.parse = patched_parse

    split = "dev"
    evalset_path = EVALSET_DIR / f"{split}.with_gt.evalset.json"
    evalset = json.loads(evalset_path.read_text())
    case = evalset["eval_cases"][2]  # the all-scored-yes case (b4cc024b)
    print(f"Case: {case['eval_id']}")

    rubrics = load_rubrics()
    evaluator = build_evaluator("gemini-2.5-flash", 1, rubrics)
    inv = build_invocation(case, rubrics)

    result = await evaluator.evaluate_invocations(actual_invocations=[inv])

    raw_log.close()
    print(f"Raw responses: {RAW_LOG}")
    # Dump per-rubric scores + rationales
    dump = OUT / "parsed_result.json"
    per_inv = []
    for pir in (getattr(result, "per_invocation_results", None) or []):
        scores = []
        for rs in (getattr(pir, "rubric_scores", None) or []):
            scores.append({"rubric_id": rs.rubric_id, "score": rs.score, "rationale": rs.rationale})
        per_inv.append({"scores": scores})
    dump.write_text(json.dumps({"case": case["eval_id"], "per_invocation": per_inv}, indent=2))
    print(f"Parsed result: {dump}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
