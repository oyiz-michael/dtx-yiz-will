"""Tempo trace collector.

Queries Tempo's HTTP search API for recent error traces across the dtx-app
services. Tempo's API is less structured than Prometheus/Loki so this
collector is deliberately lenient — if the API is unavailable or returns
unexpected data, it logs and returns an empty list rather than crashing.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import structlog

from ..config import Settings
from ..models.signals import TraceSignal

log = structlog.get_logger(__name__)

SERVICES = ["dtx-app", "dtx-app-broken"]


async def _search_service(
    client: httpx.AsyncClient,
    service_name: str,
    start: int,
    end: int,
    limit: int = 20,
) -> list[TraceSignal]:
    """Search Tempo for error traces for a specific service."""
    signals: list[TraceSignal] = []

    # Try TraceQL first (Tempo ≥ 2.x)
    queries = [
        f'{{ resource.service.name = "{service_name}" && status = error }}',
        f'{{ resource.service.name = "{service_name}" }}',
    ]

    for q in queries:
        try:
            resp = await client.get(
                "/api/search",
                params={
                    "q": q,
                    "start": str(start),
                    "end": str(end),
                    "limit": str(limit),
                },
            )
            resp.raise_for_status()
            traces = resp.json().get("traces", [])

            for t in traces:
                try:
                    duration_ms = float(t.get("durationMs", 0))
                    # Root span name may be in spanSets or rootName
                    root_name = t.get("rootName") or t.get("rootSpanName")
                    status = "error" if "error" in q else "ok"

                    signals.append(
                        TraceSignal(
                            service=service_name,
                            duration_ms=duration_ms,
                            status=status,
                            trace_id=t.get("traceID", "unknown"),
                            root_span_name=root_name,
                        )
                    )
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("tempo.parse_error", service=service_name, error=str(exc))

            log.debug(
                "tempo.search_ok",
                service=service_name,
                query=q[:60],
                traces=len(signals),
            )
            # If the first query succeeded, don't fall through to the broader one
            if traces:
                break

        except httpx.TimeoutException:
            log.error("tempo.timeout", service=service_name, query=q[:60])
            break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                # TraceQL not supported — try next query
                log.debug("tempo.traceql_unsupported", service=service_name)
                continue
            log.error("tempo.http_error", status=exc.response.status_code)
            break
        except Exception as exc:  # noqa: BLE001
            log.error("tempo.unexpected_error", service=service_name, error=str(exc))
            break

    return signals


async def collect(settings: Settings) -> list[TraceSignal]:
    """Query Tempo for recent error traces across all dtx-app services."""
    signals: list[TraceSignal] = []

    end_ts = int(time.time())
    start_ts = end_ts - settings.query_lookback_minutes * 60

    async with httpx.AsyncClient(
        base_url=settings.tempo_url,
        timeout=settings.http_timeout,
    ) as client:
        for service in SERVICES:
            result = await _search_service(client, service, start_ts, end_ts)
            signals.extend(result)

    log.info("tempo.collected", total_traces=len(signals))
    return signals
