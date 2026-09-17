"""Provider-independent replay policy; safety windows belong to adapters."""

from typing import Literal


def decide_replay(
    result: str, retries: int, replay_safe: bool
) -> Literal["replay", "unknown", "not_observed"]:
    if retries == 0 and replay_safe:
        return "replay"
    return "unknown" if result == "response_lost" else "not_observed"
