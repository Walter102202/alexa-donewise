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

    @property
    def model_label(self):
        if self.llm_provider == "none":
            return "Model: off · scripted inputs"
        model = self.bedrock_model_id if self.llm_provider == "bedrock" else self.anthropic_model
        name = {
            "claude-sonnet-4-6": "Claude Sonnet 4.6",
            "us.anthropic.claude-sonnet-4-6": "Claude Sonnet 4.6",
            "us.amazon.nova-pro-v1:0": "Amazon Nova Pro",
            "us.openai.gpt-5.6-terra": "GPT-5.6 Terra",
            "openai.gpt-oss-120b-1:0": "gpt-oss-120b",
        }.get(model, model or "not configured")
        provider = "Amazon Bedrock" if self.llm_provider == "bedrock" else "Anthropic API"
        return f"Model: {name} · {provider}"
