"""Local demo configuration. Connected mode remains fake until step 1 is approved."""

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    mode: str = field(default_factory=lambda: os.getenv("DONEWISE_MODE", "sandbox"))
    mcp_bearer_token: str = field(default_factory=lambda: os.getenv("MCP_BEARER_TOKEN", ""))
    demo_admin_token: str = field(default_factory=lambda: os.getenv("DEMO_ADMIN_TOKEN", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DONEWISE_DATA_DIR", "./data")))
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            v.strip()
            for v in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:*,http://localhost:*").split(
                ","
            )
            if v.strip()
        ]
    )
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8765")))
    google_service_account_json: str = field(
        default_factory=lambda: os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    )
    google_calendar_id: str = field(default_factory=lambda: os.getenv("GOOGLE_CALENDAR_ID", ""))
    stripe_secret_key: str = field(default_factory=lambda: os.getenv("STRIPE_SECRET_KEY", ""))
    pending_after: float = 0.45
    fake_payment_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("FAKE_PAYMENT_DELAY_SECONDS", "0.65"))
    )

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        if self.mode not in ("sandbox", "connected"):
            raise ValueError("DONEWISE_MODE must be sandbox or connected")
        if self.mode == "connected":
            if not self.stripe_secret_key.startswith("sk_test_"):
                raise ValueError("Connected mode requires a Stripe sk_test_ key")
            if not self.google_service_account_json or not self.google_calendar_id:
                raise ValueError("Connected mode requires Google credentials and calendar ID")

    def consent_token_for(self, run_id: str) -> str | None:
        if not self.demo_admin_token:
            return None
        return hmac.new(self.demo_admin_token.encode(), run_id.encode(), hashlib.sha256).hexdigest()
