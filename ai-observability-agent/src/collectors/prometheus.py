"""Prometheus metrics collector.

Queries the Prometheus HTTP API for key signals about the dtx-app workloads.
All queries are run with asyncio + httpx. If Prometheus is unreachable the
collector logs the error and returns whatever partial results it has so the
agent can still run an analysis.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
import structlog

from ..config import Settings
from ..models.signals import MetricSignal

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# PromQL queries
# ---------------------------------------------------------------------------
QUERIES: dict[str, str] = {
    "error_rate": (
        'sum(rate(flask_http_request_total{status="500"}[5m])) by (app)'
        " / sum(rate(flask_http_request_total[5m])) by (app) * 100"
    ),
    "memory_usage": 'container_memory_usage_bytes{container!="", pod=~"dtx-app.*"}',
    "memory_trend": 'deriv(container_memory_usage_bytes{container!="", pod=~"dtx-app.*"}[15m])',
    "pod_restarts": (
        'sum(increase(kube_pod_container_status_restarts_total{pod=~"dtx-app.*"}[15m]))'
        " by (pod)"
    ),
    "p95_latency": (
        "histogram_quantile(0.95,"
        " sum(rate(flask_http_request_duration_seconds_bucket[5m])) by (le, app))"
    ),
    "pod_waiting": 'kube_pod_container_status_waiting_reason{pod=~"dtx-app.*"}',
}

# Human-readable baselines sent to the LLM for context
BASELINES: dict[str, dict[str, str]] = {
    "error_rate": {
        "dtx-app-broken": "~35% baseline error rate by design",
        "dtx-app": "<1% baseline error rate",
    },
    "memory_usage": {
        "dtx-app-broken": "~150MB baseline — grows monotonically due to memory leak",
        "dtx-app": "~80MB stable",
    },
}


def _baseline(query_name: str, labels: dict[str, str]) -> str | None:
    """Return a baseline hint for the given query + labels if one is defined."""
    per_app = BASELINES.get(query_name)
    if not per_app:
        return None
    app = labels.get("app") or labels.get("pod", "")
    for key, hint in per_app.items():
        if key in app:
            return hint
    return None


def _parse_instant_result(
    query_name: str,
    result: list[dict],
) -> list[MetricSignal]:
    """Convert a Prometheus instant-query result vector into MetricSignals."""
    signals: list[MetricSignal] = []
    for item in result:
        try:
            ts, val = item["value"]
            signals.append(
                MetricSignal(
                    name=query_name,
                    value=float(val),
                    labels=item.get("metric", {}),
                    timestamp=datetime.fromtimestamp(float(ts), tz=timezone.utc),
                    baseline=_baseline(query_name, item.get("metric", {})),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("prometheus.parse_error", query=query_name, error=str(exc))
    return signals


async def collect(settings: Settings) -> list[MetricSignal]:
    """Query Prometheus and return a flat list of MetricSignals.

    Individual query failures are logged and skipped; a total connection failure
    returns an empty list.
    """
    signals: list[MetricSignal] = []

    async with httpx.AsyncClient(
        base_url=settings.prometheus_url,
        timeout=settings.http_timeout,
    ) as client:
        for query_name, promql in QUERIES.items():
            try:
                resp = await client.get(
                    "/api/v1/query",
                    params={"query": promql, "time": str(time.time())},
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") != "success":
                    log.warning(
                        "prometheus.query_failed",
                        query=query_name,
                        response=data.get("error", "unknown"),
                    )
                    continue

                result = data["data"].get("result", [])
                parsed = _parse_instant_result(query_name, result)
                signals.extend(parsed)
                log.debug(
                    "prometheus.query_ok",
                    query=query_name,
                    series=len(parsed),
                )

            except httpx.TimeoutException:
                log.error("prometheus.timeout", query=query_name)
            except httpx.HTTPStatusError as exc:
                log.error(
                    "prometheus.http_error",
                    query=query_name,
                    status=exc.response.status_code,
                )
            except Exception as exc:  # noqa: BLE001
                log.error("prometheus.unexpected_error", query=query_name, error=str(exc))

    log.info("prometheus.collected", total_signals=len(signals))
    return signals
