"""Simulator configuration; credentials never enter session responses."""

import os
from dataclasses import dataclass, field

USER_TIMEZONES = ("America/Los_Angeles", "America/Santiago")


@dataclass
class Settings:
    mcp_url: str = field(default_factory=lambda: os.getenv("MCP_URL", "http://127.0.0.1:8765/mcp"))
    mcp_bearer_token: str = field(default_factory=lambda: os.getenv("MCP_BEARER_TOKEN", ""))
    demo_admin_token: str = field(default_factory=lambda: os.getenv("DEMO_ADMIN_TOKEN", ""))
    mode: str = field(default_factory=lambda: os.getenv("DONEWISE_MODE", "sandbox"))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "bedrock"))
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "us-west-2"))
    bedrock_model_id: str = field(default_factory=lambda: os.getenv("BEDROCK_MODEL_ID", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    )
    port: int = field(default_factory=lambda: int(os.getenv("SIM_PORT", "8080")))
    user_timezone: str = field(
        default_factory=lambda: os.getenv("USER_TIMEZONE", USER_TIMEZONES[0]).strip()
    )

    def __post_init__(self):
        if self.user_timezone not in USER_TIMEZONES:
            raise ValueError("USER_TIMEZONE must be one of: " + ", ".join(USER_TIMEZONES))
