"""Per-run, single-use fault injection (PRD RF-41). Never a global service failure."""

from collections import defaultdict
from contextvars import ContextVar
from threading import RLock

from .contracts import FaultKind, RunId


class FaultBoard:
    """Implements ports.FaultInjector. `uses` lets one fault persist for N consumptions (T22)."""

    def __init__(self) -> None:
        self._armed: dict[tuple[str, str], int] = defaultdict(int)
        self._fired: dict[str, list[FaultKind]] = defaultdict(list)
        self._active_run: ContextVar[RunId | None] = ContextVar("active_run", default=None)
        self.lock = RLock()
        self._history: dict[str, list[FaultKind]] = defaultdict(list)

    @property
    def active_run(self) -> RunId | None:
        return self._active_run.get()

    @active_run.setter
    def active_run(self, value: RunId | None) -> None:
        self._active_run.set(value)

    def arm(self, kind: FaultKind, run_id: RunId, uses: int = 1) -> None:
        if uses < 1:
            raise ValueError("uses must be >= 1")
        with self.lock:
            self._armed[(kind, run_id)] += uses

    def consume(self, kind: FaultKind, run_id: RunId) -> bool:
        with self.lock:
            left = self._armed.get((kind, run_id), 0)
            if left <= 0:
                return False
            self._armed[(kind, run_id)] = left - 1
            self._fired[run_id].append(kind)
            self._history[run_id].append(kind)
            return True

    def consume_active(self, kind: FaultKind) -> bool:
        """For adapters: consume against the run the harness is currently serving."""
        return self.active_run is not None and self.consume(kind, self.active_run)

    def armed(self, run_id: RunId) -> dict[FaultKind, int]:
        with self.lock:
            return {k: n for (k, r), n in self._armed.items() if r == run_id and n > 0}

    def fired(self, run_id: RunId) -> list[FaultKind]:
        with self.lock:
            return list(self._history[run_id])

    def take_fired(self, run_id: RunId) -> list[FaultKind]:
        with self.lock:
            return self._fired.pop(run_id, [])
