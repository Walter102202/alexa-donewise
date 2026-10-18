# Voz conversacional (consentimiento, frases para el oído, interrupción, espera, voz) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the simulator's voice turn feel like a conversation: natural yes/no for the charge, receipt phrases written for the ear, tap-to-interrupt, a spoken wait cue, a better browser voice and faster end-pointing.

**Architecture:** No new model. Consent stays a deterministic text classifier in the sim backend (`agent.py`), now with declines and a "weak affirmation only right after the question" rule. Speech wording changes only in the receipt templates (`core/donewise_harness/spoken.py`), the single source of what is heard. Everything else is browser JavaScript over the existing Web Speech API (`sim/static/app.js`).

**Tech Stack:** Python 3.12, FastAPI, pytest (`uv run pytest`), ruff (line length 100), vanilla JS, Web Speech API, Playwright MCP for browser checks. Tests run LOCAL only (dev congelado).

**Spec:** `docs/briefs/voz-conversacional-2026-10-18.md` (gitignored; local copy on Walter's machine). Decisions taken 18-oct-2026 by Walter: all five changes approved; the spoken confirmation reads the last 4 characters of the Stripe id.

## Global Constraints

- The spoken phrase of any write, `operation_get` or `receipts_recap` comes from `render_spoken` only (PRD §5.3 rule of 16-sep-2026). The sim never invents receipt wording. A decline and a wait cue are conversation without effect; they are fixed strings in the sim/browser, never claims about results.
- `approval_grant` never enters the model's tools; approval happens only in `Session.approve()` with the consent token.
- Existing public ids and classes in `sim/static/index.html` stay (`de-*`); `tests/test_sim_static.py` guards the HTML/CSS/JS contract.
- Asset cache busting: bump `?v=` on `styles.css`/`app.js` links in `index.html` to `2026-10-19a` in the first task that touches `app.js` (Task 3).
- ruff: `uv run ruff check . && uv run ruff format --check .` must pass before each commit.
- Commits go to `main` directly (project convention, no PR). No push unless Walter asks.
- Historical evidence (`docs/traces/*`, `evals/results/*`, `integrations/alexa/README.md`) keeps the old phrases; only `docs/prd.md` §5.1/§5.3 and the fixture are updated.

## Review Focus

1. ASR output with capitals and punctuation ("Yes, please charge it." / "Yeah go ahead") must count as consent; test `test_classify_consent_phrases` (Task 1).
2. "Yes" plus a changed amount ("yes but make it fifty" / "yes, $50") must NOT charge; the turn goes to the model; covered by the digit/`$`/"but" rule in `test_classify_consent_phrases` (Task 1).
3. A decline when nothing is pending is an ordinary model turn, never an error; `test_voice_decline_clears_pending_and_charges_nothing` second half (Task 1).
4. The wait cue must never be spoken over a receipt phrase or after the turn ended; `clearWait()` runs on `assistant`, `error` and `idle` events, verified in the browser (Task 4).
5. Tap-to-interrupt during the wait cue or during a long recap stops speech within one tick and starts listening; verified in the browser (Task 3).

---

### Task 1: Consent by voice: natural affirmations, real declines

**Files:**
- Modify: `sim/donewise_sim/agent.py:9-30`
- Modify: `sim/donewise_sim/app.py:132-149`
- Modify: `sim/donewise_sim/session.py:174-178` (where `pending_approval` is set)
- Modify: `sim/static/app.js:885-889` (`assistant` handler: source label)
- Test: `tests/test_sim.py`

**Interfaces:**
- Consumes: `Session.pending_approval` dict `{"request", "arguments"}`; `OneCallLLM` stub and `simulation()/act()` helpers in `tests/test_sim.py`.
- Produces: `agent.classify_consent(text: str, pending: dict | None) -> str | None` returning `"yes"`, `"no"` or `None`; `agent.DECLINED = "OK, I won't charge it. Nothing was charged."`; `pending_approval["turns_since"]: int`; SSE `assistant` event with `source: "session"`.

- [ ] **Step 1: Write the failing unit test for the classifier**

Append to `tests/test_sim.py`:

```python
from donewise_sim import agent as agent_module


PENDING_NOW = {"request": {}, "arguments": {}, "turns_since": 0}
PENDING_LATER = {"request": {}, "arguments": {}, "turns_since": 1}


@pytest.mark.parametrize(
    ("text", "pending", "expected"),
    [
        ("Yes, charge it.", PENDING_NOW, "yes"),
        ("Yes, please charge it.", PENDING_LATER, "yes"),
        ("Yeah go ahead", PENDING_LATER, "yes"),
        ("Sure, do it", PENDING_LATER, "yes"),
        ("please approve it", PENDING_LATER, "yes"),
        ("ok", PENDING_NOW, "yes"),
        ("Okay.", PENDING_NOW, "yes"),
        ("sure", PENDING_NOW, "yes"),
        ("ok", PENDING_LATER, None),
        ("sure", PENDING_LATER, None),
        ("yeah", PENDING_LATER, None),
        ("No, cancel that.", PENDING_NOW, "no"),
        ("don't charge it", PENDING_LATER, "no"),
        ("nope", PENDING_NOW, "no"),
        ("never mind", PENDING_LATER, "no"),
        ("no, don't", PENDING_NOW, "no"),
        ("yes but make it fifty", PENDING_NOW, None),
        ("yes, $50", PENDING_NOW, None),
        ("how much is it?", PENDING_NOW, None),
        ("I know, move it to ten", PENDING_NOW, None),
        ("yes", None, None),
        ("no", None, None),
    ],
)
def test_classify_consent_phrases(text, pending, expected):
    assert agent_module.classify_consent(text, pending) == expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_sim.py -k classify_consent -q`
Expected: FAIL with `AttributeError: module 'donewise_sim.agent' has no attribute 'classify_consent'`

- [ ] **Step 3: Implement `classify_consent` in `sim/donewise_sim/agent.py`**

Replace `AFFIRMATIONS` and `is_affirmation` with:

```python
STRONG_YES = re.compile(
    r"\b(yes|yep|yup|yeah go ahead|go ahead|do it|charge it|approve|confirm|please do)\b"
)
WEAK_YES = re.compile(r"^(ok|okay|sure|yeah|yep|yup|fine|alright|sounds good)$")
NO = re.compile(r"\b(no|nope|don't|do not|cancel|stop|never mind|nevermind|not now|forget it)\b")
CHANGE = re.compile(r"\d|\$|\bbut\b|\binstead\b|\bfifty\b|\bforty\b|\bhundred\b")
DECLINED = "OK, I won't charge it. Nothing was charged."


def normalize(text):
    return " ".join(re.sub(r"[^\w\s$']", " ", text.lower()).split())


def classify_consent(text, pending):
    """Deterministic yes/no against the pending approval; anything else goes to the model."""
    if not pending:
        return None
    words = normalize(text)
    if NO.search(words):
        return "no"
    if CHANGE.search(words):
        return None
    if STRONG_YES.search(words):
        return "yes"
    if pending.get("turns_since", 0) == 0 and WEAK_YES.match(words):
        return "yes"
    return None
```

Rule: a decline wins over a yes ("no, don't"); any digit, `$`, "but"/"instead" or a spelled amount sends the turn to the model; weak words count only as the first turn after the question. Keep `normalize` dropping the trailing period so "Okay." matches `WEAK_YES`.

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `uv run pytest tests/test_sim.py -k classify_consent -q`
Expected: PASS (22 cases)

- [ ] **Step 5: Write the failing integration tests**

Append to `tests/test_sim.py`:

```python
PAY_ARGS = {
    "submission_id": "pay-voice-consent",
    "amount_minor": 6000,
    "currency": "USD",
    "payee": "Ridge Plumbing",
    "concept": "deposit",
}


@pytest.mark.anyio
async def test_voice_decline_clears_pending_and_charges_nothing(mcp):
    llm = OneCallLLM("payment_charge_verified", PAY_ARGS)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, _):
        sid = metadata["session_id"]
        state = await act(client, sid, "/turn", {"text": "Pay the deposit"})
        assert state["pending_approval"]
        state = await act(client, sid, "/turn", {"text": "No, cancel that."})
        assert state["pending_approval"] is None
        said = [e["data"] for e in events if e["event"] == "assistant"]
        assert said[-1] == {"text": agent_module.DECLINED, "source": "session"}
        # A later bare "ok" is an ordinary model turn: nothing pending, nothing charged.
        await act(client, sid, "/turn", {"text": "ok"})
        assert len(mcp[0].state.harness.payments.intents()) == 0
        assert not [e for e in events if e["event"] == "error"]


@pytest.mark.anyio
async def test_weak_affirmation_counts_only_right_after_the_question(mcp):
    llm = OneCallLLM("payment_charge_verified", PAY_ARGS)
    async with simulation(mcp, llm, ui_mode="voice") as (client, metadata, events, _):
        sid = metadata["session_id"]
        await act(client, sid, "/turn", {"text": "Pay the deposit"})
        state = await act(client, sid, "/turn", {"text": "how much is it?"})
        assert state["pending_approval"]  # the question keeps the approval open
        await act(client, sid, "/turn", {"text": "ok"})
        assert len(mcp[0].state.harness.payments.intents()) == 0  # weak word, too late
        state = await act(client, sid, "/turn", {"text": "Yes, charge it."})
        assert state["pending_approval"] is None
        assert len(mcp[0].state.harness.payments.intents()) == 1
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/test_sim.py -k "voice_decline or weak_affirmation" -q`
Expected: FAIL. First test: `assert state["pending_approval"] is None` fails (decline not handled). Second: `assert len(...) == 0` fails after "ok" (charged).

- [ ] **Step 7: Implement the consent path in `agent.turn` and `app.py`**

In `sim/donewise_sim/agent.py` `turn()`, replace the `if session.pending_approval and is_affirmation(text):` block head with:

```python
    consent = classify_consent(text, session.pending_approval)
    if consent == "no":
        session.pending_approval = None
        session.messages.append(
            {"role": "assistant", "content": [{"type": "text", "text": DECLINED}]}
        )
        await session.emit("assistant", {"text": DECLINED, "source": "session"})
        return
    if consent == "yes":
        ... (existing approve body unchanged)
    if session.pending_approval:
        session.pending_approval["turns_since"] += 1
```

In `sim/donewise_sim/session.py:174-178` set `"turns_since": 0` when `pending_approval` is created.

In `sim/donewise_sim/app.py:135-139` and `:149`:

```python
        consent = agent.classify_consent(body.text, session.pending_approval)
        if session.ui_mode == "scripted" and consent != "yes":
            raise HTTPException(409, "Free input requires a new voice session")
        if consent == "yes" and not session.consent_token:
            raise HTTPException(409, NO_CONSENT)
```

`/approve` keeps sending `"Yes, charge it."` (strong yes, valid at any `turns_since`).

In `sim/static/app.js:889` extend the source label:

```js
    if (data.source === 'model') text('source', 'Model · no operation result');
    else if (data.source === 'session') text('source', 'Session · no operation, nothing charged');
```

- [ ] **Step 8: Run the whole sim suite**

Run: `uv run pytest tests/test_sim.py tests/test_sim_static.py -q`
Expected: PASS, including the existing `test_voice_affirmation_without_admin_is_rejected_up_front` (its "yes" is a strong yes at `turns_since == 0`).

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add sim/donewise_sim/agent.py sim/donewise_sim/app.py sim/donewise_sim/session.py sim/static/app.js tests/test_sim.py
git commit -m "feat(sim): natural voice consent with real declines; weak yes only right after the question"
```

---

### Task 2: Receipt phrases written for the ear

**Files:**
- Modify: `core/donewise_harness/spoken.py:19-50` (TEMPLATES) and `:98-125` (recap and charge rendering)
- Modify: `tests/test_contracts.py:205-216`
- Modify: `sim/fixtures/story-3min.json` (two `spoken` strings: charge at ~line 160, recap at ~line 373)
- Modify: `docs/prd.md` §5.1 rows 2b and 5, §5.3 rows "VERIFIED (cobro)" and "Recap"
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: `RecapResult.generated_at`, `RecapResult.timezone`, `RecapItem.observed_at`, `PaymentChargeResult.payment_intent_id`.
- Produces: new exact phrases (below). The Alexa classic skill and the Lightsail server pick them up only after Walter redeploys Lightsail; this plan does not deploy.

New phrases, exact:

- Charge: `Done: a $60 test charge is recorded for Ridge Plumbing's deposit, charged once. Confirmation ending in o s i t.` (last 4 characters of `payment_intent_id`, lower-cased as stored, joined by single spaces so TTS spells them). With recovery: ` You don't need to try again.` appended as today.
- Recap item: `{summary}, read back {when}.` where `{when}` is `today at 7:44 PM`, `yesterday at 7:44 PM`, or `on September 16 at 7:44 PM`, relative to `generated_at` in `receipt.timezone`. No zone, no UTC offset in speech.
- Recap unverified count: 0 → `Nothing is unverified or pending.`; 1 → `1 operation remains unverified or pending.`; n → `{n} operations remain unverified or pending.`

- [ ] **Step 1: Update the expected phrases in the failing test**

In `tests/test_contracts.py:205-216` replace the charge and recap entries of `expected` with:

```python
        "Done: a $60 test charge is recorded for Ridge Plumbing's deposit, charged once. "
        "Confirmation ending in o s i t. You don't need to try again.",
        ...
        "From the saved receipts: the plumber is at 10 to 11 AM, read back today at 7:44 PM. "
        "One $60 test charge for the deposit, read back today at 7:40 PM. "
        "Nothing is unverified or pending. "
        "Nothing new was written to your calendar or payments.",
```

Add a unit test for the relative day:

```python
def test_recap_reads_the_day_relative_to_generation():
    recap = SPECS["receipts_recap"].output_model.model_validate(ROWS[6]["result"])
    la = ZoneInfo("America/Los_Angeles")
    observed = recap.items[0].observed_at.astimezone(la)
    same_day = recap.model_copy(update={"generated_at": observed + timedelta(hours=1)})
    next_day = recap.model_copy(update={"generated_at": observed + timedelta(days=1)})
    assert "read back today at 7:44 PM" in render_spoken(same_day)
    assert "read back yesterday at 7:44 PM" in render_spoken(next_day)
```

(Import `ZoneInfo` from `zoneinfo`; `timedelta` is already imported. `ROWS[6]` is the recap row; confirm the index by `ROWS[6]["tool"] == "receipts_recap"` in the assertion.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_contracts.py -k "story_shapes or relative_to_generation" -q`
Expected: FAIL on the charge phrase (`Confirmation pi_story_deposit` vs `ending in o s i t`).

- [ ] **Step 3: Implement in `core/donewise_harness/spoken.py`**

TEMPLATES changes:

```python
    "charge": (
        "Done: a {amount} test charge is recorded for {payee}'s {concept}, charged once. "
        "Confirmation ending in {confirmation}."
    ),
    "recap_item": "{summary}, read back {when}.",
    "recap_none_unverified": "Nothing is unverified or pending.",
```

Add `def spoken_day(value: datetime, now: datetime, zone: str) -> str` returning `"today at {clock}"`, `"yesterday at {clock}"` or `"on {Month} {day} at {clock}"` (month via `f"{local:%B} {local.day}"`, never `%-d`, this runs on Windows). In the recap branch pass `now=receipt.generated_at` and build `unverified` with the three forms. In the charge branch pass `confirmation=" ".join(confirmation[-4:])`.

- [ ] **Step 4: Run the contracts tests**

Run: `uv run pytest tests/test_contracts.py -q`
Expected: `test_story_shapes_spoken_and_shared_identity` still FAILS because the fixture's stored `spoken` differs (`result.spoken == phrase`); the relative-day test PASSES.

- [ ] **Step 5: Update the fixture and the PRD**

In `sim/fixtures/story-3min.json` replace the two `spoken` strings with the exact new phrases from Step 1. The fixture's recap `generated_at` is `2026-09-17T02:45:00Z` and both readings are `2026-09-17T02:4x:xxZ`: all fall on 16 September in Los Angeles, hence "today at". The relative-day unit test covers "yesterday" with a shifted `generated_at`.

In `docs/prd.md` §5.1 row 2b replace `Confirmation pi_….` with `Confirmation ending in {last 4}.`; row 5 phrase to `... read back today at 7:44 PM. One $60 test charge for the deposit, read back today at 7:40 PM. Nothing is unverified or pending. Nothing new was written to your calendar or payments.`; §5.3 "VERIFIED (cobro)" row to `Confirmation ending in {last 4 of payment_intent_id, spelled}.`; "Recap" row items to `read back {today|yesterday|on Month day} at {time}`. Add one line under the 16-sep rule: `Cambio 19-oct-2026: frases ajustadas al oído (sin zona ni offset en voz, confirmación por los últimos 4 caracteres); pantalla conserva el detalle.`

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. `tests/test_server.py:486` asserts `"1 operation remains unverified or pending."`, which is unchanged; no other test pins recap wording.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add core/donewise_harness/spoken.py tests/test_contracts.py sim/fixtures/story-3min.json docs/prd.md tests/test_sim.py
git commit -m "feat(spoken): phrases written for the ear: relative day, no zone in voice, confirmation by last four"
```

---

### Task 3: Tap to interrupt

**Files:**
- Modify: `sim/static/app.js:523-531` (mic click), `:681` (updateControls), `:474-486` (speak)
- Modify: `sim/static/index.html:8,99` (`?v=2026-10-19a`)
- Test: `tests/test_sim_static.py`

**Interfaces:**
- Consumes: `ttsActive()`, `speaking`, `recognizing`, `updateControls()`.
- Produces: `function stopSpeaking()` (cancels synthesis, sets `speaking = false`, calls `updateControls()`); mic enabled while TTS plays.

- [ ] **Step 1: Write the failing static test**

Append to `tests/test_sim_static.py`:

```python
def test_mic_interrupts_speech_instead_of_waiting_for_it():
    assert "get('mic').disabled = recognizing ? false : (busy || !Recognition);" in JS
    assert "ttsActive()) return;" not in JS  # the mic click no longer bails out while speaking
    assert "function stopSpeaking()" in JS
    assert "?v=2026-10-19a" in HTML
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sim_static.py -k interrupts -q`
Expected: FAIL on the first assertion.

- [ ] **Step 3: Implement in `app.js` and bump the asset version**

- Add `function stopSpeaking() { try { speechSynthesis.cancel(); } catch (_) {} speaking = false; updateControls(); }` next to `speak()`; use it in the Voice-off handler (line 497) too.
- Mic click (line 529): `if (!LIVE || LIVE_BUSY || controlBusy) return; if (ttsActive()) stopSpeaking();`
- `updateControls` (line 681): `get('mic').disabled = recognizing ? false : (busy || !Recognition);`
- `index.html`: both asset links to `?v=2026-10-19a`.

- [ ] **Step 4: Run static tests**

Run: `uv run pytest tests/test_sim_static.py -q`
Expected: PASS

- [ ] **Step 5: Browser check (Playwright MCP, local server + sim in scripted mode)**

Start: `uv run donewise-server` (MCP_BEARER_TOKEN, DEMO_ADMIN_TOKEN, DONEWISE_DATA_DIR, PORT=8765) and `uv run donewise-sim` (MCP_URL, same tokens, LLM_PROVIDER=none, SIM_PORT=8080). Open `http://127.0.0.1:8080`, click Continue to reach turn 1 (TTS speaks), evaluate `!document.getElementById('de-mic').disabled` while `speechSynthesis.speaking` → true; click the mic → `speechSynthesis.speaking === false` and `aria-pressed="true"` on the mic.
Expected: both true; screenshot saved to `.superpowers/sdd/2026-10-18-voz-conversacional/shot-interrupt.png`.

- [ ] **Step 6: Commit**

```bash
git add sim/static/app.js sim/static/index.html tests/test_sim_static.py
git commit -m "feat(sim): tap the mic to interrupt the spoken answer"
```

---

### Task 4: Spoken wait cue and spoken errors

**Files:**
- Modify: `sim/static/app.js` (`speak()` signature, `status`/`assistant`/`error`/`user` SSE handlers at ~846-900)
- Test: `tests/test_sim_static.py`

**Interfaces:**
- Consumes: `speak(phrase)`, `stopSpeaking()` from Task 3, SSE `status` payloads `thinking`, `calling <tool>`, `pending`, `idle`.
- Produces: `const WAIT_PHRASE = "One moment, I'm checking that.";`, `const WAIT_AFTER_MS = 1500;`, `function clearWait()`; `speak(phrase, {interim})` where an interim utterance is cancelled by any later `speak`.

- [ ] **Step 1: Write the failing static test**

```python
def test_wait_cue_claims_nothing_and_errors_are_spoken():
    assert "const WAIT_PHRASE = \"One moment, I'm checking that.\";" in JS
    assert "const WAIT_AFTER_MS = 1500;" in JS
    assert "function clearWait()" in JS
    for banned in ("done", "charged", "booked", "calendar", "confirmed"):
        assert banned not in "One moment, I'm checking that.".lower()
    assert "LIVE_ERROR = JSON.parse(e.data).message; note(LIVE_ERROR); speak(LIVE_ERROR);" in JS
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sim_static.py -k wait_cue -q`
Expected: FAIL (`WAIT_PHRASE` absent).

- [ ] **Step 3: Implement**

- `let waitTimer = null, waitSpoken = false;`
- `function clearWait() { clearTimeout(waitTimer); waitTimer = null; if (speakingInterim) stopSpeaking(); }` where `speakingInterim` is set by `speak(phrase, {interim: true})` and reset by any `speak`/`stopSpeaking`.
- `on('user', …)`: `clearWait(); waitSpoken = false;`
- `on('status', …)` non-replayed: if `data.status === 'thinking' || data.status.startsWith('calling ')` and `!waitSpoken && !waitTimer && voiceOn` → `waitTimer = setTimeout(() => { waitSpoken = true; speak(WAIT_PHRASE, {interim: true}); }, WAIT_AFTER_MS)`. On `idle` → `clearWait()`.
- `on('assistant', …)` non-replayed: `clearWait()` before `speak(data.text)`.
- `error` listener with `e.data` (line ~903): `LIVE_ERROR = JSON.parse(e.data).message; note(LIVE_ERROR); speak(LIVE_ERROR);` after `clearWait()`.
- `speak()` must not return early because of `recognizing` for interim cues when the mic is idle; keep the guard as is (interim cue is never needed while listening).

- [ ] **Step 4: Run static tests**

Run: `uv run pytest tests/test_sim_static.py -q`
Expected: PASS

- [ ] **Step 5: Browser check**

Same local setup as Task 3. Arm nothing; click Continue for turn 1 and watch `speechSynthesis.speaking` within 2 s of the `calling calendar_create_verified` status (verification takes >1.5 s with Fake adapters? If the step completes under 1.5 s, verify the inverse: no wait cue spoken and no error). Then click Continue for turn 2 (fault drop → PENDING → recovered): the PENDING phrase cancels the pending wait timer; the final phrase replaces it. Trigger an error by clicking Continue twice quickly after the script ends (409 "Script complete") → `note` shows and TTS speaks it.
Expected: no overlapping utterances (check `speechSynthesis.pending === false` after each phrase); screenshot `shot-wait-cue.png`.

- [ ] **Step 6: Commit**

```bash
git add sim/static/app.js tests/test_sim_static.py
git commit -m "feat(sim): spoken wait cue after 1.5 s and spoken turn errors"
```

---

### Task 5: Better browser voice and two-stage end-pointing

**Files:**
- Modify: `sim/static/app.js:474-486` (`speak`), `:521` (`SILENCE_MS`), `:548-556` (`onresult`)
- Test: `tests/test_sim_static.py`

**Interfaces:**
- Consumes: `speak(phrase, opts)` from Task 4, `speakable()`.
- Produces: `function pickVoice()`, `const VOICE_PREFERENCE = [/Google US English/, /Microsoft .* Online \(Natural\).*en-US/i, /^en-US$/]` matched against `voice.name` then `voice.lang`; `const FINAL_SILENCE_MS = 700, INTERIM_SILENCE_MS = 2000;`; `resetSilence(ms)`.

- [ ] **Step 1: Write the failing static test**

```python
def test_voice_choice_and_two_stage_endpointing():
    assert "function pickVoice()" in JS and "VOICE_PREFERENCE" in JS
    assert "const FINAL_SILENCE_MS = 700, INTERIM_SILENCE_MS = 2000;" in JS
    assert "SILENCE_MS = 2000, MAX_RESTARTS" not in JS
    assert "resetSilence(last && last.isFinal ? FINAL_SILENCE_MS : INTERIM_SILENCE_MS)" in JS
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sim_static.py -k two_stage -q`
Expected: FAIL (`pickVoice` absent).

- [ ] **Step 3: Implement**

- `pickVoice()`: iterate `VOICE_PREFERENCE`, return the first `speechSynthesis.getVoices()` entry whose `name` or `lang` matches; cache in `let chosenVoice`; refresh on `speechSynthesis.onvoiceschanged`.
- `speak()`: split `utterance` into sentences with `/[^.!?]+[.!?]+["']?|[^.!?]+$/g`, create one `SpeechSynthesisUtterance` per sentence (`voice = chosenVoice`, `lang 'en-US'`, `rate 1`), queue them all; `speaking = false` only on the last one's `onend`/`onerror`.
- `const FINAL_SILENCE_MS = 700, INTERIM_SILENCE_MS = 2000, MAX_RESTARTS = 5;` and `resetSilence(ms)` takes the timeout; in `onresult`: `const last = results.at(-1); if (armed) resetSilence(last && last.isFinal ? FINAL_SILENCE_MS : INTERIM_SILENCE_MS);`.

- [ ] **Step 4: Run static tests and the full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
Expected: PASS, lint clean.

- [ ] **Step 5: Browser check**

Local setup as Task 3. In the console: `speechSynthesis.getVoices().map(v => v.name)` and confirm the chosen voice name appears in the first queued utterance (`chosenVoice.name`). Click Continue to the recap (turn 5) and confirm the phrase is spoken sentence by sentence with no symbol names ("dash", "slash", "U T C") in the text passed to utterances (log `speakable(...)` output). Mic end-pointing is manual: tap the mic, say "yes charge it", confirm the field sends within about one second of the final result (Walter can repeat this at recording).
Expected: chosen voice is Google US English on Chrome or a Natural voice on Edge; screenshot `shot-voice.png`.

- [ ] **Step 6: Commit**

```bash
git add sim/static/app.js tests/test_sim_static.py
git commit -m "feat(sim): preferred browser voice, sentence pacing and two-stage end-pointing"
```

---

### Task 6: Documentation and local notes

**Files:**
- Modify: `README.md` (simulator paragraph: add one sentence on voice consent, interruption and the wait cue)
- Modify: `docs/devpost.md` (local, gitignored): one sentence under "What's next" naming Nova 2 Sonic and the model router as the Alexa+-shaped next step, and one under the HTML/CSS/JS entry for the 19-Oct voice changes
- Modify: `docs/guion-video.md` (local, gitignored): turn 2 may use a natural "Yes, please" and the recap can be interrupted by tapping the mic; the recap phrase changes to the new wording

- [ ] **Step 1: Apply the three edits** (exact copy decided at execution from the files' current text; keep them to one or two sentences each)
- [ ] **Step 2: Run the full suite one last time**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 3: Commit the README only** (the other two are gitignored)

```bash
git add README.md
git commit -m "docs(readme): voice consent, interruption and wait cue in the simulator"
```

Walter-side after the plan: redeploy Lightsail so the classic Alexa skill speaks the new recap wording; re-record the Alexa simulation evidence only if the Devpost text quotes the phrase.
