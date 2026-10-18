# Dedicated Lightsail instance

Target account `027018013541`, profile `donewise`, region `us-east-1`. Use the
minimum Linux/Unix **instance** bundle with a public IPv4 address, Ubuntu 24.04,
a static IP, and tags `Project=DoneWise`, `KeepUntil=2026-11-20`. Check the current
bundle price before creation; keep the approved total AWS budget under USD 100.
No container service: SQLite needs persistent disk. Existing budget alerts are unchanged.

Deployed as `donewise-mcp-20261013`, static IP `52.55.245.231`, at
`https://donewise-mcp.duckdns.org/mcp`. [Remote proof and measured latencies](../../docs/traces/lightsail-2026-10-13.md)
cover five connected turns. Confirm STS account before provisioning. Never use a Hosli profile.
Redeployed on 18 October 2026 from snapshot `11445c4` (spoken phrases written for the ear): the
previous source tree was kept as `/opt/donewise/source-prev-20261018-11445c4`, the registry and
secrets were untouched, and the classic Alexa skill answered the recap question with the new
wording through SMAPI (3.8 s, RequestIntent).

1. Create the dedicated instance and static IP. Allow 80/443 publicly; restrict SSH
   to the operator's current IP. Do not open 8765, 8080 or `/admin` to the internet.
2. Run `setup.sh` over SSH. Transfer a `git archive HEAD` snapshot to
   `/opt/donewise/source` (the prepared commits are local, so cloning GitHub alone
   would deploy old code). Avoid including untracked build files or local secrets.
3. Provision `/opt/donewise/private/server.env` mode 0600 with only
   `STRIPE_SECRET_KEY`, `GOOGLE_CALENDAR_ID`, `MCP_BEARER_TOKEN`, `DEMO_ADMIN_TOKEN`,
   `USER_TIMEZONE`, and `DONEWISE_PENDING_AFTER=0.45`. Use random strong independent
   bearer/admin tokens. Transfer the Google service-account JSON separately as
   `/opt/donewise/private/google.json`, mode 0600. No Anthropic/AWS credentials.
4. To continue a local recorded run, use SQLite's backup API on the chosen connected
   registry after its work has quiesced. Transfer that consistent backup to
   `/opt/donewise/data/registry.sqlite` before starting the server. Preserve the
   recorded run ID and user `demo`; do not copy an active SQLite file blindly.
5. Point the approved hostname (or the user's DuckDNS hostname) to the static IP.
   Set `MCP_HOST` and `ACME_EMAIL`; run from the source checkout:

   ```sh
   sudo docker compose --env-file /opt/donewise/private/compose.env -f deploy/lightsail/compose.yaml up -d --build
   ```

6. Verify HTTPS certificate, missing/wrong bearer gets 401, and `/admin`, `/healthz`
   and `/` return 404 externally. Run the Strands recap against `https://HOST/mcp`.
   Inspect `docker stats --no-stream` before sustained validation. Server+Caddy are
   limited to 352 MiB aggregate; do not add replica workers to the same SQLite file.
7. For trusted five-turn fault/approval testing, SSH forward the internal server
   address temporarily (or execute the operator script on the instance). Do not
   expose admin routes in Caddy. Record per-tool sample counts, faults, p50/p95 and
   verified completion time separately; a single local recap is not cloud latency.

On Windows, set `SSL_CERT_FILE` to the isolated client's certifi bundle if httpx2's
system truststore raises a native certificate-chain error. TLS verification remains enabled.
For the smoke, set `DONEWISE_ADMIN_URL=http://127.0.0.1:18767` and keep the temporary
SSH forward alive for the entire script. The fifth turn starts a new read-only session.

Keep the instance until 20 November for judging. Shutdown/deletion and any scheduled
cleanup need a separate explicit request; no destructive cleanup is automated here.
