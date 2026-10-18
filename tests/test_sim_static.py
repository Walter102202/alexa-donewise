"""Static contract between sim/static/app.js and the served HTML/CSS (Editorial plano, 2026-10-18)."""

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
    unstyled = sorted(c for c in created if f".{c}" not in CSS)
    assert unstyled == []
    assert "[hidden]{display:none!important}" in CSS.replace(" ", "")


def test_editorial_plano_tokens_are_in_place():
    assert "family=Instrument+Sans" in HTML and "family=Red+Hat+Mono" in HTML
    assert "Instrument+Serif" not in HTML and "IBM+Plex" not in HTML
    assert "light-dark(" not in CSS
    assert re.findall(r"border-radius:\s*(?!0\b)[^;}]+", CSS) == []  # solo radio 0
    assert "#1F3BFF" in CSS.upper() and "#111111" in CSS.upper()
