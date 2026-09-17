"""Adapter boundary; implementations and replay decisions belong to later steps."""

from typing import Literal, Protocol, Self

from pydantic import model_validator

from .contracts import Action, Contract, EvidenceSource, FaultKind, RunId, Target, Text, UtcDatetime


class WriteRequest(Contract):
    action: Action
    target: Target
    provider_key: Text
    precondition_version: str | None
    first_sent_at: UtcDatetime | None


class WriteResult(Contract):
    status: Literal["acked", "response_lost", "precondition_failed", "already_exists", "error"]
    provider_ref: str | None
    version: str | None
    error: str | None


class ReadRequest(Contract):
    action: Action
    provider_ref: Text | None = None
    target: Target | None = None

    @model_validator(mode="after")
    def identified(self) -> Self:
        if self.provider_ref is None and self.target is None:
            raise ValueError("A provider reference or target is required")
        return self


class ReadResult(Contract):
    found: bool
    observed: Target | None
    version: str | None
    observed_at: UtcDatetime
    source: EvidenceSource

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.found != (self.observed is not None):
            raise ValueError("found must agree with observed")
        return self


class Adapter(Protocol):
    @property
    def source(self) -> EvidenceSource: ...

    def write(self, req: WriteRequest) -> WriteResult: ...

    def read(self, req: ReadRequest) -> ReadResult: ...

    def replay_is_safe(self, req: WriteRequest) -> bool: ...


class FaultInjector(Protocol):
    def arm(self, kind: FaultKind, run_id: RunId) -> None: ...

    def consume(self, kind: FaultKind, run_id: RunId) -> bool:
        """Consume an armed fault once, within this run only."""
        ...
