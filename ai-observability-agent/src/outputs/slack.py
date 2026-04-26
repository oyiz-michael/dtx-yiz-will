"""Slack output — posts a Block Kit message to a webhook URL.

If SLACK_WEBHOOK_URL is not set the message is printed to stdout instead,
which is useful for local development and dry-run mode.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from ..config import Settings
from ..models.signals import AnalysisResult

log = structlog.get_logger(__name__)

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "WARNING": "🟡",
    "INFO": "🟢",
}

PRIORITY_EMOJI = {
    "immediate": "🚨",
    "short_term": "⚠️",
    "investigation": "🔍",
}


def _severity_emoji(severity: str) -> str:
    return SEVERITY_EMOJI.get(severity.upper(), "⚪")


def _build_blocks(result: AnalysisResult, grafana_url: str) -> list[dict]:
    """Construct a Slack Block Kit payload from an AnalysisResult."""
    emoji = _severity_emoji(result.severity)
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {result.severity} — AI Observability Report",
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {result.summary}"},
        },
        {"type": "divider"},
    ]

    # Anomalies
    if result.anomalies:
        anomaly_lines = "\n".join(
            f"• {_severity_emoji(a.severity)} *[{a.severity}]* {a.description}\n"
            f"  _{a.evidence}_"
            for a in result.anomalies
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🔎 Anomalies:*\n{anomaly_lines}"},
            }
        )
        blocks.append({"type": "divider"})

    # Correlations
    if result.correlations:
        corr_lines = "\n".join(
            f"• {c.description}\n  _Hypothesis: {c.root_cause_hypothesis}_"
            for c in result.correlations
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*🔗 Correlations:*\n{corr_lines}"},
            }
        )
        blocks.append({"type": "divider"})

    # Recommendations
    if result.recommendations:
        rec_lines = "\n".join(
            f"{i+1}. {PRIORITY_EMOJI.get(r.priority, '•')} *[{r.priority}]* {r.action}"
            for i, r in enumerate(result.recommendations)
        )
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*✅ Recommendations:*\n{rec_lines}",
                },
            }
        )
        blocks.append({"type": "divider"})

    # Healthy app status
    if result.healthy_app_status:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*dtx-app (healthy):* {result.healthy_app_status}",
                },
            }
        )

    # Footer
    footer_parts = [f"🕐 {ts}", "AI Observability Agent"]
    if grafana_url:
        # Strip trailing slash for the link
        gurl = grafana_url.rstrip("/")
        footer_parts.insert(0, f"<{gurl}|📊 Grafana>")

    blocks.append(
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": " | ".join(footer_parts)}
            ],
        }
    )

    return blocks


def _format_terminal(result: AnalysisResult) -> str:
    """Return a nicely formatted terminal string for dry-run / no-webhook mode."""
    emoji = _severity_emoji(result.severity)
    lines = [
        "",
        f"{'='*70}",
        f" {emoji}  AI OBSERVABILITY REPORT  —  {result.severity}",
        f"{'='*70}",
        f"  Summary: {result.summary}",
        "",
    ]

    if result.anomalies:
        lines.append("  ANOMALIES:")
        for a in result.anomalies:
            lines.append(f"    {_severity_emoji(a.severity)} [{a.severity}] {a.description}")
            lines.append(f"       Evidence: {a.evidence}")
        lines.append("")

    if result.correlations:
        lines.append("  CORRELATIONS:")
        for c in result.correlations:
            lines.append(f"    • {c.description}")
            lines.append(f"      Root cause: {c.root_cause_hypothesis}")
        lines.append("")

    if result.recommendations:
        lines.append("  RECOMMENDATIONS:")
        for i, r in enumerate(result.recommendations, 1):
            p_emoji = PRIORITY_EMOJI.get(r.priority, "•")
            lines.append(f"    {i}. {p_emoji} [{r.priority.upper()}] {r.action}")
        lines.append("")

    if result.healthy_app_status:
        lines.append(f"  dtx-app (healthy): {result.healthy_app_status}")
        lines.append("")

    lines.append(f"{'='*70}")
    return "\n".join(lines)


async def send(result: AnalysisResult, settings: Settings) -> None:
    """Send the analysis result to Slack, or print to stdout if dry_run or no webhook."""
    if settings.dry_run or not settings.slack_webhook_url:
        print(_format_terminal(result))  # noqa: T201
        if not settings.slack_webhook_url:
            log.info("slack.skipped_no_webhook")
        return

    blocks = _build_blocks(result, settings.grafana_url)
    payload = {"blocks": blocks}

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            resp = await client.post(settings.slack_webhook_url, json=payload)
            resp.raise_for_status()
            log.info("slack.sent", severity=result.severity)
    except httpx.TimeoutException:
        log.error("slack.timeout")
    except httpx.HTTPStatusError as exc:
        log.error("slack.http_error", status=exc.response.status_code, body=exc.response.text[:200])
    except Exception as exc:  # noqa: BLE001
        log.error("slack.unexpected_error", error=str(exc))
