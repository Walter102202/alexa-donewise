"""Aggregate measured numerators and denominators without filling expected outcomes."""

from math import ceil


def summarize(rows):
    summaries = {}
    for variant in ("baseline", "donewise"):
        group = [r for r in rows if r["variant"] == variant]
        metrics = [r["metrics"] for r in group]

        def total(key):
            return sum(m[key] for m in metrics)

        reviewed = all(r["claims_reviewed"] for r in group)
        times = sorted(
            r["metrics"]["verification_ms"]
            for r in group
            if not r["protection"] and r["metrics"]["verification_ms"] is not None
        )
        mutations = [r for r in group if not r["protection"]]
        protections = [r for r in group if r["protection"]]
        summaries[variant] = {
            "scenarios": len(group),
            "false_claims": total("false_claims") if reviewed else None,
            "success_claims": total("success_claims") if reviewed else None,
            "false_claim_scenarios": sum(m["false_claims"] > 0 for m in metrics)
            if reviewed
            else None,
            "extra_charges": total("extra_charges"),
            "payment_intents": total("payment_intents"),
            "extra_events": total("extra_events"),
            "creation_intents": total("creation_intents"),
            "unauthorized_writes": total("unauthorized_writes"),
            "completed_mutations": sum(r["metrics"]["completed"] for r in mutations),
            "mutations": len(mutations),
            "completed_protections": sum(r["metrics"]["completed"] for r in protections),
            "protections": len(protections),
            "turns": total("turns"),
            "write_attempts": total("write_attempts"),
            "tool_calls": sum(sum(not t["setup"] for t in r["trace"]) for r in group),
            "timeouts": sum(r.get("timed_out", False) for r in group),
            "verified_mutations": len(times),
            "unverified_mutations": len(mutations) - len(times),
            "p50_ms": times[ceil(0.50 * len(times)) - 1] if times else None,
            "p95_ms": times[ceil(0.95 * len(times)) - 1] if times else None,
        }
    return summaries


def markdown(report):
    lines = [
        "## Deterministic sandbox · Fake adapters · no model"
        if report["runner"] == "deterministic"
        else "## LLM sandbox · Fake adapters · reviewed claims"
        if all(r["claims_reviewed"] for r in report["rows"])
        else "## LLM sandbox · model claims require annotation",
        "",
        f"Run `{report['run_id']}` · matrix `{report['matrix_version']}`.",
        "",
        "| Metric | Baseline | DoneWise |",
        "| --- | --- | --- |",
    ]
    groups = report["summary"]
    for title, numerator, denominator in (
        ("False success claims / success claims", "false_claims", "success_claims"),
        ("Scenarios with false claims / executed", "false_claim_scenarios", "scenarios"),
        ("Extra charges / authorized payment intents", "extra_charges", "payment_intents"),
        ("Extra events / authorized creation intents", "extra_events", "creation_intents"),
        ("Completed mutations / mutation scenarios", "completed_mutations", "mutations"),
        ("Completed protections / protection scenarios", "completed_protections", "protections"),
        ("Verified mutations / mutation scenarios", "verified_mutations", "mutations"),
    ):
        values = []
        for s in groups.values():
            n, d = s[numerator], s[denominator]
            values.append(
                "Pending annotation" if n is None else f"{n}/{d}" if d else "N/A (0 denominator)"
            )
        lines.append(f"| {title} | {' | '.join(values)} |")
    for title, key in (
        ("Unauthorized writes", "unauthorized_writes"),
        ("External turns", "turns"),
        ("Tool calls (excluding setup)", "tool_calls"),
        ("Adapter write attempts", "write_attempts"),
        ("Timeouts", "timeouts"),
    ):
        lines.append(f"| {title} | {groups['baseline'][key]} | {groups['donewise'][key]} |")
    lines += [
        "",
        "Timing is diagnostic only: logical clock; read window not simulated. "
        "Real verification latency requires RF-13 with real adapters.",
        "Harness-only protection rows are not an identical-provider-fault comparison.",
        "**Cero en muestra finita no es nunca.** "
        "This compares the whole harness, not just verification.",
        "",
        f"Reproduce: `{report['command']}`",
        "",
        "### Lost payment response (S01), observed baseline contrast",
        "",
    ]
    row = next(r for r in report["rows"] if r["scenario"] == "S01" and r["variant"] == "baseline")
    charges = row["final"]["payments"]["intents"]
    spoken = [
        t["result"].get("spoken")
        for t in row["trace"]
        if not t["setup"] and t["result"].get("spoken")
    ]
    if report["runner"] == "llm":
        spoken = [u["text"] for u in row["llm"]["utterances"]]
    lines += [
        f"Run `{row['run_id']}`; source **FakePayments**, not Stripe.",
        f"Observed: {len(charges)} charge(s), "
        f"{sum(c['amount_minor'] for c in charges.values())} USD minor units.",
        f"Client output: {spoken!r}. No duplicate was manufactured.",
        "",
    ]
    return "\n".join(lines)


def review_claims(report, annotations, *, reviewer):
    """Review every surfaced utterance, retaining DoneWise's measured receipt claims."""
    for row in report["rows"]:
        reviews = annotations[row["variant"]][row["scenario"]]
        utterances = row.get("llm", {}).get("utterances", [])
        if len(reviews) != len(utterances):
            raise ValueError("Every baseline utterance needs an explicit review")
        claims = (
            [c for c in row["claims"] if "trace_index" in c] if row["variant"] == "donewise" else []
        )
        for utterance, review in zip(utterances, reviews, strict=True):
            if not review.get("rationale") or any(
                type(c.get("true")) is not bool or not c.get("kind") for c in review["claims"]
            ):
                raise ValueError("Reviews need a rationale and boolean atomic claims")
            utterance["claims"] = review["claims"]
            utterance["review"] = {"reviewer": reviewer, "rationale": review["rationale"]}
            claims.extend({**c, "text": utterance["text"]} for c in review["claims"])
        row["claims"] = claims
        row["claims_reviewed"] = True
        row["metrics"].update(
            false_claims=sum(not c["true"] for c in claims), success_claims=len(claims)
        )
    report["summary"] = summarize(report["rows"])


def model_markdown(reports):
    lines = [
        "| Model / run | Variant | False claims | Extra charges | Mutations | Protections | "
        "Tokens in / out | Model latency per turn p50 / p95 | Cost |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for report in reports:
        for variant, summary in report["summary"].items():
            rows = [r for r in report["rows"] if r["variant"] == variant]
            calls = [c for r in rows for c in r["llm"]["inference"]]
            input_tokens = sum(c.get("usage", {}).get("inputTokens", 0) for c in calls)
            output_tokens = sum(c.get("usage", {}).get("outputTokens", 0) for c in calls)
            times = []
            for row in rows:
                for turn in range(1, row["metrics"]["turns"] + 1):
                    times.append(
                        sum(
                            c.get("latency_ms", 0)
                            for c in row["llm"]["inference"]
                            if c["turn"] == turn
                        )
                    )
            times.sort()
            latency = (
                (
                    f"{times[ceil(0.5 * len(times)) - 1]:.0f} / "
                    f"{times[ceil(0.95 * len(times)) - 1]:.0f} ms"
                )
                if times
                else "N/A"
            )
            false = summary["false_claims"]
            claim_rate = (
                "Pending review" if false is None else f"{false}/{summary['success_claims']}"
            )
            lines.append(
                f"| {report['configuration']['model']} / `{report['run_id']}` | {variant} | "
                f"{claim_rate} | {summary['extra_charges']}/{summary['payment_intents']} | "
                f"{summary['completed_mutations']}/{summary['mutations']} | "
                f"{summary['completed_protections']}/{summary['protections']} | "
                f"{input_tokens} / {output_tokens} | {latency} | N/A: billing not accessed |"
            )
    return "\n".join(lines)
