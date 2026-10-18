# Simulador DoneWise · sistema "Editorial plano" — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Llevar el front del simulador (`sim/static`) al sistema de diseño B2 "Editorial plano" elegido por Walter el 2026-10-18, con la estructura de tres columnas de la dirección B (sesión de voz · evidencia · riel de demo), sin tocar la lógica de `app.js`.

**Architecture:** `index.html` se reorganiza en tres columnas y conserva todos los `id="de-*"` y las clases que `app.js` crea o consulta; `styles.css` se reescribe entero sobre tokens nuevos (blanco puro, tinta #111, reglas de 1 px, radio 0, un solo azul cobalto). `app.js` no cambia. Un test de contrato estático garantiza que el HTML sigue exponiendo todo lo que el JS necesita.

**Tech Stack:** HTML + CSS estático servido por FastAPI (`sim/donewise_sim/app.py`), vanilla JS, pytest (`uv run pytest`), Playwright MCP para la verificación visual local.

**Spec:** artboard "B2 · Editorial plano" del canvas https://claude.ai/artifact/PVZFEUbJLnahFeTNoHAreg, copiado al repo en `design/mockups/B2-Editorial.dc.html` (Tarea 0). Tokens exactos en la sección siguiente.

## Global Constraints

- Solo LOCAL: nada se despliega ni se prueba en dev/AWS (regla Walter 2026-10-07). El simulador corre con `uv run donewise-sim` en modo fixture, sin modelo.
- `sim/static/app.js` no se modifica. Todo `id="de-…"` que consulta (`get('…')`) y toda clase que crea (`de-record`, `de-past`, `de-chapter`, `de-receipt-tab`, `de-audit-op`, `de-hist-list`, `de-small`) o consulta (`.de-director`) sigue existiendo.
- Tipografía: `Instrument Sans` 400/500/600 (texto) y `Red Hat Mono` 400/500 (ids, horas, log), vía un único `<link>` de Google Fonts. Se eliminan `Instrument Serif` e `IBM Plex Sans`.
- Tokens (del artboard B2, valores literales):
  - fondo `#FFFFFF` · riel de demo `#F7F7F7`
  - tinta `#111111` · apagado `#5C5C5C` · regla `#E4E4E4` · regla fuerte `#111111`
  - acento (solo accionable y "fault") `#1F3BFF`, hover `#0F23B8`
  - radio `0` en todo elemento; sin sombras; sin gradientes; sin bordes-izquierdos de color
  - etiquetas de sección: 11 px, `letter-spacing: .08em`, mayúsculas, peso 500, color apagado
  - escala: cuerpo 14–15 px / 1.45; título de recibo 30 px peso 500 `-0.02em`; valor 48 px peso 500 `-0.03em` tabular; monto en aprobación 44 px
  - header 64 px con `border-bottom: 1px solid #111111`; columnas `460px 1fr 340px` separadas por reglas de 1 px, sin `gap`
- Sin modo oscuro: `color-scheme: light`. (Decisión: B2 es papel blanco; el `light-dark()` actual se retira.)
- Accesibilidad como está hoy o mejor: objetivos ≥ 44 px, `focus-visible` visible (outline 2 px `#1F3BFF`, offset 3 px), contraste ≥ 4.5:1 (`#5C5C5C` sobre blanco cumple).
- No abrir PR ni borrar ramas; commits locales, uno por tarea.

## Review Focus

1. **Modo voz en vivo** (`LIVE.ui_mode === 'voice'`): `app.js` oculta `.de-director` y muestra `#de-session-controls` con el panel de fallos. Ambos viven en el riel: el riel no debe quedar vacío ni colapsar a 0 px. Test en Tarea 1 (ids presentes) + checklist visual en Tarea 4.
2. **Modo fixture sin servidor** (`LIVE = null`): `#de-preview-left` dice "Fixture mode · server not connected" y `#de-bottom` muestra el aviso. Deben seguir visibles y legibles en el nuevo layout. Checklist Tarea 4.
3. **Pantalla estrecha (390 px)**: tres columnas apilan a una; el input sigue usable; los botones de capítulo tienen ≥ 44 px. Tarea 3.
4. **Texto largo en celdas de recibo** (`dd` con ids `pi_…`, `op_…`): `overflow-wrap: anywhere` se conserva. Tarea 2 (CSS).
5. **Estados `hidden`**: `#dw-evening [hidden]{display:none!important}` debe seguir presente o los paneles ocultos por `app.js` aparecen. Test en Tarea 1.

---

### Task 0: Fijar la especificación en el repo

**Files:**
- Create: `design/mockups/B2-Editorial.dc.html` (copia literal del artboard)

- [ ] **Step 1: Copiar el artboard desde el scratchpad de la sesión del 2026-10-18**

```bash
cp "C:/Users/walte/AppData/Local/Temp/claude/C--dev-alexa-donewise/0c70dd42-a8c1-4880-9686-1e0679273bc3/scratchpad/redesign/project/B2-Editorial.dc.html" design/mockups/B2-Editorial.dc.html
```

Si la carpeta ya no existe: leerlo del canvas con el Artifact tool (`action: read`, `path: project/B2-Editorial.dc.html`) y guardarlo ahí.

- [ ] **Step 2: Commit**

```bash
git add design/mockups/B2-Editorial.dc.html
git commit -m "design(sim): add Editorial plano artboard as the UI spec"
```

---

### Task 1: Test de contrato entre `app.js` y el HTML/CSS estático

**Files:**
- Create: `tests/test_sim_static.py`

**Interfaces:**
- Produces: tres tests que las Tareas 2 y 3 deben dejar en verde.

- [ ] **Step 1: Escribir los tests**

```python
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "sim" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JS = (STATIC / "app.js").read_text(encoding="utf-8")


def test_every_id_app_js_reads_exists_in_index_html():
    wanted = set(re.findall(r"\bget\('([a-z-]+)'\)", JS)) | set(re.findall(r"\btext\('([a-z-]+)'", JS))
    missing = sorted(i for i in wanted if f'id="de-{i}"' not in HTML)
    assert missing == []


def test_every_class_app_js_creates_or_queries_is_styled():
    created = set(re.findall(r"el\('[a-z]+', '(de-[a-z-]+)'", JS)) | {"de-director"}
    assert all(f".{c}" in CSS for c in created), sorted(c for c in created if f".{c}" not in CSS)
    assert "[hidden]{display:none!important}" in CSS.replace(" ", "")


def test_editorial_plano_tokens_are_in_place():
    assert "family=Instrument+Sans" in HTML and "family=Red+Hat+Mono" in HTML
    assert "Instrument+Serif" not in HTML and "IBM+Plex" not in HTML
    assert "light-dark(" not in CSS
    assert re.findall(r"border-radius:\s*(?!0\b)[^;}]+", CSS) == []  # solo radio 0
    assert "#1F3BFF" in CSS.upper() and "#111111" in CSS.upper()
```

- [ ] **Step 2: Correr y verificar que falla solo el tercer test**

Run: `uv run pytest tests/test_sim_static.py -v`
Expected: los dos primeros PASS (el HTML actual ya es coherente con `app.js`); `test_editorial_plano_tokens_are_in_place` FAIL en la aserción de fuentes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sim_static.py
git commit -m "test(sim): static contract between app.js and the served UI"
```

---

### Task 2: Reestructurar `index.html` a tres columnas

**Files:**
- Modify: `sim/static/index.html`

**Interfaces:**
- Consumes: ids y clases listados en Global Constraints.
- Produces: nuevas clases de layout que la Tarea 3 estiliza: `de-rail`, `de-turn`, `de-turn-who`, `de-label`.

- [ ] **Step 1: Cambiar el `<link>` de fuentes**

`https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Red+Hat+Mono:wght@400;500&display=swap`

- [ ] **Step 2: Header**

Mantener `header.de-head` y `#de-model-label`, `#de-mode`, `#de-session-label`. Quitar `.de-mark` (el círculo con check); la marca es solo el texto "DoneWise". Partir el `.de-small` "Simulated Alexa+ experience · test mode · no real money" en dos `<span class="de-badge">`: `Simulated Alexa+` y `Test mode · no real money`. `#de-model-label` pasa a `class="de-badge de-badge-mono"`.

- [ ] **Step 3: Envolver riel y columnas**

Dentro de `#de-grid` quedan tres hijos directos, en este orden: `section.de-talk` (existe), `aside.de-side` (existe) y un nuevo `aside.de-rail aria-label="Demo controls"`. Mover dentro de `.de-rail`, sin cambiar su markup interno: `section#de-session-controls` y `footer.de-director`. `#de-grid` conserva `hidden` inicial (lo quita `app.js`).

Nota: `#de-loading`, `.de-preview` y `#de-bottom` quedan fuera del grid como hoy (`.de-preview` bajo el header, `#de-bottom` al final).

- [ ] **Step 4: Columna de conversación como turnos con etiqueta**

Envolver cada turno en `div.de-turn` con un primer hijo `span.de-turn-who` y el contenido existente después:
- `#de-gap` se mantiene como primer bloque, sin `de-turn`.
- `#de-user-wrap` → `de-turn`; su `<small>Clara</small>` pasa a ser el `span.de-turn-who` (texto "Clara"); `#de-user` queda.
- El bloque de respuesta → `de-turn` con `span.de-turn-who` "Alexa+"; dentro se conservan `.de-answer-label` (con `#de-voice`), `#de-answer`, `#de-approve-wrap`, `#de-source`.
- `.de-heading` (`#de-title`, `#de-time`, `#de-subtitle`) queda arriba como encabezado de la columna; `h2` se mantiene.
- Etiquetas de sección (`.de-answer-label`, `.de-side-label`, `.de-director-label`) reciben además la clase `de-label`.

- [ ] **Step 5: Verificar el contrato**

Run: `uv run pytest tests/test_sim_static.py -v -k "id or class"`
Expected: PASS en los dos tests.

- [ ] **Step 6: Commit**

```bash
git add sim/static/index.html
git commit -m "feat(sim): three-column layout with a demo rail, Editorial plano markup"
```

---

### Task 3: Reescribir `styles.css`

**Files:**
- Modify: `sim/static/styles.css` (reescritura completa; el comentario de cabecera pasa a citar `design/mockups/B2-Editorial.dc.html` y la fecha 2026-10-18)

**Interfaces:**
- Consumes: clases de la Tarea 2 y las que crea `app.js`.

- [ ] **Step 1: Base y tokens**

`#dw-evening{--de-bg:#FFFFFF;--de-rail:#F7F7F7;--de-ink:#111111;--de-muted:#5C5C5C;--de-line:#E4E4E4;--de-accent:#1F3BFF;--de-accent-hover:#0F23B8;font:400 14px/1.45 'Instrument Sans',system-ui,sans-serif;color-scheme:light;max-width:1440px;width:100%}`. `body{margin:0;background:#FFFFFF;display:grid;place-items:start center}`. Conservar los resets actuales (`*{box-sizing}`, `h2,h3,p{margin:0}`, `button{font:inherit}`, `svg` 16 px stroke, `[hidden]{display:none!important}`). `focus-visible`: `outline:2px solid var(--de-accent);outline-offset:3px`.

- [ ] **Step 2: Header, preview y badges**

`.de-head`: 64 px, `padding:0 32px`, `border-bottom:1px solid var(--de-ink)`. `.de-brand`: 20 px 600 `-0.02em`. `.de-badge`: 11 px mayúsculas `.08em` 500, `padding:6px 10px`, `border:1px solid var(--de-ink)`. `.de-badge-mono`: Red Hat Mono 12 px, sin mayúsculas, `border-color:#D6D6D6`, color apagado. `.de-mode`: mismo estilo que `.de-badge`; `[data-mode=connected]` usa `border-color:var(--de-accent);color:var(--de-accent)`. `.de-preview`: 12 px Red Hat Mono apagado, `padding:10px 32px`, `border-bottom:1px solid var(--de-line)`.

- [ ] **Step 3: Grid de tres columnas**

`.de-grid{display:grid;grid-template-columns:460px 1fr 340px}`. `.de-talk` y `.de-side`: `border-right:1px solid var(--de-line)`, `padding:18px 28px 20px` y `24px 32px`. `.de-rail{background:var(--de-rail);padding:18px 24px;display:flex;flex-direction:column;gap:16px}`. Dentro del riel, `.de-session-controls` y `.de-director` pierden fondo, bordes punteados y padding horizontal propio: `border-top:1px solid var(--de-line);padding:14px 0 0`.

- [ ] **Step 4: Conversación**

`.de-heading h2`: 22 px 500 `-0.02em` (ya no serif). `.de-clock`: Red Hat Mono 12 px apagado. `.de-turn{display:grid;grid-template-columns:72px 1fr;gap:16px;padding:14px 0;border-top:1px solid var(--de-line)}`. `.de-turn-who`: 11 px mayúsculas `.08em` apagado, `padding-top:3px`. `.de-user{all:unset-like}`: sin fondo ni radio, 15 px/1.5 (quitar `align-self`, `max-width`, `border-radius`). `.de-answer`: 15 px/1.5 peso 500. `.de-source`: 12 px apagado, **sin** `border-left`; `margin-top:10px`. `.de-gap`: `border:1px solid var(--de-accent);color:var(--de-accent);padding:10px 12px`, sin fondo. `.de-approve`: `background:var(--de-ink);color:#FFF;border:0;padding:0 16px;min-height:44px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;font-weight:500`. `.de-input input`: `border:0;border-bottom:1px solid var(--de-ink);background:transparent;padding:0 2px;font-size:15px`. `.de-mic`: 44×44 `background:var(--de-ink);color:#FFF;border:0`. `.de-send`: texto subrayado cobalto, `background:transparent;border:0`. `.de-voice`: 11 px mayúsculas, `border:1px solid var(--de-line)`; `[aria-pressed=true]` borde y texto en tinta. `.de-history summary`: color tinta, 12 px. `.de-past`: `border-top:1px solid var(--de-line);padding:10px 0`.

- [ ] **Step 5: Evidencia (recibo)**

`.de-receipt`: sin fondo, sombra, radio ni `:after` (se elimina el borde zigzag). `.de-receipt-tabs`: fila con `border-bottom:1px solid var(--de-line)`; `.de-receipt-tab`: 11 px mayúsculas `.08em` 500 apagado, `border:0;background:transparent;padding:0 0 12px;min-height:44px`; `[aria-pressed=true]`: tinta + `border-bottom:2px solid var(--de-ink);margin-bottom:-1px`. `#de-receipt-title` (`h3`): 30 px 500 `-0.02em`/1.1. `.de-value`: 48 px 500 `-0.03em`/1 tabular, `margin:18px 0 4px`. `.de-status`: 22 px 500 tinta, check de 22 px; `[data-tone=ok]` también tinta (el estado se dice con la palabra, no con color); el resto de tonos usan apagado. Quitar el `border-bottom:dashed`. `.de-fault-tag`: solo texto 11 px mayúsculas `.08em` 500 color acento, sin fondo. `.de-facts`: filas `grid-template-columns:1fr auto`, cada `dt`/`dd` con `padding:7px 0;border-top:1px solid var(--de-line)`; `dd` tinta, `overflow-wrap:anywhere`. `.de-evidence`, `.de-contrast`, `.de-audit`, `.de-saved`: `border-top:1px solid var(--de-line);padding-top:14px;margin-top:18px`, `h3` como `.de-label`. `.de-placeholder`: borde 1 px acento, texto acento, sin fondo. `.de-record`: fila con `border-top` regla. `.de-links a`: color acento, `text-decoration:underline;text-underline-offset:4px`.

- [ ] **Step 6: Riel de demo**

`.de-label`/`.de-director-label`: 11 px mayúsculas `.08em` 500 apagado. `.de-chapters`: columna (`flex-direction:column;gap:6px`). `.de-chapter`: `width:100%;text-align:left;border:1px solid #D6D6D6;background:#FFF;padding:10px 12px;min-height:44px;font-size:13px`; `[aria-pressed=true]`: `border-color:var(--de-ink);color:var(--de-ink)`; su `b` en Red Hat Mono 12 px acento. `.de-back`: igual que `.de-chapter` sin ancho completo. `.de-next`: `background:var(--de-ink);color:#FFF;border:0;min-height:44px;padding:0 16px;font-size:11px;letter-spacing:.08em;text-transform:uppercase`. `select`: `border:1px solid var(--de-ink);background:#FFF;min-height:44px;margin:4px 0 10px`. `#de-fault-state`, `.de-small`: 12 px apagado; dentro del riel, tiempos y `run_…` en Red Hat Mono. `.de-audit-op`, `.de-hist-list`: igual que hoy pero reglas `var(--de-line)` y `b` en Red Hat Mono.

- [ ] **Step 7: Responsive**

`@media(max-width:1100px)`: `.de-grid{grid-template-columns:1fr 1fr}` y `.de-rail{grid-column:1/-1;border-top:1px solid var(--de-line)}`; `.de-side{border-right:0}`. `@media(max-width:680px)`: una columna, `.de-talk,.de-side{border-right:0;border-bottom:1px solid var(--de-line);padding:18px 16px}`, `.de-head,.de-preview,.de-rail{padding-left:16px;padding-right:16px}`, `.de-head-right{width:100%}`, `.de-value{font-size:38px}`, `#de-receipt-title{font-size:24px}`, `.de-turn{grid-template-columns:1fr;gap:4px}`.

- [ ] **Step 8: Verificar**

Run: `uv run pytest tests/test_sim_static.py tests/test_sim.py -v`
Expected: todos PASS (incluido `test_editorial_plano_tokens_are_in_place`).

Run: `uv run ruff check .`
Expected: sin errores.

- [ ] **Step 9: Commit**

```bash
git add sim/static/styles.css
git commit -m "feat(sim): Editorial plano design system for the simulator UI"
```

---

### Task 4: Verificación visual local

**Files:** ninguno (solo evidencia en el scratchpad).

- [ ] **Step 1: Levantar el simulador en modo fixture, en local**

Run (fondo): `uv run donewise-sim`
Expected: `GET /` responde 200 en `http://127.0.0.1:8000/` (puerto según `Settings`; confirmar en la salida).

- [ ] **Step 2: Capturas con Playwright MCP a 1440×810 y 390×844**

Abrir `/`, esperar a que `#de-grid` pierda `hidden`, capturar. Luego pulsar "Continue" hasta el turno 2 (cobro recuperado) y capturar de nuevo. Guardar en `C:\Users\walte\AppData\Local\Temp\claude\C--dev-alexa-donewise\<sesión>\scratchpad\editorial-plano\`.

- [ ] **Step 3: Checklist contra `design/mockups/B2-Editorial.dc.html`**

- Header 64 px con regla negra; marca solo texto; badges rectangulares con borde.
- Tres columnas separadas por reglas de 1 px; riel gris `#F7F7F7` a la derecha con capítulos y Back/Continue.
- Turnos con etiqueta "Clara"/"Alexa+" en la columna de 72 px, sin burbujas ni fondos.
- Recibo sin tarjeta: título 30 px, valor 48 px, estado como palabra en tinta con check, hechos en filas con reglas.
- Botón de aprobación y micrófono en negro; input subrayado; enlaces en cobalto subrayados.
- Nada con radio, sombra, gradiente o borde-izquierdo de color.
- A 390 px: una columna, nada recortado horizontalmente, botones ≥ 44 px.
- Con el servidor apagado (modo fixture): `#de-preview-left` y `#de-bottom` legibles.

- [ ] **Step 4: Corregir desvíos en `styles.css` y repetir Steps 2–3 hasta cumplir el checklist; commit de cada corrección**

```bash
git add sim/static/styles.css sim/static/index.html
git commit -m "fix(sim): Editorial plano visual adjustments after local review"
```

- [ ] **Step 5: Reportar a Walter** con las dos capturas (1440 y 390) y la lista de desvíos aceptados, si los hay. No abrir PR: queda en `main` local hasta que él lo pida. Las capturas de `docs/screenshots` (README) vienen del modo conectado por Docker y no se regeneran en este plan.

---

## Fuera de alcance (decisiones explícitas)

- `app.js` no se toca; cualquier cambio de copy o de comportamiento va en otro plan.
- Modo oscuro retirado (ver Global Constraints).
- `docs/screenshots/*.png` y el video no se regeneran aquí.
- Los artboards A, B, C, B1 y B3 del canvas quedan como historial; solo B2 entra al repo.
