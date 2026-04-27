"""Loki log collector.

Queries Loki's HTTP API for error logs, log volume, and OOM warnings.
Log lines are truncated to manage token usage when passed to the LLM.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import httpx
import structlog

from ..config import Settings
from ..models.signals import LogSignal

log = structlog.get_logger(__name__)

MAX_LINE_LENGTH = 200  # chars — truncated before sending to LLM
MAX_LINES_PER_QUERY = 50

# ---------------------------------------------------------------------------
# LogQL queries
# ---------------------------------------------------------------------------
LOG_QUERIES: dict[str, str] = {
    "recent_errors_broken": '{kubernetes_labels_app="dtx-app-broken"} |~ "(?i)(error|exception|traceback|500)"',
    "recent_errors_healthy": '{kubernetes_labels_app="dtx-app"} |~ "(?i)(error|exception|traceback|500)"',
    "oom_warnings": '{kubernetes_labels_app=~"dtx-app.*"} |~ "(?i)(oom|out of memory|killed|evict)"',
}

# Metric (aggregation) queries — these return a matrix, not log streams
METRIC_QUERIES: dict[str, str] = {
    "log_volume_broken": 'sum(count_over_time({kubernetes_labels_app="dtx-app-broken"}[5m]))',
    "log_volume_healthy": 'sum(count_over_time({kubernetes_labels_app="dtx-app"}[5m]))',
    "error_log_volume_broken": (
        'sum(count_over_time({kubernetes_labels_app="dtx-app-broken"} |~ "(?i)(error|exception)"[5m]))'
    ),
}


def _detect_level(line: str) -> str:
    """Infer log level from the content of a log line."""
    lower = line.lower()
    if any(w in lower for w in ("error", "exception", "critical", "fatal", "traceback", "500")):
        return "ERROR"
    if any(w in lower for w in ("warn", "warning")):
        return "WARNING"
    if "debug" in lower:
        return "DEBUG"
    return "INFO"


def _truncate(line: str) -> str:
    return line[:MAX_LINE_LENGTH] + ("…" if len(line) > MAX_LINE_LENGTH else "")


def _deduplicate(signals: list[LogSignal]) -> list[LogSignal]:
    """Merge identical messages into a single entry with a count."""
    seen: dict[str, LogSignal] = {}
    for s in signals:
        key = s.source + ":" + s.message
        if key in seen:
            seen[key] = seen[key].model_copy(update={"count": seen[key].count + 1})
        else:
            seen[key] = s
    return list(seen.values())


async def _query_log_stream(
    client: httpx.AsyncClient,
    query_name: str,
    logql: str,
    start_ns: int,
    end_ns: int,
) -> list[LogSignal]:
    """Execute a LogQL stream query and return parsed LogSignals."""
    signals: list[LogSignal] = []
    try:
        resp = await client.get(
            "/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": str(MAX_LINES_PER_QUERY),
                "direction": "backward",
            },
        )
        resp.raise_for_status()
        streams = resp.json().get("data", {}).get("result", [])

        for stream in streams:
            stream_labels = stream.get("stream", {})
            app_label = stream_labels.get("kubernetes_labels_app") or stream_labels.get("app", "unknown")
            for ts_str, line in stream.get("values", []):
                clean = _truncate(line.strip())
                signals.append(
                    LogSignal(
                        source=app_label,
                        message=clean,
                        level=_detect_level(line),
                        timestamp=datetime.fromtimestamp(
                            int(ts_str) / 1e9, tz=timezone.utc
                        ),
                    )
                )

        log.debug("loki.stream_ok", query=query_name, lines=len(signals))
    except httpx.TimeoutException:
        log.error("loki.timeout", query=query_name)
    except httpx.HTTPStatusError as exc:
        log.error("loki.http_error", query=query_name, status=exc.response.status_code)
    except Exception as exc:  # noqa: BLE001
        log.error("loki.unexpected_error", query=query_name, error=str(exc))

    return signals


async def _query_metric(
    client: httpx.AsyncClient,
    query_name: str,
    logql: str,
    start_ns: int,
    end_ns: int,
) -> list[LogSignal]:
    """Execute a LogQL metric query (count_over_time etc.) and return summary signals."""
    signals: list[LogSignal] = []
    try:
        resp = await client.get(
            "/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": str(start_ns),
                "end": str(end_ns),
                "step": "60",
            },
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("result", [])

        for series in results:
            app_label = series.get("metric", {}).get("app", query_name)
            values = series.get("values", [])
            if values:
                # Take the latest value
                ts_str, val = values[-1]
                signals.append(
                    LogSignal(
                        source=app_label,
                        message=f"Log volume: {float(val):.0f} lines in last 5m",
                        level="INFO",
                        count=int(float(val)),
                        timestamp=datetime.fromtimestamp(float(ts_str), tz=timezone.utc),
                    )
                )

        log.debug("loki.metric_ok", query=query_name, series=len(results))
    except Exception as exc:  # noqa: BLE001
        log.error("loki.metric_error", query=query_name, error=str(exc))

    return signals


async def collect(settings: Settings) -> list[LogSignal]:
    """Query Loki and return a deduplicated flat list of LogSignals."""
    signals: list[LogSignal] = []

    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - settings.query_lookback_minutes * 60 * int(1e9)

    async with httpx.AsyncClient(
        base_url=settings.loki_url,
        timeout=settings.http_timeout,
    ) as client:
        # Log stream queries
        for qname, logql in LOG_QUERIES.items():
            result = await _query_log_stream(client, qname, logql, start_ns, end_ns)
            signals.extend(result)

        # Metric queries (log volume)
        for qname, logql in METRIC_QUERIES.items():
            result = await _query_metric(client, qname, logql, start_ns, end_ns)
            signals.extend(result)

    deduped = _deduplicate(signals)
    log.info("loki.collected", raw=len(signals), deduplicated=len(deduped))
    return deduped
