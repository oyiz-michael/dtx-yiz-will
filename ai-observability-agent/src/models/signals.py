"""Pydantic models for collected observability signals and LLM analysis results."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Collected signal models
# ---------------------------------------------------------------------------


class MetricSignal(BaseModel):
    """A single time-series data point from Prometheus."""

    name: str
    value: float
    labels: dict[str, str] = {}
    timestamp: datetime
    baseline: str | None = None
    unit: str | None = None


class LogSignal(BaseModel):
    """A log entry or log-volume summary from Loki."""

    source: str  # app label value
    message: str  # log content, truncated to 200 chars
    level: str = "unknown"  # ERROR / WARNING / INFO / unknown
    count: int = 1
    timestamp: datetime


class TraceSignal(BaseModel):
    """A trace entry from Tempo."""

    service: str
    duration_ms: float
    status: str  # "ok" or "error"
    trace_id: str
    root_span_name: str | None = None


class CollectedSignals(BaseModel):
    """Container for all signals gathered in one collection run."""

    metrics: list[MetricSignal] = []
    logs: list[LogSignal] = []
    traces: list[TraceSignal] = []
    collected_at: datetime
    lookback_minutes: int

    # Track which collectors failed so the LLM knows about partial data
    collector_errors: dict[str, str] = {}


# ---------------------------------------------------------------------------
# LLM analysis result models
# ---------------------------------------------------------------------------


class Anomaly(BaseModel):
    """A single anomaly detected by the LLM."""

    signal_type: str  # metric | log | trace
    description: str
    evidence: str
    severity: str  # CRITICAL | WARNING | INFO


class Correlation(BaseModel):
    """A cross-signal correlation identified by the LLM."""

    description: str
    signals_involved: list[str]
    root_cause_hypothesis: str


class Recommendation(BaseModel):
    """An actionable recommendation from the LLM."""

    action: str
    priority: str  # immediate | short_term | investigation
    rationale: str


class AnalysisResult(BaseModel):
    """Full structured response from the LLM."""

    summary: str
    severity: str  # CRITICAL | WARNING | INFO
    anomalies: list[Anomaly] = []
    correlations: list[Correlation] = []
    recommendations: list[Recommendation] = []
    healthy_app_status: str = ""
    raw_response: str | None = None  # set if JSON parsing failed

    @classmethod
    def from_llm_text(cls, text: str) -> "AnalysisResult":
        """Parse Claude's response text into a typed AnalysisResult.

        Falls back to a minimal result with the raw text if JSON parsing fails.
        """
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            data: dict[str, Any] = json.loads(cleaned)
            return cls(**data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return cls(
                summary=text[:300],
                severity="INFO",
                raw_response=text,
            )

    @field_validator("severity", mode="before")
    @classmethod
    def normalise_severity(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else "INFO"
