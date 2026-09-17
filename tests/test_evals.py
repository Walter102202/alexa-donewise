"""Approved matrix over real MCP; assertions never supply report values."""

import json

import pytest
from donewise_evals.llm_runner import run_llm
from donewise_evals.report import summarize
from donewise_evals.runner import main, run_suite
from donewise_evals.scenarios import SCENARIOS
from donewise_evals.world import World, matches
from donewise_sim.config import Settings
from donewise_sim.llm import Reply, ToolCall


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_approved_matrix_over_mcp_and_independent_oracle(tmp_path):
    rows = await run_suite(tmp_path)
    assert len(rows) == 20
    row = {(r["scenario"], r["variant"]): r for r in rows}
    summary = summarize(rows)
    assert summary["donewise"]["false_claims"] == 0
    assert summary["donewise"]["extra_charges"] == summary["donewise"]["extra_events"] == 0
    assert summary["donewise"]["unauthorized_writes"] == 0
    assert summary["donewise"]["completed_mutations"] == 6  # S03 remains unconfirmed.
    assert summary["donewise"]["verified_mutations"] == 6
    assert summary["baseline"]["p50_ms"] is None
    assert summary["baseline"]["payment_intents"] == 4
    assert summary["baseline"]["creation_intents"] == 3
    for sid in ("S02", "S03", "S08"):
        assert row[sid, "baseline"]["metrics"]["false_claims"] > 0
    assert row["S01", "baseline"]["metrics"]["success_claims"] == 1
    assert len(row["S01", "baseline"]["final"]["payments"]["intents"]) == 2
    assert len(row["S01", "donewise"]["final"]["payments"]["intents"]) == 1
    for variant in ("baseline", "donewise"):
        s01 = row["S01", variant]
        calls = [t for t in s01["trace"] if not t["setup"]]
        assert s01["metrics"]["turns"] == 2
        assert len(calls) == 2 and calls[0]["arguments"] == calls[1]["arguments"]
    for sid in ("S01", "S07"):
        payment = row[sid, "donewise"]
        calls = [t for t in payment["trace"] if not t["setup"]]
        assert calls[0]["result"]["receipt_id"] == calls[1]["result"]["receipt_id"]
        assert {c["kind"] for c in payment["claims"]} == {"effect", "charged_once"}
        assert len(payment["claims"]) == 2
        assert {c["trace_index"] for c in payment["claims"]} == {payment["trace"].index(calls[0])}
    assert row["S03", "baseline"]["faults_remaining"] == {"ack_without_write": 1}
    assert not row["S03", "donewise"]["metrics"]["completed"]
    assert all(row["S04", v]["metrics"]["completed"] for v in ("baseline", "donewise"))
    assert row["S05", "baseline"]["faults_remaining"] == {"read_unavailable": 3}
    assert row["S06", "donewise"]["metrics"]["write_attempts"] == 0
    assert row["S06", "baseline"]["protection_absent"]
    assert row["S07", "baseline"]["metrics"]["extra_charges"] == 1
    assert row["S07", "donewise"]["metrics"]["write_attempts"] == 1
    assert row["S08", "donewise"]["metrics"]["completed"]
    assert not row["S08", "baseline"]["metrics"]["completed"]
    assert row["S09", "baseline"]["metrics"]["unauthorized_writes"] == 1
    assert row["S09", "donewise"]["outcomes"][-1] == "REJECTED"
    assert row["S10", "donewise"]["outcomes"] == ["UNKNOWN", "VERIFIED"]
    assert row["S10", "donewise"]["metrics"]["write_attempts"] == 1
    evidence = row["S01", "donewise"]
    claim = evidence["claims"][0]
    trace = evidence["trace"][claim["trace_index"]]
    # A receipt alone is insufficient: tampering with the independent effect fails the oracle.
    altered = json.loads(json.dumps(trace["oracle"]))
    next(iter(altered["payments"]["intents"].values()))["amount_minor"] = 9000
    assert not matches(altered, trace["result"]["expected"])
    assert "consent_token" not in json.dumps(rows)


@pytest.mark.anyio
@pytest.mark.parametrize("variant", ["baseline", "donewise"])
async def test_llm_tools_and_claim_review_boundary_with_provider_double(tmp_path, variant):
    scenario = SCENARIOS[1]

    class ProviderDouble:
        calls = 0

        async def reply(self, messages, tools):
            self.calls += 1
            names = {t["name"] for t in tools}
            if self.calls == 1:
                name = "calendar_create_verified" if variant == "donewise" else "calendar_create"
                assert name in names and "approval_grant" not in names
                return Reply(tool_calls=[ToolCall("create", name, scenario.inputs)])
            if self.calls == 2 and variant == "baseline":
                assert "calendar_read" in names and "payment_read" in names
                payload = json.loads(messages[-1]["content"][0]["content"])
                assert "spoken" not in payload
                return Reply(
                    tool_calls=[
                        ToolCall(
                            "read",
                            "calendar_read",
                            {
                                "provider_ref": payload["provider_ref"],
                            },
                        )
                    ]
                )
            return Reply("Done, everything is booked.")

    world = World(tmp_path / variant, scenario, variant)
    async with world.connect():
        await run_llm(world, Settings(llm_provider="none"), ProviderDouble())
        result = world.result("llm")
    if variant == "baseline":
        assert world.llm_record["utterances"][0]["claims"] is None
        assert not result["claims_reviewed"] and result["claims"] == []
        assert result["metrics"]["verification_ms"] is None
        assert any(t["tool"] == "calendar_read" for t in result["trace"])
        assert summarize([result])["baseline"]["false_claims"] is None
    else:
        assert not world.llm_record["utterances"]  # model prose cannot replace receipt speech
        assert result["metrics"]["completed"] and result["metrics"]["false_claims"] == 0


def test_llm_none_skips_without_output_or_provider(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    output = tmp_path / "not-created"
    monkeypatch.setattr(
        "sys.argv", ["donewise-evals", "--runner", "llm", "--output-dir", str(output)]
    )
    main()
    assert capsys.readouterr().out == "SKIPPED: LLM_PROVIDER=none\n"
    assert not output.exists()
