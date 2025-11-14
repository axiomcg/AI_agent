from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Centralized application settings loaded from environment or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # === LLM / OpenRouter ===
    openrouter_api_key: Optional[str] = Field(default=None, alias="OPENROUTER_API_KEY")
    llm_model_id: str = Field(default="google/gemini-2.5-flash-lite", alias="LLM_MODEL_ID")
    llm_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="LLM_BASE_URL")
    llm_http_referer: Optional[str] = Field(default=None, alias="LLM_HTTP_REFERER")
    llm_title: Optional[str] = Field(default="Autonomous Browser Agent", alias="LLM_TITLE")
    llm_request_timeout: int = Field(default=60, alias="LLM_REQUEST_TIMEOUT")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    agent_llm_provider: str = Field(default="openrouter", alias="AGENT_LLM_PROVIDER")
    agent_llm_model: str = Field(default="google/gemini-2.5-flash-lite", alias="AGENT_LLM_MODEL")
    agent_llm_temperature: float = Field(default=0.2, alias="AGENT_LLM_TEMPERATURE")

    # === Agent Behavior ===
    max_agent_steps: int = Field(default=120, alias="MAX_AGENT_STEPS")
    max_consecutive_failures: int = Field(default=5, alias="MAX_CONSECUTIVE_FAILURES")
    context_max_tokens: int = Field(default=6000, alias="CONTEXT_MAX_TOKENS")
    human_approval_required: bool = Field(default=True, alias="HUMAN_APPROVAL_REQUIRED")
    save_run_artifacts: bool = Field(default=True, alias="SAVE_RUN_ARTIFACTS")
    enable_cli: bool = Field(default=True, alias="ENABLE_CLI")
    anonymized_telemetry: bool = Field(default=False, alias="ANONYMIZED_TELEMETRY")
    logging_level: str = Field(default="info", alias="BROWSER_USE_LOGGING_LEVEL")

    # === Browser / Playwright ===
    browser_path: Optional[str] = Field(default=None, alias="BROWSER_PATH")
    browser_user_data: Optional[str] = Field(default=None, alias="BROWSER_USER_DATA")
    browser_debugging_host: str = Field(default="localhost", alias="BROWSER_DEBUGGING_HOST")
    browser_debugging_port: int = Field(default=9222, alias="BROWSER_DEBUGGING_PORT")
    use_own_browser: bool = Field(default=False, alias="USE_OWN_BROWSER")
    keep_browser_open: bool = Field(default=True, alias="KEEP_BROWSER_OPEN")
    persist_browser: bool = Field(default=True, alias="PERSIST_BROWSER")
    playwright_headless: bool = Field(default=False, alias="PLAYWRIGHT_HEADLESS")
    browser_cdp: Optional[str] = Field(default=None, alias="BROWSER_CDP")
    resolution: str = Field(default="1920x1080x24", alias="RESOLUTION")
    resolution_width: int = Field(default=1920, alias="RESOLUTION_WIDTH")
    resolution_height: int = Field(default=1080, alias="RESOLUTION_HEIGHT")

    # === Safety ===
    security_layer_enabled: bool = Field(default=True, alias="SECURITY_LAYER_ENABLED")
    security_confirmation_timeout: int = Field(default=120, alias="SECURITY_CONFIRMATION_TIMEOUT")

    # === Observability ===
    runs_path_raw: str = Field(default="./runs", alias="RUNS_PATH")
    gif_output_path: str = Field(default="agent_history.gif", alias="GIF_OUTPUT_PATH")
    vnc_password: str = Field(default="youvncpassword", alias="VNC_PASSWORD")
    vnc_port: int = Field(default=6080, alias="VNC_PORT")

    # === Misc ===
    mcp_server_config: Optional[str] = Field(default=None, alias="MCP_SERVER_CONFIG")

    @computed_field
    @property
    def runs_path(self) -> Path:
        """Resolved path for storing run artifacts."""
        return Path(self.runs_path_raw).expanduser().resolve()

    def llm_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.openrouter_api_key:
            headers["Authorization"] = f"Bearer {self.openrouter_api_key}"
        if self.llm_http_referer:
            headers["HTTP-Referer"] = self.llm_http_referer
        if self.llm_title:
            headers["X-Title"] = self.llm_title
        return headers

    def llm_payload_defaults(self) -> Dict[str, str | int]:
        return {
            "model": self.llm_model_id,
            "max_output_tokens": self.context_max_tokens,
        }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings instance."""
    return AppSettings()
