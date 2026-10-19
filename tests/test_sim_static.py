"""Static contract between sim/static/app.js and the served HTML/CSS (Editorial plano)."""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "sim" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def test_every_id_app_js_reads_exists_in_index_html():
    wanted = set(re.findall(r"\bget\('([a-z-]+)'\)", JS)) | set(
        re.findall(r"\btext\('([a-z-]+)'", JS)
    )
    missing = sorted(i for i in wanted if f'id="de-{i}"' not in HTML)
    assert missing == []


def test_every_class_app_js_creates_or_queries_is_styled():
    created = set(re.findall(r"el\('[a-z]+', '(de-[a-z-]+)'", JS)) | {"de-director"}
    unstyled = sorted(c for c in created if not re.search(rf"\.{c}(?![\w-])", CSS))
    assert unstyled == []
    assert 'class="de-director"' in HTML
    assert "[hidden]{display:none!important}" in CSS.replace(" ", "")


def test_editorial_plano_tokens_are_in_place():
    assert "family=Instrument+Sans" in HTML and "family=Red+Hat+Mono" in HTML
    assert "Instrument+Serif" not in HTML and "IBM+Plex" not in HTML
    assert "light-dark(" not in CSS
    assert re.findall(r"border-radius:\s*(?!0\b)[^;}]+", CSS) == []  # solo radio 0
    assert "#1F3BFF" in CSS.upper() and "#111111" in CSS.upper()


def test_editorial_plano_layout_details():
    # Rail shows "Demo controls" once when session controls and the director bar are both visible.
    once = ".de-session-controls:not([hidden])+.de-director.de-director-label{display:none}"
    assert once in CSS.replace(" ", "")
    # Three fixed-plus-fluid columns only from 1200px up; below that the rail takes its own row.
    grid = ".de-grid{display:grid;grid-template-columns:460pxminmax(0,1fr)340px"
    assert grid in CSS.replace(" ", "")
    assert "@media(max-width:1199px)" in CSS.replace(" ", "")
    # Header carries the product tagline from the B2 artboard.
    assert "reads the result back before it says done" in HTML


def test_receipt_facts_and_recap_tone():
    # Free-text recap labels must be allowed to wrap instead of forcing a max-content column.
    css = CSS.replace(" ", "")
    assert "de-facts{display:grid;grid-template-columns:fit-content(" in css
    assert "overflow-wrap:anywhere" in css.split("#dw-eveningdt{")[1].split("}")[0]
    # The verified check mark is keyed on the VERIFIED outcome only; recaps use their own tone.
    assert "tone = 'recap'" in JS
    assert "data-tone=recap" in css


def test_mic_interrupts_speech_instead_of_waiting_for_it():
    assert "get('mic').disabled = recognizing ? false : (busy || !Recognition);" in JS
    # The mic click no longer bails out while speaking.
    assert "controlBusy || ttsActive()) return;" not in JS
    assert "function stopSpeaking()" in JS
    assert "?v=2026-10-19c" in HTML


def test_wait_cue_claims_nothing_and_errors_are_spoken():
    assert 'const WAIT_PHRASE = "One moment, I\'m checking that.";' in JS
    assert "const WAIT_AFTER_MS = 1500;" in JS
    assert "function clearWait()" in JS
    for banned in ("done", "charged", "booked", "calendar", "confirmed"):
        assert banned not in "One moment, I'm checking that.".lower()
    assert "LIVE_ERROR = JSON.parse(e.data).message; note(LIVE_ERROR); speak(LIVE_ERROR);" in JS


def test_voice_choice_and_two_stage_endpointing():
    assert "function pickVoice()" in JS and "VOICE_PREFERENCE" in JS
    # A pause to think must not end the turn: 1.5 s after a final result, 2 s after an interim one.
    assert "const FINAL_SILENCE_MS = 1500, INTERIM_SILENCE_MS = 2000" in JS
    assert "const SILENCE_MS = 2000" not in JS
    assert "resetSilence(last && last.isFinal ? FINAL_SILENCE_MS : INTERIM_SILENCE_MS)" in JS


def test_mic_can_be_held_while_speaking():
    # Press and hold: no silence timer runs while held; release ends the turn.
    # A short tap keeps the hands-free behaviour.
    assert "MAX_RESTARTS = 5, HOLD_MS = 350" in JS
    assert "get('mic').addEventListener('pointerdown'" in JS
    assert "get('mic').addEventListener('pointerup'" in JS
    assert "if (holding) return;" in JS
    assert "function release() { holding = false; resetSilence(INTERIM_SILENCE_MS); }" in JS
    assert "get('mic').addEventListener('click'" not in JS


def test_sentences_split_only_at_punctuation_followed_by_space():
    assert "utterance.split(/(?<=[.!?][\"']?)\\s+/)" in JS  # "$12.50" stays one sentence


def test_wait_cue_never_speaks_over_a_phrase_of_the_same_turn():
    timer = (
        "waitTimer = setTimeout(() => { waitTimer = null; if (ttsActive()) return; "
        "waitSpoken = true; speak(WAIT_PHRASE, {interim: true}); }, WAIT_AFTER_MS);"
    )
    assert timer in JS
    assert "if (!replayed) { clearWait(); waitSpoken = true; speak(data.text); }" in JS
