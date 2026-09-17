import pytest
from donewise_harness.replay import decide_replay


@pytest.mark.parametrize("result", ["response_lost", "acked", "already_exists"])
@pytest.mark.parametrize("retries,safe", [(0, True), (0, False), (1, True), (1, False)])
def test_replay_table(result, retries, safe):
    expected = (
        "replay"
        if retries == 0 and safe
        else ("unknown" if result == "response_lost" else "not_observed")
    )
    assert decide_replay(result, retries, safe) == expected
