"""CLI and matrix runner. Default execution never constructs an LLM provider."""

import argparse
import asyncio
import hashlib
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from donewise_sim.config import Settings

from .llm_runner import run_llm
from .report import markdown, summarize
from .scenarios import NOW, SCENARIOS, VERSION, deterministic
from .world import World


async def run_suite(root, *, runner="deterministic", settings=None, model_factory=None):
    rows = []
    for scenario in SCENARIOS:
        for variant in ("baseline", "donewise"):
            world = World(root / f"{scenario.id}-{variant}", scenario, variant)
            async with world.connect():
                timed_out = False
                try:
                    async with asyncio.timeout(30):
                        if runner == "deterministic":
                            await deterministic(world)
                        else:
                            model = model_factory(variant) if model_factory else None
                            await run_llm(world, settings, model)
                except TimeoutError:
                    timed_out = True
                if world.app:
                    harness = world.app.state.harness
                    await asyncio.wait_for(asyncio.to_thread(harness.wait_for_workers, 5), 5)
                    if any(w.is_alive() for w in harness._workers.values()):
                        raise RuntimeError(
                            "Workers did not quiesce; no complete aggregate can be published"
                        )
                row = world.result(runner)
                row["timed_out"] = timed_out
                if timed_out:
                    row["metrics"]["completed"] = False
                if runner == "llm":
                    row["llm"] = world.llm_record
                    row["claims_reviewed"] = (
                        not world.llm_record["utterances"] and variant == "donewise"
                    )
                rows.append(row)
    return rows


def git_state():
    def read(*args):
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "revision": read("rev-parse", "HEAD"),
        "dirty": bool(read("status", "--porcelain")),
        "diff_stat": read("diff", "--stat"),
        "source_sha256": {
            path.as_posix(): hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            for path in sorted(
                [Path("pyproject.toml"), Path("uv.lock")]
                + [
                    p
                    for folder in ("core", "adapters", "server", "sim", "evals/donewise_evals")
                    for p in Path(folder).rglob("*.py")
                ]
            )
        },
    }


def main():
    for name in ("mcp", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", choices=("deterministic", "llm"), default="deterministic")
    parser.add_argument("--output-dir", type=Path, default=Path("evals/results"))
    args = parser.parse_args()
    settings = None
    if args.runner == "llm":
        settings = Settings()
        if settings.llm_provider not in ("none", "bedrock", "anthropic"):
            parser.error("LLM_PROVIDER must be none, bedrock or anthropic")
        if settings.llm_provider == "none":
            print("SKIPPED: LLM_PROVIDER=none")
            return
        if settings.llm_provider == "bedrock" and not settings.bedrock_model_id:
            parser.error("BEDROCK_MODEL_ID is required")
        if settings.llm_provider == "anthropic" and not settings.anthropic_api_key:
            parser.error("ANTHROPIC_API_KEY is required")
    report = {
        "run_id": "run_" + uuid4().hex,
        "matrix_version": VERSION,
        "runner": args.runner,
        "logical_clock": NOW.isoformat(),
        "timing_note": "Diagnostic only: logical clock; read window not simulated. "
        "Real verification latency requires RF-13 with real adapters.",
        "git": git_state(),
        "configuration": {
            "horizon_seconds": 30,
            "poll_seconds": 0.1,
            "cleanup_seconds": 5,
            "provider": settings.llm_provider if settings else "none",
            "model": (
                settings.bedrock_model_id
                if settings.llm_provider == "bedrock"
                else settings.anthropic_model
            )
            if settings
            else None,
        },
        "command": f"uv run donewise-evals --runner {args.runner} "
        f'--output-dir "{args.output_dir.as_posix()}"',
    }
    with TemporaryDirectory(prefix="donewise-evals-") as temp:
        try:
            report["rows"] = asyncio.run(
                run_suite(Path(temp), runner=args.runner, settings=settings)
            )
        except Exception as exc:
            # A partial run is never published as a complete result. Do not echo provider secrets.
            parser.exit(
                1, f"Evaluation incomplete ({type(exc).__name__}); no complete results published.\n"
            )
    report["summary"] = summarize(report["rows"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y-%m-%d") + "-sandbox" + ("-llm" if settings else "")
    if (args.output_dir / (name + ".json")).exists() or (args.output_dir / (name + ".md")).exists():
        name += "-" + report["run_id"]
    content = markdown(report)
    (args.output_dir / (name + ".json")).write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / (name + ".md")).write_text(content, encoding="utf-8")
    print(content)
    print(f"Results: {args.output_dir / name}")


if __name__ == "__main__":
    main()
