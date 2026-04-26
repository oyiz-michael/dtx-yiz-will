"""SNS output — sends an SMS message to a phone number using AWS SNS."""

import boto3
import structlog
from ..config import Settings
from ..models.signals import AnalysisResult

log = structlog.get_logger(__name__)

def _format_sms(result: AnalysisResult) -> str:
    # Concise, single-message summary for SMS
    lines = [
        f"AI Observability: {result.severity}",
        f"Summary: {result.summary}",
    ]
    if result.recommendations:
        rec = result.recommendations[0]
        lines.append(f"Rec: {rec.action}")
    return " | ".join(lines)[:300]  # SMS length limit

def send(result: AnalysisResult, settings: Settings) -> None:
    if not settings.sns_phone_number:
        log.info("sns.skipped_no_number")
        return
    msg = _format_sms(result)
    try:
        client = boto3.client("sns")
        resp = client.publish(PhoneNumber=settings.sns_phone_number, Message=msg)
        log.info("sns.sent", message_id=resp.get("MessageId"))
    except Exception as exc:
        log.error("sns.error", error=str(exc))