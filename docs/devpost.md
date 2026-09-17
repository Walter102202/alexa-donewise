# Devpost description — draft, not submitted

## Project name

DoneWise

## One sentence

DoneWise is an MCP verification harness that reads external effects back before an assistant claims success.

## Features and functionality

An assistant can receive an acknowledgement without an action happening—or lose a response after
an action already happened. DoneWise persists operation identity, asks for consent bound to payment
details, reads back state and returns structured receipts. Missing evidence produces uncertainty,
not invented success. Recovery follows bounded replay rules.

The web demo follows Clara through a plumber booking, a $60 sandbox deposit, a lost payment
response, a move acknowledged without a write, an explicit retry, and a recap from stored receipts.
Faults are labelled. UI and speech derive from receipts. Scripted mode fixes the inputs while
executing real MCP calls and verification.

The MIT Python core has a small adapter protocol. Six MCP tools provide calendar creation/movement,
payment, approval, status and recap. The deterministic comparison reports baseline false claims
4/10 versus DoneWise 0/11; extra charges 2/4 versus 0/4. This finite sample compares the whole
harness with direct writes, not the verifier alone; it is not a universal reliability claim.

## What is real

Local MCP, consent checks, asynchronous verification, SQLite audit, persisted Fake stores, fault
injection, SSE UI and deterministic evaluation execute. Inspector and Python ClientSession have
recorded acceptance; a separate Claude Code/Sonnet session completed five sandbox turns.

## What is simulated or pending

Alexa+ is simulated; no official integration or certification claimed. Quickstart calendar/payments
are local Fakes, with no real money. Offline fixture mode is labelled. Google Calendar and Stripe
test adapters exist, but connected acceptance, latency, simulator live-model acceptance and human
voice rehearsal remain pending. Planned AWS integration is not a validated deployment.
There is no final video or hosted demo yet.

## Links to paste into the form

No git remote is configured. Replace placeholders only after publication; these are not live URLs.

| Form link | Reviewable artifact | Publication status |
| --- | --- | --- |
| Repository | [README](../README.md), [MIT license](../LICENSE) | PUBLIC_REPOSITORY_URL — pending |
| Demo | [Docker quickstart](../README.md#quickstart-no-keys-no-real-money) | HOSTED_DEMO_URL — pending; local demo works |
| Video | [Evidence map](../README.md#video-claims--evidence) | PUBLIC_VIDEO_URL — pending |
| Evaluation | [Table](../evals/results/2026-09-17-sandbox-run_c1489defba8445f1a7592d550df68884.md) | Link through future public repository |
| Feedback | [Product feedback](product-feedback.md) | Link through future public repository |
| Friction | [Friction log](friction-log.md) | Link through future public repository |

Submission intent from PRD §9: Alexa+ track; AWS Builder and Open Source mini-challenges.
No eligibility approval, credits, publication or submission is claimed by this draft.
