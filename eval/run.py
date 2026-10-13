"""Run the review agents over the evaluation cases and write a report.

    uv run python -m eval.run                      # all cases, writes eval/results.md
    uv run python -m eval.run --case sql_injection_fstring --case clean_docs_typo
    uv run python -m eval.run --update-readme      # also refresh the README table

Uses the same LLM and review settings as the bot (LLM_*, ANTHROPIC_API_KEY, REVIEW_* from
the environment or `.env`), but no GitHub App. Calls the real LLM, so it costs money.
"""

import argparse
import asyncio
import logging
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from eval.cases import CASES_DIR, EvalCase, load_cases
from eval.pricing import cost_usd
from eval.report import CaseResult, RunInfo, embed_in_readme, full_report, summary_table
from eval.scoring import Counts, score_case
from reviewcrew.agents.registry import AGENT_CLASSES
from reviewcrew.config import CoreSettings
from reviewcrew.diff.processor import process_diff
from reviewcrew.llm.base import LLMProvider, TokenUsage
from reviewcrew.llm.factory import open_llm_provider
from reviewcrew.logging_config import configure_logging
from reviewcrew.pipeline.aggregator import aggregate
from reviewcrew.pipeline.options import ReviewOptions
from reviewcrew.pipeline.orchestrator import run_agents

logger = logging.getLogger("eval")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "eval" / "results.md"
README = ROOT / "README.md"


async def evaluate_case(
    case: EvalCase, llm: LLMProvider, options: ReviewOptions, *, model: str
) -> CaseResult:
    diff = process_diff(case.diff, options.diff, new_contents=case.head_contents)
    agents = [AGENT_CLASSES[name](llm, language="en") for name in options.agents]
    started = time.monotonic()
    results = await run_agents(
        agents,
        diff.chunks,
        pr_title=case.title,
        deleted_files=diff.deleted_paths,
        agent_timeout_seconds=options.agent_timeout_seconds,
        max_concurrent_calls=options.max_concurrent_llm_calls,
    )
    duration = time.monotonic() - started
    findings = aggregate((f for r in results for f in r.findings), options.aggregation).findings
    usage = sum((r.usage for r in results), TokenUsage())
    return CaseResult(
        name=case.name,
        clean=case.is_clean,
        counts=score_case(findings, case.expected, case.scored),
        usage=usage,
        cost_usd=cost_usd(model, usage),
        duration_seconds=duration,
        errors=tuple(f"{r.agent}: {e}" for r in results for e in r.errors),
    )


async def evaluate(
    cases: Sequence[EvalCase],
    llm: LLMProvider,
    options: ReviewOptions,
    *,
    model: str,
    parallel_cases: int = 2,
) -> list[CaseResult]:
    semaphore = asyncio.Semaphore(parallel_cases)

    async def one(case: EvalCase) -> CaseResult:
        async with semaphore:
            result = await evaluate_case(case, llm, options, model=model)
            counts = sum(result.counts.values(), Counts())
            logger.info(
                "%-32s tp=%d fp=%d fn=%d tokens=%d %.1fs",
                case.name,
                counts.tp,
                counts.fp,
                counts.fn,
                result.usage.total_tokens,
                result.duration_seconds,
            )
            return result

    return list(await asyncio.gather(*(one(case) for case in cases)))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_DIR, help="cases directory")
    parser.add_argument("--case", action="append", default=[], help="run only this case")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown report")
    parser.add_argument("--parallel-cases", type=int, default=2)
    parser.add_argument(
        "--update-readme", action="store_true", help="refresh the results table in README.md"
    )
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = CoreSettings()
    configure_logging(settings.log_level)
    logging.getLogger("eval").setLevel(logging.INFO)

    cases = load_cases(args.cases, only=set(args.case) or None)
    if not cases:
        print("No cases selected.", file=sys.stderr)
        return 2
    options = settings.review_options().model_copy(update={"token_budget": None})
    info = RunInfo(
        model=settings.llm_model,
        settings=(f"effort {settings.llm_effort}, " if settings.llm_provider == "anthropic" else "")
        + f"min confidence {settings.review_min_confidence}",
        date=datetime.now(UTC).strftime("%Y-%m-%d"),
    )

    async with open_llm_provider(settings) as llm:
        results = await evaluate(
            cases, llm, options, model=settings.llm_model, parallel_cases=args.parallel_cases
        )

    args.output.write_text(full_report(results, info), encoding="utf-8", newline="\n")
    table = summary_table(results, info)
    print(table)
    print(f"\nFull report: {args.output}")
    if args.update_readme:
        README.write_text(
            embed_in_readme(README.read_text(encoding="utf-8"), table),
            encoding="utf-8",
            newline="\n",
        )
        print(f"Updated {README.name}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
