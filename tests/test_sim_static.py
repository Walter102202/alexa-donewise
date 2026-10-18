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
