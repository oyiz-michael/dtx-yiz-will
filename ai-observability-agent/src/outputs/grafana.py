"""Grafana annotations output.

Posts a single annotation to Grafana's HTTP API so events from the AI agent
appear as vertical lines on all dashboards. Supports both API-key auth and
basic auth (username/password).
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from ..config import Settings
from ..models.signals import AnalysisResult

log = structlog.get_logger(__name__)

SEVERITY_TAGS = {
    "CRITICAL": ["ai-agent", "critical", "anomaly"],
    "WARNING": ["ai-agent", "warning", "anomaly"],
    "INFO": ["ai-agent", "info"],
}


def _build_annotation(result: AnalysisResult) -> dict:
    """Build the Grafana annotation request body."""
    tags = SEVERITY_TAGS.get(result.severity, ["ai-agent"])

    # Build a text summary for the annotation tooltip
    lines = [f"[{result.severity}] {result.summary}"]
    for a in result.anomalies[:3]:  # keep it short
        lines.append(f"• {a.description}")
    if len(result.anomalies) > 3:
        lines.append(f"… and {len(result.anomalies) - 3} more anomalies")

    return {
        "tags": tags,
        "text": "\n".join(lines),
        "time": int(datetime.now(tz=timezone.utc).timestamp() * 1000),  # ms epoch
    }


def _auth_headers(settings: Settings) -> dict[str, str]:
    """Return the appropriate auth headers for the Grafana API."""
    if settings.grafana_api_key:
        return {"Authorization": f"Bearer {settings.grafana_api_key}"}
    return {}  # httpx will use basic auth via auth= param


def _basic_auth(settings: Settings) -> tuple[str, str] | None:
    if not settings.grafana_api_key and settings.grafana_password:
        return (settings.grafana_user, settings.grafana_password)
    return None


async def post_annotation(result: AnalysisResult, settings: Settings) -> None:
    """Post an annotation to Grafana. Skips silently if Grafana URL is not set."""
    if not settings.grafana_url:
        log.info("grafana.skipped_no_url")
        return

    if settings.dry_run:
        log.info(
            "grafana.dry_run",
            severity=result.severity,
            summary=result.summary[:80],
        )
        return

    annotation = _build_annotation(result)
    url = settings.grafana_url.rstrip("/") + "/api/annotations"
    basic = _basic_auth(settings)

    try:
        async with httpx.AsyncClient(
            headers={**_auth_headers(settings), "Content-Type": "application/json"},
            auth=basic,
            timeout=settings.http_timeout,
        ) as client:
            resp = await client.post(url, json=annotation)
            resp.raise_for_status()
            resp_data = resp.json()
            log.info(
                "grafana.annotation_posted",
                annotation_id=resp_data.get("id"),
                severity=result.severity,
            )
    except httpx.TimeoutException:
        log.error("grafana.timeout")
    except httpx.HTTPStatusError as exc:
        log.error(
            "grafana.http_error",
            status=exc.response.status_code,
            body=exc.response.text[:200],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("grafana.unexpected_error", error=str(exc))
