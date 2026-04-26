"""AI Observability Agent — entry point.

Orchestrates the collection → analysis → output pipeline.

Usage:
    python -m src.main            # normal run
    python -m src.main --dry-run  # collect + analyse but only print, no side effects
    DRY_RUN=true python -m src.main
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import structlog

from .analyzer import llm_analyzer
from .collectors import loki, prometheus, tempo
from .config import Settings
from .models.signals import CollectedSignals
from .outputs import grafana, slack


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def configure_logging(log_level: str, dry_run: bool = False) -> None:
    """Configure structlog for JSON output in production or pretty output locally."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if dry_run or sys.stdout.isatty():
        # Human-friendly output for dev / dry-run
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # Loki-friendly JSON in production
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


async def run_pipeline(settings: Settings) -> int:
    """Collect signals, analyse, and dispatch outputs. Returns exit code."""
    log = structlog.get_logger(__name__)
    log.info(
        "agent.start",
        dry_run=settings.dry_run,
        lookback_minutes=settings.query_lookback_minutes,
    )

    # ---- Collect signals in parallel -----------------------------------------
    collector_errors: dict[str, str] = {}
    collected_at = datetime.now(tz=timezone.utc)

    async def _safe_prometheus():
        try:
            return await prometheus.collect(settings)
        except Exception as exc:  # noqa: BLE001
            collector_errors["prometheus"] = str(exc)
            return []

    async def _safe_loki():
        try:
            return await loki.collect(settings)
        except Exception as exc:  # noqa: BLE001
            collector_errors["loki"] = str(exc)
            return []

    async def _safe_tempo():
        try:
            return await tempo.collect(settings)
        except Exception as exc:  # noqa: BLE001
            collector_errors["tempo"] = str(exc)
            return []

    metrics, logs, traces = await asyncio.gather(
        _safe_prometheus(),
        _safe_loki(),
        _safe_tempo(),
    )

    signals = CollectedSignals(
        metrics=metrics,
        logs=logs,
        traces=traces,
        collected_at=collected_at,
        lookback_minutes=settings.query_lookback_minutes,
        collector_errors=collector_errors,
    )

    log.info(
        "agent.collection_complete",
        metrics=len(metrics),
        logs=len(logs),
        traces=len(traces),
        errors=len(collector_errors),
    )

    # ---- Analyse -------------------------------------------------------------
    result = await llm_analyzer.analyse(signals, settings)

    # ---- Dispatch outputs in parallel ----------------------------------------
    await asyncio.gather(
        slack.send(result, settings),
        grafana.post_annotation(result, settings),
    )

    log.info("agent.done", severity=result.severity)

    # Exit non-zero for CRITICAL so the CronJob registers a failure
    return 1 if result.severity == "CRITICAL" else 0


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Observability Agent — analyses dtx-app metrics/logs/traces via Claude."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and analyse but only print output; do not post to Slack or Grafana.",
    )
    args = parser.parse_args()

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    # Re-instantiate Settings so DRY_RUN env var is picked up
    settings = Settings()
    configure_logging(settings.log_level, settings.dry_run)

    exit_code = asyncio.run(run_pipeline(settings))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
