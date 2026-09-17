"""Google Calendar REST adapter using google-auth only for service-account authentication."""

import base64
import json
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import httpx
from donewise_harness.contracts import Action, CalendarTarget, EvidenceSource
from donewise_harness.errors import ReadUnavailable
from google.auth.transport import Response
from google.oauth2 import service_account

from .provider_http import ProviderHTTP


def google_event_id(provider_key: str) -> str:
    """Reversible, unpadded lowercase base32hex of the UTF-8 internal evt_ ID."""
    encoded = base64.b32hexencode(provider_key.encode()).decode().rstrip("=").lower()
    if not 5 <= len(encoded) <= 1024:
        raise ValueError("Event identity exceeds Google limits")
    return encoded


def internal_event_id(provider_id: str) -> str:
    return base64.b32hexdecode(provider_id.upper() + "=" * (-len(provider_id) % 8)).decode()


class AuthResponse(Response):
    def __init__(self, response):
        self.response = response

    @property
    def status(self):
        return self.response.status_code

    @property
    def data(self):
        return self.response.content

    @property
    def headers(self):
        return self.response.headers


class GoogleCalendar(ProviderHTTP):
    source = EvidenceSource.GOOGLE_CALENDAR

    def __init__(
        self,
        service_account_json,
        calendar_id,
        *,
        credentials=None,
        base_url="https://www.googleapis.com/calendar/v3",
        **kwargs,
    ):
        if credentials is None:
            raw = service_account_json.strip()
            info = json.loads(raw if raw.startswith("{") else Path(raw).read_text())
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/calendar.events"]
            )
        super().__init__(base_url, **kwargs)
        self.credentials = credentials
        self._auth_lock = Lock()
        self.calendar_id = calendar_id
        self.events_path = f"/calendars/{quote(calendar_id, safe='')}/events"

    def headers(self):
        def auth_request(url, method="GET", body=None, headers=None, timeout=10, **kwargs):
            # Token exchange is direct, never sent through the fault proxy.
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                return AuthResponse(client.request(method, url, content=body, headers=headers))

        headers = {}
        with self._auth_lock:
            self.credentials.before_request(auth_request, "GET", self.base_url, headers)
        return headers

    def write(self, req):
        try:
            target = req.target
            if not isinstance(target, CalendarTarget) or target.calendar_id != self.calendar_id:
                raise ValueError("Wrong calendar target")
            event_id = google_event_id(req.provider_key)
            body = {
                "start": {"dateTime": target.start.isoformat(), "timeZone": target.timezone},
                "end": {"dateTime": target.end.isoformat(), "timeZone": target.timezone},
            }
            if req.action == Action.CALENDAR_CREATE:
                body |= {
                    "id": event_id,
                    "summary": target.title,
                    "extendedProperties": {
                        "private": {"intent_id": req.provider_key, "run_id": self.run_id or ""}
                    },
                }
                response = self.request("POST", self.events_path, json=body)
                if response.status_code == 409:
                    return self.result("already_exists", req.provider_key)
            elif req.action == Action.CALENDAR_RESCHEDULE and req.precondition_version:
                response = self.request(
                    "PATCH",
                    self.events_path + "/" + event_id,
                    json=body,
                    headers={"If-Match": req.precondition_version},
                )
                if response.status_code == 412:
                    current = self.read_json(self.events_path + "/" + event_id, missing_ok=True)
                    return self.result(
                        "precondition_failed",
                        req.provider_key,
                        current.get("etag") if current else None,
                    )
            else:
                raise ValueError("Unsupported action or missing precondition")
            response.raise_for_status()
            row = response.json()
            if row["id"] != event_id:
                raise ValueError("Unexpected provider identity")
            return self.result("acked", req.provider_key, row["etag"])
        except Exception as exc:
            return self.write_exception(exc)

    def _target(self, row):
        return CalendarTarget(
            calendar_id=self.calendar_id,
            event_id=internal_event_id(row["id"]),
            title=row["summary"],
            start=datetime.fromisoformat(row["start"]["dateTime"]),
            end=datetime.fromisoformat(row["end"]["dateTime"]),
            timezone=row["start"]["timeZone"],
            status=row["status"],
        )

    def read(self, req):
        try:
            key = req.provider_ref or req.target.event_id
            row = self.read_json(self.events_path + "/" + google_event_id(key), missing_ok=True)
            return self.observation(
                self._target(row) if row else None, row["etag"] if row else None
            )
        except ReadUnavailable:
            raise
        except Exception:
            raise ReadUnavailable("Calendar response cannot represent a complete target") from None

    def replay_is_safe(self, req):
        return req.action == Action.CALENDAR_CREATE or (
            req.action == Action.CALENDAR_RESCHEDULE and bool(req.precondition_version)
        )

    def search(self, query):
        stems = {w[:4] for w in query.lower().split() if len(w) >= 4 and w not in ("the", "with")}
        params = {"showDeleted": "false"}
        if self.run_id:
            params["privateExtendedProperty"] = f"run_id={self.run_id}"
        hits = {}
        # Google's q does not guarantee stemming. A scoped second pass preserves Fake semantics.
        for search_params in (params | {"q": query}, params.copy()):
            while True:
                page = self.read_json(self.events_path, params=search_params)
                for row in page.get("items", []):
                    private = row.get("extendedProperties", {}).get("private", {})
                    if row.get("status") == "cancelled" or (
                        self.run_id and private.get("run_id") != self.run_id
                    ):
                        continue
                    title_stems = {
                        w[:4] for w in row.get("summary", "").lower().split() if len(w) >= 4
                    }
                    if stems & title_stems:
                        try:
                            target = self._target(row)
                        except (ValueError, KeyError):
                            continue  # External/all-day events are outside the frozen contract.
                        hits[target.event_id] = target
                if not page.get("nextPageToken"):
                    break
                search_params["pageToken"] = page["nextPageToken"]
        return list(hits.values())
