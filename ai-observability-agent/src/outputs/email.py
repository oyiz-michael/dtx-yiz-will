"""Email output — sends issues and recommendations via AWS SES."""

from __future__ import annotations

import asyncio

import boto3
import structlog
from botocore.config import Config
from email_validator import EmailNotValidError, validate_email

from ..config import Settings
from ..models.signals import AnalysisResult

log = structlog.get_logger(__name__)

_BOTO_CONFIG = Config(
    connect_timeout=5,
    read_timeout=15,
    retries={"max_attempts": 1},
)


def _format_email(result: AnalysisResult) -> tuple[str, str]:
    subject = f"AI Observability: {result.severity} - Investigation & Recommendations"
    body = [
        f"Summary: {result.summary}",
        "",
        "ANOMALIES:",
    ]
    for a in result.anomalies:
        body.append(f"- [{a.severity}] {a.description}\n  Evidence: {a.evidence}")
    body.append("")
    body.append("RECOMMENDATIONS:")
    for r in result.recommendations:
        body.append(f"- [{r.priority}] {r.action}\n  Rationale: {r.rationale}")
    return subject, "\n".join(body)


def _send_sync(sender: str, recipient: str, subject: str, body: str) -> str:
    """Synchronous SES call — run via asyncio.to_thread."""
    client = boto3.client("ses", region_name="us-east-1", config=_BOTO_CONFIG)
    resp = client.send_email(
        Source=sender,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )
    return resp.get("MessageId", "")


async def send(result: AnalysisResult, settings: Settings) -> None:
    sender = settings.email_sender
    recipient = settings.email_recipient

    log.info("email.attempt", sender=sender, recipient=recipient, severity=result.severity)

    try:
        validate_email(sender)
        validate_email(recipient)
    except EmailNotValidError as exc:
        log.error("email.invalid_address", error=str(exc))
        return

    subject, body = _format_email(result)

    try:
        message_id = await asyncio.to_thread(_send_sync, sender, recipient, subject, body)
        log.info("email.sent", message_id=message_id)
    except Exception as exc:  # noqa: BLE001
        log.error("email.error", error=str(exc))
