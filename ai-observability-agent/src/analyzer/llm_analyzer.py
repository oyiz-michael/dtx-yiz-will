"""LLM-powered anomaly analyzer.

Formats collected signals into a structured prompt, calls Claude via
Amazon Bedrock Runtime (boto3), and parses the JSON response into a
typed AnalysisResult. Authentication is via IRSA — no API key required.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import boto3
import structlog
from botocore.exceptions import ClientError, EndpointResolutionError

from ..config import Settings
from ..models.signals import (
    AnalysisResult,
    Anomaly,
    CollectedSignals,
    MetricSignal,
    LogSignal,
    TraceSignal,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an expert SRE (Site Reliability Engineer) and observability specialist.
You analyse Prometheus metrics, Loki logs, and Tempo traces from a Kubernetes
cluster and produce a concise, structured anomaly report.

Your response MUST be valid JSON matching this schema exactly:
{
  "summary": "<1-3 sentence executive summary of the health status>",
  "severity": "<CRITICAL | WARNING | INFO>",
  "anomalies": [
    {
      "signal_type": "<metric | log | trace>",
      "description": "<what is wrong>",
      "evidence": "<specific numbers/lines that show the problem>",
      "severity": "<CRITICAL | WARNING | INFO>"
    }
  ],
  "correlations": [
    {
      "description": "<how two or more signals relate>",
      "signals_involved": ["<signal name 1>", "<signal name 2>"],
      "root_cause_hypothesis": "<most likely root cause>"
    }
  ],
  "recommendations": [
    {
      "action": "<concrete action to take>",
      "priority": "<immediate | short_term | investigation>",
      "rationale": "<why this helps>"
    }
  ],
  "healthy_app_status": "<brief status of dtx-app (the healthy one)>"
}

Rules:
- severity is CRITICAL if any anomaly is CRITICAL, WARNING if any is WARNING, else INFO
- Be concise: each field ≤ 200 characters
- Only flag things that deviate meaningfully from the provided baselines
- If data is missing or a collector failed, say so in the summary
- Do NOT include markdown fences or any text outside the JSON object
"""

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _fmt_metrics(metrics: list[MetricSignal]) -> str:
    if not metrics:
        return "  (no metrics collected)\n"

    # Group by query name
    groups: dict[str, list[MetricSignal]] = {}
    for m in metrics:
        groups.setdefault(m.name, []).append(m)

    lines: list[str] = []
    for name, signals in groups.items():
        lines.append(f"  [{name}]")
        for s in signals:
            label_str = ", ".join(f"{k}={v}" for k, v in s.labels.items() if k != "__name__")
            value_str = f"{s.value:.3g}"
            baseline_str = f" [baseline: {s.baseline}]" if s.baseline else ""
            lines.append(f"    {label_str or '(no labels)'}: {value_str}{baseline_str}")
    return "\n".join(lines) + "\n"


def _fmt_logs(logs: list[LogSignal]) -> str:
    if not logs:
        return "  (no log entries collected)\n"

    lines: list[str] = []
    for entry in logs:
        count_str = f" (×{entry.count})" if entry.count > 1 else ""
        lines.append(f"  [{entry.level}] {entry.source}: {entry.message}{count_str}")
    return "\n".join(lines) + "\n"


def _fmt_traces(traces: list[TraceSignal]) -> str:
    if not traces:
        return "  (no traces collected)\n"

    lines: list[str] = []
    for t in traces:
        name_str = f" ({t.root_span_name})" if t.root_span_name else ""
        lines.append(
            f"  {t.service}{name_str}: status={t.status}, duration={t.duration_ms:.0f}ms,"
            f" traceID={t.trace_id[:16]}…"
        )
    return "\n".join(lines) + "\n"


def _build_user_message(signals: CollectedSignals) -> str:
    now = datetime.now(tz=timezone.utc).isoformat()
    errors_str = ""
    if signals.collector_errors:
        errors_str = (
            "\n## Collector Errors (data may be partial)\n"
            + "\n".join(
                f"  - {k}: {v}" for k, v in signals.collector_errors.items()
            )
            + "\n"
        )

    return (
        f"## Observability Report — {now}\n"
        f"Lookback window: {signals.lookback_minutes} minutes\n"
        f"{errors_str}"
        "\n## Prometheus Metrics\n"
        f"{_fmt_metrics(signals.metrics)}"
        "\n## Loki Logs\n"
        f"{_fmt_logs(signals.logs)}"
        "\n## Tempo Traces\n"
        f"{_fmt_traces(signals.traces)}"
        "\n## Known Baselines\n"
        "  - dtx-app-broken: ~35% error rate, ~150MB memory (grows), periodic OOMKill,"
        " high latency on /data — these are BY DESIGN for this demo app\n"
        "  - dtx-app (healthy): <1% error rate, ~80MB stable memory\n"
        "\nAnalyse these signals. Only raise anomalies that are WORSE than the known baselines.\n"
        "Return your analysis as JSON now."
    )


# ---------------------------------------------------------------------------
# Analyser
# ---------------------------------------------------------------------------


async def analyse(signals: CollectedSignals, settings: Settings) -> AnalysisResult:
    """Call Claude via Amazon Bedrock with the collected signals and return a typed AnalysisResult."""
    user_message = _build_user_message(signals)
    log.debug("analyzer.prompt_built", message_chars=len(user_message))

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
    )

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": settings.llm_max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }

    try:
        response = await asyncio.to_thread(
            bedrock.invoke_model,
            modelId=settings.bedrock_model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload),
        )
        response_body = json.loads(response["body"].read())
        raw_text = response_body["content"][0]["text"]

        usage = response_body.get("usage", {})
        log.debug(
            "analyzer.llm_response",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

        result = AnalysisResult.from_llm_text(raw_text)
        log.info(
            "analyzer.done",
            severity=result.severity,
            anomalies=len(result.anomalies),
            recommendations=len(result.recommendations),
        )
        return result

    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("ModelTimeoutException", "ThrottlingException"):
            log.error("analyzer.bedrock_throttle_or_timeout", code=error_code)
            return AnalysisResult(
                summary=f"Bedrock call failed ({error_code}). Will retry next run.",
                severity="INFO",
            )
        log.error("analyzer.bedrock_client_error", code=error_code, error=str(exc))
        return AnalysisResult(
            summary=f"Bedrock ClientError ({error_code}): {exc}",
            severity="INFO",
        )
    except EndpointResolutionError as exc:
        log.error("analyzer.bedrock_endpoint_error", error=str(exc))
        return AnalysisResult(
            summary=f"Could not resolve Bedrock endpoint: {exc}",
            severity="INFO",
        )
    except Exception as exc:  # noqa: BLE001
        log.error("analyzer.unexpected_error", error=str(exc))
        return AnalysisResult(
            summary=f"Unexpected error during analysis: {exc}",
            severity="INFO",
        )
