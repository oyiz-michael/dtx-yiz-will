"""Central configuration sourced from environment variables.

In Kubernetes, non-sensitive values come from a ConfigMap and secrets
(ANTHROPIC_API_KEY, GRAFANA_PASSWORD, etc.) come from a Kubernetes Secret.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration for the AI observability agent.

    Values can be set via environment variables (upper-case) or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # -------------------------------------------------------------------------
    # Observability backends (in-cluster service URLs)
    # -------------------------------------------------------------------------
    prometheus_url: str = Field(
        default="http://kube-prometheus-kube-prome-prometheus.monitoring.svc:9090",
        alias="PROMETHEUS_URL",
    )
    loki_url: str = Field(
        default="http://loki.monitoring.svc:3100",
        alias="LOKI_URL",
    )
    tempo_url: str = Field(
        default="http://tempo.monitoring.svc:3200",
        alias="TEMPO_URL",
    )
    grafana_url: str = Field(
        default="http://kube-prometheus-grafana.monitoring.svc",
        alias="GRAFANA_URL",
    )

    # -------------------------------------------------------------------------
    # LLM (Anthropic SDK)
    # -------------------------------------------------------------------------
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model_id: str = Field(
        default="claude-haiku-4-5-20251001",
        alias="ANTHROPIC_MODEL_ID",
    )
    llm_max_tokens: int = Field(default=1024, alias="LLM_MAX_TOKENS")
    llm_timeout: int = Field(default=30, alias="LLM_TIMEOUT")

    # -------------------------------------------------------------------------
    # Output targets
    # -------------------------------------------------------------------------
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    grafana_api_key: str = Field(default="", alias="GRAFANA_API_KEY")
    grafana_user: str = Field(default="admin", alias="GRAFANA_USER")
    grafana_password: str = Field(default="", alias="GRAFANA_PASSWORD")

    # -------------------------------------------------------------------------
    # Agent behaviour
    # -------------------------------------------------------------------------
    query_lookback_minutes: int = Field(default=5, alias="QUERY_LOOKBACK_MINUTES")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    dry_run: bool = Field(default=False, alias="DRY_RUN")
    http_timeout: int = Field(default=10, alias="HTTP_TIMEOUT")
