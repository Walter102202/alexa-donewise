# Stripe sandbox setup and connected-provider evidence

Verified 18 September 2026 using Stripe CLI **1.51.0**, Windows PowerShell and Python 3.12.
This is a temporary, unclaimed Stripe sandbox. No live payments or bank accounts are involved.
The sandbox created for this run **expires on 25 September 2026 unless claimed beforehand**.
Permanent account onboarding from Chile and the claim flow have not been validated.

## Create a sandbox without account registration

Stripe documents anonymous sandbox provisioning through its official CLI:
[Sandboxes](https://docs.stripe.com/sandboxes).
For this run, npm metadata pointed to `stripe/stripe-cli` and version 1.51.0.

```powershell
npm install -g @stripe/cli@1.51.0
stripe version
stripe sandbox create --help

$stripeConfig = "$env:USERPROFILE/.config/donewise/stripe-cli.toml"
stripe --config $stripeConfig --project-name donewise-demo sandbox create --email YOUR_EMAIL --non-interactive
```

Run creation once. The CLI saves credentials, the private claim URL, and expiry to that profile.
Its output also contains secrets: do not paste it into chat, screenshots, logs committed to Git,
or this document. In the recorded setup, output was captured outside the repo in a private file
and the credential/claim fields were redacted after configuring the application.
The profile directory's Windows ACL grants access to the current user and SYSTEM.

Observed result: sandbox provisioning succeeded without browser login. The returned server key
starts with `rkcs_test_`. An authenticated read of `/v1/payment_intents` returned HTTP 200.
The original adapter rejected this key before any request because it allowed only `sk_test_`.
The adapter and server now share the explicit allowlist `sk_test_`, `rkcs_test_`.
The provider's `livemode: false` checks remain in place on payment writes and reads.
Other prefixes, including ordinary `rk_test_` keys, are outside this change's supported set.

## Configure DoneWise

Keep the existing Google credential path and calendar ID in ignored `.env`. Set:

```dotenv
STRIPE_SECRET_KEY=<test_mode_api_key from the private CLI profile>
DONEWISE_MODE=connected
DONEWISE_DATA_DIR=./data/connected
LLM_PROVIDER=none
MCP_BEARER_TOKEN=<random local secret>
DEMO_ADMIN_TOKEN=<different random local secret>
```

The recorded setup transferred the key directly from the local TOML profile to `.env` and
generated both local tokens. It preserved the existing Google configuration. No credential
value or private claim URL belongs in the repository. `.env.example` remains key-free.

Start the server and simulator in separate terminals, from the repository root:

```powershell
uv run --env-file .env donewise-server
# Second terminal:
uv run --env-file .env donewise-sim
```

Open `http://localhost:8080` and use Scripted mode. Bedrock is not configured by this procedure.
These commands use the connected providers; the Compose quickstart still uses local Fake adapters.
Each new payment operation in connected mode creates a test-mode payment, not real money.

## Verification performed

```powershell
uv run pytest tests/test_stripe_test.py tests/test_server.py tests/test_connected_app.py -q
uv run --env-file .env pytest tests/test_connected_providers.py -m connected -q --tb=short
```

- **41 local tests passed.** Existing payment replay/read/search coverage now includes the CLI
  key, with configuration coverage and rejection of production/public keys. One pre-existing
  Starlette/AnyIO deprecation warning was emitted.
- **1 connected smoke test passed** against real Google Calendar and Stripe sandbox APIs.
  It created, reread, moved, and deleted a test calendar event; rejected a stale ETag; created a
  USD 1.00 test payment; replayed that payment with the same idempotency key; checked the same
  PaymentIntent ID; and reread its amount, currency, metadata, and successful status.
- An independent HTTP list request found **exactly one PaymentIntent**, `succeeded`, amount `100`,
  currency `usd`, and `livemode: false`. The payment remains available as test evidence.
- The connected application started and shut down successfully with the `GoogleCalendar` and
  `StripeTest` adapters. This startup check did not exercise a browser or LLM session.
- Local read-back evidence is in ignored `data/stripe-connection-verification.json`.

The first connected run failed before reaching Stripe: its generated calendar times included
microseconds, while Google's read-back discarded them. The smoke fixture now uses whole seconds;
production date comparison was not changed. Subsecond calendar inputs remain outside this proof.

Full connected fault-injection acceptance, the five-turn browser flow with real providers,
Bedrock invocation, microphone/TTS rehearsal, and latency measurements remain pending.
The successful direct provider replay is not proof of lost-response recovery through the harness.

## Claim before expiry

The private CLI profile records the sandbox expiry separately from the key expiry. The later key
date does not extend the sandbox's lifetime. To open the claim flow for this exact profile:

```powershell
$stripeConfig = "$env:USERPROFILE/.config/donewise/stripe-cli.toml"
stripe --config $stripeConfig --project-name donewise-demo sandbox claim
```

Follow Stripe's actual registration/eligibility requirements; do not invent a business country.
The CLI says to run `stripe login` after claiming to obtain permanent keys. Any replacement key
must be checked for compatibility and remain test-only before updating DoneWise's `.env`.
If claiming is unavailable, this connection remains temporary and must not be presented as a
durable demo setup. No claim was submitted during this setup.
