"""Local demo configuration; connected mode permits Stripe test keys only."""

import hashlib
import hmac
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from donewise_adapters.stripe_test import STRIPE_TEST_KEY_PREFIXES

USER_TIMEZONES = ("America/Los_Angeles", "America/Santiago")


def user_timezone_from_env() -> str:
    return os.getenv("USER_TIMEZONE", USER_TIMEZONES[0]).strip()


def pending_after_from_env() -> float | None:
    value = os.getenv("DONEWISE_PENDING_AFTER", "0.45").strip().lower()
    return None if value == "off" else float(value)


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
    pending_after: float | None = field(default_factory=pending_after_from_env)
    user_timezone: str = field(default_factory=user_timezone_from_env)
    fake_payment_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("FAKE_PAYMENT_DELAY_SECONDS", "0.65"))
    )

    def __post_init__(self):
        self.data_dir = Path(self.data_dir)
        if self.pending_after is not None and (
            not math.isfinite(self.pending_after) or self.pending_after < 0
        ):
            raise ValueError("DONEWISE_PENDING_AFTER must be nonnegative seconds or off")
        if self.mode not in ("sandbox", "connected"):
            raise ValueError("DONEWISE_MODE must be sandbox or connected")
        if self.user_timezone not in USER_TIMEZONES:
            raise ValueError("USER_TIMEZONE must be one of: " + ", ".join(USER_TIMEZONES))
        if self.stripe_secret_key and not self.stripe_secret_key.startswith(
            STRIPE_TEST_KEY_PREFIXES
        ):
            raise ValueError(
                "Stripe requires a sk_test_ or rkcs_test_ key; real money is forbidden"
            )
        if self.mode == "connected":
            if not self.stripe_secret_key.startswith(STRIPE_TEST_KEY_PREFIXES):
                raise ValueError("Connected mode requires a Stripe sk_test_ or rkcs_test_ key")
            if not self.google_service_account_json or not self.google_calendar_id:
                raise ValueError("Connected mode requires Google credentials and calendar ID")

    def consent_token_for(self, run_id: str) -> str | None:
        if not self.demo_admin_token:
            return None
        return hmac.new(self.demo_admin_token.encode(), run_id.encode(), hashlib.sha256).hexdigest()
