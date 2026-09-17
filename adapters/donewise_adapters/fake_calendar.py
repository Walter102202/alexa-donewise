"""FakeCalendar: JSON-file calendar with its own ETags and the four fault hooks (PRD 6.5).

The file is the independent oracle: tests read it directly, and every read reloads it from disk.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from donewise_harness.clock import Clock, SystemClock
from donewise_harness.contracts import Action, CalendarTarget, EvidenceSource, FaultKind
from donewise_harness.errors import ReadUnavailable
from donewise_harness.faults import FaultBoard
from donewise_harness.ports import ReadRequest, ReadResult, WriteRequest, WriteResult

from .state_lock import locked


class FakeCalendar:
    source = EvidenceSource.FAKE_CALENDAR

    def __init__(
        self, path: Path | str, faults: FaultBoard | None = None, clock: Clock | None = None
    ):
        self._lock = RLock()
        self.path = Path(path)
        self.faults = faults
        self.clock = clock or SystemClock()
        self.write_calls = 0
        self.read_calls = 0
        self._corrupt_minutes: int | None = None
        if not self.path.exists():
            self._save({"events": {}})

    # -- state file -----------------------------------------------------------------------

    @locked
    def _load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    @locked
    def _save(self, state: dict) -> None:
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    @locked
    def events(self) -> dict[str, dict]:
        return self._load()["events"]

    def corrupt_next_write(self, minutes: int) -> None:
        """Test hook (T10): the provider acknowledges but stores a shifted time."""
        self._corrupt_minutes = minutes

    def _fault(self, kind: FaultKind) -> bool:
        return self.faults is not None and self.faults.consume_active(kind)

    @staticmethod
    def _to_target(event_id: str, row: dict) -> CalendarTarget:
        return CalendarTarget(
            calendar_id=row["calendar_id"],
            event_id=event_id,
            title=row["title"],
            start=datetime.fromisoformat(row["start"]),
            end=datetime.fromisoformat(row["end"]),
            timezone=row["timezone"],
            status=row["status"],
        )

    def _shifted(self, target: CalendarTarget) -> tuple[datetime, datetime]:
        if self._corrupt_minutes is None:
            return target.start, target.end
        delta = timedelta(minutes=self._corrupt_minutes)
        self._corrupt_minutes = None
        return target.start + delta, target.end + delta

    # -- ports.Adapter --------------------------------------------------------------------

    @locked
    def write(self, req: WriteRequest) -> WriteResult:
        self.write_calls += 1
        target = req.target
        if not isinstance(target, CalendarTarget):
            return WriteResult(
                status="error", provider_ref=None, version=None, error="not a calendar target"
            )
        state = self._load()
        events = state["events"]
        event_id = req.provider_key

        if req.action == Action.CALENDAR_CREATE:
            if event_id in events:
                return WriteResult(
                    status="already_exists",
                    provider_ref=event_id,
                    version=str(events[event_id]["version"]),
                    error=None,
                )
            if self._fault(FaultKind.ACK_WITHOUT_WRITE):
                return WriteResult(status="acked", provider_ref=event_id, version="1", error=None)
            start, end = self._shifted(target)
            events[event_id] = {
                "run_id": self.faults.active_run if self.faults else None,
                "calendar_id": target.calendar_id,
                "title": target.title,
                "start": start.astimezone(UTC).isoformat(),
                "end": end.astimezone(UTC).isoformat(),
                "timezone": target.timezone,
                "status": "confirmed",
                "version": 1,
            }
            self._save(state)
            if self._fault(FaultKind.DROP_RESPONSE_AFTER_WRITE):
                return WriteResult(
                    status="response_lost", provider_ref=None, version=None, error=None
                )
            return WriteResult(status="acked", provider_ref=event_id, version="1", error=None)

        if req.action == Action.CALENDAR_RESCHEDULE:
            row = events.get(event_id)
            if row is None:
                return WriteResult(
                    status="error", provider_ref=None, version=None, error="event not found"
                )
            if self._fault(FaultKind.CONCURRENT_EDIT):
                # Someone else edited the event between our read and our write.
                other_start = datetime.fromisoformat(row["start"]) + timedelta(minutes=30)
                other_end = datetime.fromisoformat(row["end"]) + timedelta(minutes=30)
                row["start"], row["end"] = other_start.isoformat(), other_end.isoformat()
                row["version"] += 1
                self._save(state)
            if req.precondition_version is not None and req.precondition_version != str(
                row["version"]
            ):
                return WriteResult(
                    status="precondition_failed",
                    provider_ref=event_id,
                    version=str(row["version"]),
                    error="If-Match failed",
                )
            if self._fault(FaultKind.ACK_WITHOUT_WRITE):
                return WriteResult(
                    status="acked",
                    provider_ref=event_id,
                    version=str(row["version"] + 1),
                    error=None,
                )
            start, end = self._shifted(target)
            row["start"], row["end"] = (
                start.astimezone(UTC).isoformat(),
                end.astimezone(UTC).isoformat(),
            )
            row["timezone"] = target.timezone
            row["version"] += 1
            self._save(state)
            if self._fault(FaultKind.DROP_RESPONSE_AFTER_WRITE):
                return WriteResult(
                    status="response_lost", provider_ref=None, version=None, error=None
                )
            return WriteResult(
                status="acked", provider_ref=event_id, version=str(row["version"]), error=None
            )

        return WriteResult(
            status="error", provider_ref=None, version=None, error="unsupported action"
        )

    @locked
    def read(self, req: ReadRequest) -> ReadResult:
        self.read_calls += 1
        if self._fault(FaultKind.READ_UNAVAILABLE):
            raise ReadUnavailable("calendar read unavailable")
        event_id = req.provider_ref or (
            req.target.event_id if isinstance(req.target, CalendarTarget) else None
        )
        row = self.events().get(event_id) if event_id else None
        now = self.clock.now()
        if row is None:
            return ReadResult(
                found=False, observed=None, version=None, observed_at=now, source=self.source
            )
        return ReadResult(
            found=True,
            observed=self._to_target(event_id, row),
            version=str(row["version"]),
            observed_at=now,
            source=self.source,
        )

    def replay_is_safe(self, req: WriteRequest) -> bool:
        # Own event id on insert (409 = evidence of a previous write) and If-Match on patch:
        # a replay can never create a second event or overwrite a newer version.
        return req.action in (Action.CALENDAR_CREATE, Action.CALENDAR_RESCHEDULE)

    # -- helpers used by the harness beyond ports (event_query resolution) -----------------

    @locked
    def search(self, query: str) -> list[CalendarTarget]:
        """Events whose title shares a word stem with the query ("plumber" ~ "Plumbing")."""
        stems = {w[:4] for w in query.lower().split() if len(w) >= 4 and w not in ("the", "with")}
        hits = []
        for event_id, row in self.events().items():
            if (
                self.faults
                and self.faults.active_run
                and row.get("run_id") not in (None, self.faults.active_run)
            ):
                continue
            if row["status"] == "cancelled":
                continue
            title_stems = {w[:4] for w in row["title"].lower().split() if len(w) >= 4}
            if stems & title_stems:
                hits.append(self._to_target(event_id, row))
        return hits

    @locked
    def reset_run(self, run_id: str):
        state = self._load()
        state["events"] = {k: v for k, v in state["events"].items() if v.get("run_id") != run_id}
        self._save(state)
