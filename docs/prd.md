# PRD — Alexa-DoneWise

**Versión:** 1.3. **Fecha:** 17 de septiembre de 2026 (v1.0 borrador: 15-sep; v1.1 y v1.2: 16-sep). **Estado:** aprobado por Walter el 16-sep-2026; v1.2 incorpora la dirección visual de Codex y la historia recortada a 3 minutos; v1.3 ajusta el puente Alexa+ tras el spike documental (ver §14.2). Hosting pendiente (decisión 10). Construido al 17-sep: contratos, harness, servidor MCP, simulador con voz y modo guionado, evaluación determinista en sandbox; adaptadores reales en curso.
**Aprueba:** Walter. **Escribe:** Claude (sesión del 14 y 15-sep-2026).
**Qué es este documento:** los requisitos del producto que se entrega al track Alexa+ de la "Build, Ship, Shape: Amazon Developer Hackathon" 2026 (cierre **23-oct-2026 12:00 PT, 16:00 Chile**). Fija qué se construye, qué no, cómo se comporta, cómo se prueba y qué ve el jurado. No es el plan de implementación (está en `docs/analisis-y-plan.md` §7) ni el diseño técnico por módulo (se escribe al empezar cada uno).
**Documentos base:** `docs/analisis-y-plan.md` (hechos verificados, decisiones §8, estrategia §9), `docs/revision-critica-ganar.md` (riesgos y recomendaciones), `docs/archive/spec-v1-2026-09-14.md` (spec v1, contratos y casos T06–T16), `design/mockups/donewise-3min.html` (prototipo estático de la pantalla única y de la historia, en inglés; deriva de `design/mockups/donewise-evening.codex.html`, la propuesta visual de Codex aprobada por Walter el 16-sep-2026). `Main.dc.html` y los demás `*.dc.html` quedan como exploración previa.
**Nota de publicación:** `docs/analisis-y-plan.md`, `docs/revision-critica-ganar.md` y `docs/archive/` son documentos internos y no se publican en el repositorio; las referencias a sus secciones se conservan como cita.
**Prioridades:** **P0** = sin esto no se entrega. **P1** = sube nota; se hace si el hito del video se cumple. **P2** = stretch.

---

## 1. Una frase

**Alexa-DoneWise: the Alexa+ add-on that never says "done" unless it can prove it, and never does it twice.**

Es un servidor MCP (spec 2025-11-25, Streamable HTTP) que envuelve acciones con consecuencias (una cita en Google Calendar, un cobro en Stripe) en un harness de ejecución verificada: intención → autorización → idempotencia → ejecución → relectura → veredicto → recibo. La frase que oye el usuario sale del recibo, nunca del modelo. Se demuestra en una web que simula la experiencia Alexa+ (ruta explícitamente permitida por las bases) y, si entra el stretch, en el simulador oficial de Alexa Skills vía `alexa-skill-mcp-bridge`.

---

## 2. Objetivo y medida de éxito

| Objetivo | Medida |
| --- | --- |
| Top-3 del track Alexa+ (US$25k / 15k / 4k). | Pasar etapa 1; nota alta en los cuatro criterios de igual peso (Tech, Design, Impact, Idea) más el bonus de friction log (10 %). |
| Mini-challenge AWS Builder (US$5k + 5k créditos). | Simulador sobre Bedrock, documentado en README; AgentCore + Lambda si va el puente. |
| Mini-challenge Open Source (US$5k + 5k). | Harness publicado como librería independiente en la ventana del concurso. |
| Producto honesto. | Cero confirmaciones falsas y cero duplicados en la suite crítica (8); todo lo no probado se llama no probado. |

Estimación de la revisión crítica (15-sep-2026): ~10 % de top-3 con el plan actual; 20–25 % si el video existe el 2-oct, el README abre con un número y la Alexa del simulador habla nuestro resultado.

---

## 3. Usuarios y problema

**Usuario final (el de la historia):** alguien que delega por voz tareas con consecuencias, no solo consultas. Hoy no delega dinero a un asistente porque el asistente dice "done" sin comprobar y, ante un timeout, reintenta y duplica. Fuente documentada: falsas confirmaciones de asistentes (WIRED, mar-2026, citado en la spec v1).

**Desarrollador de add-ons (audiencia del harness):** quien construye tools MCP que escriben en sistemas externos y necesita, en pocas líneas, recibo verificado, idempotencia y claims permitidos. Es la audiencia "más allá de la hackathon" que pide el criterio Potential Impact.

**Jurado (cliente de la entrega):** decide con video < 3 min, README y repo. Necesita ver en pantalla que el check verde es real (Google Calendar y el dashboard de Stripe en modo test abiertos), un cliente MCP que no escribimos nosotros, y un número.

---

## 4. Alcance

### 4.1 Dentro (P0 salvo indicación)

- Servidor MCP propio en Python (SDK oficial), Streamable HTTP, versión negociada 2025-11-25 registrada.
- Seis tools: `calendar_create_verified`, `calendar_reschedule_verified`, `payment_charge_verified`, `operation_get`, `approval_grant`, `receipts_recap` (solo lectura). Recurso de solo lectura `receipts`.
- Harness con cuatro identidades, idempotencia por intención (`intent_id` estable + huella del payload), `PENDING` + `operation_get`, replay condicional seguro dentro de la ventana del proveedor, recuperación automática, registro append-only en SQLite (claims por inserción única, no por `UPDATE`).
- Adaptadores: `FakeCalendar`, `GoogleCalendar` (cuenta de servicio + calendario de prueba compartido), `FakePayments`, `StripeTest` (modo test, `Idempotency-Key`, relectura del PaymentIntent).
- Aprobación explícita para dinero, ligada a monto, moneda, destinatario e intención; consumida de forma durable por una sola operación; con caducidad hasta su consumo; concedida solo por el canal de consentimiento (token que el modelo no tiene).
- Simulador web "simulated Alexa+ experience": una pantalla (según `Main.dc.html`), voz de entrada y salida del navegador, agente LLM detrás de interfaz intercambiable (Bedrock por defecto), cliente MCP oficial, modo guionado sin claves, vista de recibo y auditoría, panel de fallos rotulado.
- Inyección de fallos por run, de un solo uso, fuera de MCP.
- Evaluación baseline vs harness con fallos inyectados; tabla en el README.
- Suite T06–T22 en CI con un cliente MCP real por HTTP.
- Entrega pública en inglés: repo MIT, README, video, product feedback, friction log, formulario Devpost.
- **P1:** demo alojada viva hasta el 20-nov-2026 (NF-07 es P1 con ella; hosting con disco persistente e instancia única, decisión 10); ruta rápida síncrona < 450 ms; ruta solo-voz documentada; segundo adaptador trivial en README; SKILL.md (Agent Skill).
- **P2:** puente `alexa-skill-mcp-bridge` (Alexa real en el simulador ASK); si el spike falla, tarjeta de recibo como MCP App en Claude Desktop; elicitation MCP para la aprobación en clientes que la soporten; **capítulo "una hora después"** de la propuesta de Codex (continuidad entre sesiones: mismo usuario, recuperar recibos y aprobaciones, lectura nueva comparada con la evidencia guardada). Prerrequisitos: tool de solo lectura `calendar_get_verified`, instrucción al modelo de consultar `receipts` antes de tratar una pregunta como orden, y registro por `user_id` (ya en RF-11). Solo en la demo alojada, nunca en el video, y solo después del video final.

### 4.2 Fuera (decidido; no se reabre sin Walter)

Tiempo, receta y música (14/15-sep-2026). Del prototipo de Codex (16-sep-2026): el dentista, el bloque "retirar paquete", la pregunta de desambiguación y el salto de una hora quedan fuera del video y del P0 (la desambiguación sigue cubierta por T13 como caso de prueba). Invitar asistentes al evento (una cuenta de servicio no puede sin Workspace). OAuth de usuario final y account linking real (solo documentación). MCP Toolkit, manifiesto real y certificación (acceso "select partners only"). PostgreSQL, worker en proceso aparte, cadena de hashes, estudio con personas, temporizador, hogar, compras, dinero real en cualquier entorno, tasks MCP del núcleo (SEP-1686), Amazon Polly (default propuesto en 12).

---

## 5. La demo: historia, pantalla y voz

### 5.1 Historia (una sola, 5 turnos de usuario, 6 estados, en inglés)

Persona: Clara, de noche en su cocina (`America/Los_Angeles`, decisión 11). Prototipo estático con los textos exactos: `design/mockups/donewise-3min.html`. Los fallos se inyectan a la vista, con rótulo. Recorte decidido por Walter el 16-sep-2026 sobre la historia de 14 escenas de Codex para que quepa en el video de 3 minutos: se conserva la reserva, la aprobación, el cobro con respuesta perdida, el cambio con acuse falso y un recap desde los recibos.

| Turno | Clara dice | Qué pasa por dentro | DoneWise responde (desde el recibo) | Estado |
| --- | --- | --- | --- | --- |
| 1 | "Book the plumber tomorrow nine to ten and pay the sixty-dollar deposit to Ridge Plumbing." | `calendar_create_verified` crea con ID propio, relee, compara → VERIFIED. `payment_charge_verified` sin aprobación → NEEDS_APPROVAL, nada en Stripe. Un turno, dos recibos; el `spoken` de ambos se concatena en orden (RF-33). | "It's on your calendar: Ridge Plumbing, tomorrow 9 to 10 AM. For the deposit: a $60 test charge for Ridge Plumbing. Should I charge it?" | VERIFIED + NEEDS_APPROVAL |
| 2 | "Yes, charge it." | El backend de sesión clasifica la afirmación contra la petición pendiente y concede la aprobación con `consent_token` (RF-24). **Fallo inyectado: respuesta perdida después del cobro.** `PENDING` en < 500 ms. | "I'm on it. I'll confirm in a moment." + banner "Fault injected: response dropped after the charge" | PENDING |
| 2b | — (mismo turno, unos segundos después; el agente consulta `operation_get` solo, RF-34) | Replay con la misma `Idempotency-Key` devuelve el mismo PaymentIntent; relectura por ID: `succeeded`, US$60, un solo cargo con este `intent_id`. | "Done: a $60 test charge is recorded for Ridge Plumbing's deposit, charged once. Confirmation pi_…. You don't need to try again." + "charges applied: 1" + bloque de contraste (RF-46) | VERIFIED |
| 3 | "I'm running late. Move the plumber to ten." | **Fallo inyectado: acuse favorable sin escritura, vigente durante dos intentos.** Intento 1: 3 lecturas en 5 s, sigue a las 9. Replay automático con `If-Match` (RF-15/16): mismo acuse falso, sigue a las 9. Presupuesto agotado. | "I couldn't confirm the change. I tried twice; the latest calendar check still shows 9 AM." + "2 attempts · 1 automatic · 0 writes observed" | NOT_OBSERVED |
| 4 | "Try that again." | Misma intención (`retry_of_operation_id`), objetivo absoluto 10:00–11:00, `If-Match` con la versión actual; el fallo ya expiró; relectura coincide. | "The plumber is now at 10 to 11 AM. I read it back from your calendar." + "read back at 7:44:03 PM · one write" | VERIFIED |
| 5 | "Recap tomorrow. And what did you charge?" | `receipts_recap` (solo lectura): lista los recibos del run y compone el `spoken` por plantilla con la hora de observación de cada uno. No lee el calendario ni Stripe de nuevo; no escribe. | "From the receipts in this conversation: the plumber is at 10 to 11 AM, read back at 7:44 PM. One $60 test charge for the deposit, read back at 7:40 PM. Nothing new was written." | — (recap) |

Cierre del video (no es un turno): recibo abierto, handshake 2025-11-25, cliente ajeno, tabla baseline.

En el estado 2b la pantalla muestra el contraste "Same fault, same model, without DoneWise": lo que dijo el baseline y lo que muestra el dashboard de Stripe en esa corrida (en la ejecución esperada, "Done! Your $60 deposit is paid." y US$120). Ese bloque se alimenta de una corrida real de la evaluación (6.9), rotulada con su ID; nunca se escribe a mano. Si ninguna corrida baseline duplica, el bloque muestra el resultado observado y el video usa el guion alternativo de 9.1.

**Qué prueba cada frase (y qué no):** el evento en el calendario prueba que existe en el calendario del usuario, no que Ridge Plumbing haya aceptado la reserva; el cargo en Stripe test prueba que existe un PaymentIntent `succeeded` de US$60 con ese concepto, no que un destinatario haya recibido fondos (no hay cuentas conectadas ni Stripe Connect). Ridge Plumbing es un proveedor simulado y así se rotula. Las frases habladas se limitan a lo verificado. El recap repite resultados verificados con su hora; nunca se presenta como una lectura nueva.

### 5.2 Pantalla (P0)

**Dirección visual:** la propuesta de Codex aprobada por Walter el 16-sep-2026 (`design/mockups/donewise-evening.codex.html`), tal como la reproduce `donewise-3min.html`: paleta marfil y verde petróleo con modo oscuro por `light-dark()`, tipografía Instrument Serif para títulos e IBM Plex Sans para el resto (Google Fonts), conversación a la izquierda, comprobante a la derecha con un valor grande, estado, hechos y "where this answer comes from" desplegable, y el registro de tareas debajo. **Adaptación a móvil** obligatoria (una columna bajo 680 px, controles de 44 px). Se conserva sin rediseñar; lo que falta se integra dentro de ese lenguaje.

**Elementos que la implementación agrega a esa dirección (todos del PRD, ninguno nuevo):**
- Rótulo permanente en la cabecera: "Simulated Alexa+ experience · Real MCP server · Stripe test mode", más el badge de modo `sandbox` / `connected` (RF-36). Sin logos de Amazon ni sonido de activación.
- Banner de fallo inyectado en la conversación (ya existe en el prototipo como banda ámbar): `off` / `drop response after write` / `ack without write`, con el rótulo persistente también en el recibo (RF-41).
- Contador **charges applied** / **writes applied** como valor grande del comprobante en los estados de cobro y de cambio (así lo hace el prototipo en 2b).
- Bloque de contraste "Same fault, same model, without DoneWise" en el estado 2b (en el prototipo va como fila del comprobante; en la implementación es una tarjeta bajo el comprobante, alimentada por RF-46).
- Campo de texto siempre visible y botón de micrófono al pie de la conversación (RF-31); botón "Approve $60 for Ridge Plumbing" junto a la petición de aprobación (RF-24).
- Enlaces "Receipt" (exportar JSON sanitizado) y "Audit" (vista de auditoría con sesión MCP y versión negociada, RF-38).
- En modo conectado, la grabación muestra además Google Calendar y el dashboard de Stripe (test) en pestañas aparte.

**Controles de la demo, separados del producto:** una barra al pie, rotulada "Demo controls · not part of the product", con capítulos y Back / Continue. En la implementación, "Continue" envía la siguiente **entrada** guionada por el cliente MCP (RF-35); todos los estados, horas y comprobantes salen de recibos persistidos y verificados. Nunca se avanza una escena ni se espera un temporizador para mostrar un estado. La barra no existe en modo voz libre.

**Dependencias del frontend:** HTML/CSS/JS plano por defecto (RF-39b, Next.js prohibido); iconos como SVG inline; fuentes de Google Fonts; sin bundler.

### 5.3 Ruta solo-voz (P1; frase por estado, la misma que muestra la pantalla)

| Estado | Frase (plantilla; se rellena solo desde el recibo) |
| --- | --- |
| VERIFIED (crear) | "It's on your calendar: {title}, {day} {start} to {end}." Nunca "{payee} is booked": no se verifica al proveedor. Turno 1 de 5.1: se concatena con la frase NEEDS_APPROVAL del segundo recibo. |
| VERIFIED (mover) | "{title} is now at {start} to {end}. I read it back from your calendar." (5.1 turno 4 usa `title` = "The plumber", el nombre corto del evento que fija el guion.) |
| VERIFIED (cobro) | "Done: a {amount} test charge is recorded for {payee}'s {concept}, charged once. Confirmation {payment_intent_id}." Si `reason_code = WRITE_RESPONSE_LOST_RECOVERED` se añade " You don't need to try again." Nunca "paid to {payee}": no se verifica la recepción de fondos. |
| VERIFIED histórico (relectura vieja) | "I checked at {observed_at}; the calendar shows {start} to {end}." Nunca "it's already at…" sin la hora. |
| PENDING | "I'm on it. I'll confirm in a moment." En un dispositivo sin seguimiento: "Ask me 'did it go through?' if you don't hear back." |
| NEEDS_APPROVAL | "For the {concept}: a {amount} test charge for {payee}. Should I charge it?" |
| NEEDS_INPUT | Una pregunta concreta: "Which one, the plumber or the dentist?" |
| NOT_OBSERVED | "I couldn't confirm the change. I tried {attempts_word}; the latest calendar check still shows {observed_start}." (`attempts_word`: "once", "twice", "{n} times".) |
| UNKNOWN | "I couldn't check the result yet. Nothing is confirmed. I'll keep checking." |
| REJECTED (sin aprobación) | "I won't charge anything without your OK." |
| REJECTED (aprobación no coincide) | "That's a different amount. I need a new OK for {amount}." |
| Conflicto de versión (412) | "Your calendar changed since I last looked. It now shows {observed}. Still move it to {target}?" |
| Recap (`receipts_recap`) | "From the receipts in this conversation: {items}. Nothing new was written." Cada item: calendario "the {title_short} is at {start} to {end}, read back at {observed_at}"; pago "one {amount} test charge for the {concept}, read back at {observed_at}". |

Estado vs. causalidad: "moved" o "paid" solo con evidencia del intento propio; con solo la lectura, "the calendar now shows…".

**Regla (16-sep-2026, tras la revisión de Codex del paso 0):** las plantillas de esta tabla son las que generan, palabra por palabra, las frases de 5.1. Si una frase de 5.1 y una plantilla difieren, se corrige la plantilla; 5.1 es la historia aprobada. `render_spoken` es la única fuente de lo que se oye; no hay frases escritas a mano en el simulador.

---

## 6. Requisitos funcionales

### 6.1 Servidor MCP (P0)

- RF-01. Endpoint único `/mcp` con POST y GET (SSE opcional), SDK oficial de Python, transporte Streamable HTTP según 2025-11-25.
- RF-02. Negocia y registra la versión de protocolo; los tests afirman `2025-11-25`. `MCP-Protocol-Version` inválido → 400; sin header → 2025-03-26 asumido según spec.
- RF-03. `MCP-Session-Id` asignado en `InitializeResult`; DELETE termina la sesión; 404 si fue cerrada. El estado por operación **no** vive en la sesión MCP: vive en el registro con identidad autenticada.
- RF-04. Seguridad de transporte: valida `Origin` (403 si no coincide), bind `127.0.0.1` en local, bearer estático por conexión en despliegue.
- RF-05. Toda tool declara `inputSchema` y `outputSchema`; toda respuesta trae `structuredContent` conforme y el mismo JSON serializado como `TextContent`, precedido por la frase `spoken`. Texto y `structuredContent` nunca se contradicen.
- RF-06. `isError: true` solo para fallas de ejecución: entrada inválida, no autorizado, adaptador inalcanzable **antes** de cualquier escritura, registro caído **antes** de persistir la intención. `NOT_OBSERVED`, `UNKNOWN`, `REJECTED`, `NEEDS_*` y `PENDING` son resultados de negocio con `isError: false`.
- RF-07. No se publican por MCP: parches crudos, alteración de evidencia, inyección de fallos.
- RF-08. Recurso `receipts` de solo lectura (lista y detalle por `operation_id`), sanitizado. **P2:** `ui://receipt` con `_meta.ui.resourceUri` (MCP Apps).
- RF-09. Interoperabilidad probada con MCP Inspector y con Claude Code o Claude Desktop; trazas guardadas en `docs/traces/`.

### 6.2 Contratos de tools (P0)

**Salida estándar** de toda tool de escritura y de `operation_get`:

```json
{
  "operation_id": "op_…", "intent_id": "int_…", "attempt_id": "att_…",
  "outcome": "VERIFIED | PENDING | NEEDS_APPROVAL | NEEDS_INPUT | NOT_OBSERVED | UNKNOWN | REJECTED",
  "expected": { "…": "objetivo autorizado, absoluto" },
  "observed": { "…": "última lectura válida" } ,
  "evidence": { "evidence_id": "ev_…", "source": "google_calendar | stripe_test | fake_*", "observed_at": "RFC3339", "version": "etag o null" },
  "reason_code": "POSTCONDITION_MISMATCH | READ_TIMEOUT | WRITE_RESPONSE_LOST_RECOVERED | REPLAY_BUDGET_EXHAUSTED | REPLAY_WINDOW_EXPIRED | RECONCILIATION_EXPIRED | VERSION_CONFLICT | NO_APPROVAL | APPROVAL_MISMATCH | APPROVAL_USED | APPROVAL_EXPIRED | IDEMPOTENCY_PAYLOAD_MISMATCH | AMBIGUOUS_TARGET | UNAUTHORIZED | REGISTRY_UNAVAILABLE | null",
  "allowed_claims": ["EFFECT_VERIFIED | LATEST_READ_MATCHES_TARGET | LATEST_READ_DIFFERS_FROM_TARGET | EFFECT_UNVERIFIED | CHARGED_ONCE | NOTHING_CHARGED | OPERATION_IN_PROGRESS | APPROVAL_REQUIRED"],
  "may_claim_success": false,
  "next_action": "NONE | CHECK_EXISTING_OPERATION | ASK_USER | GRANT_APPROVAL",
  "writes_applied": 0,
  "automatic_retries": 0,
  "spoken": "frase construida por plantilla desde este mismo recibo",
  "receipt_id": "rcpt_… | null"
}
```

`may_claim_success` y `allowed_claims` los calcula código de política; nunca se aceptan de un argumento. `PARTIAL` y `CANCELLED` quedan reservados y fuera de alcance (no hay peticiones compuestas ni cancelación).

| Tool | Entrada | Precondiciones | Efecto y observación | Extra en salida |
| --- | --- | --- | --- | --- |
| `calendar_create_verified` | `submission_id`, `title`, `start`, `end` (RFC3339), `timezone`, `notes?` | Sesión válida; `end > start`; dentro de 12 meses. | Persiste `event_id` propio **antes** de enviar; `events.insert` con ese ID; relee con `events.get` como consulta nueva; compara calendario, ID, estado no cancelado, inicio, fin y zona; guarda ETag y hora. Replay tras respuesta perdida: mismo ID; 409 "ya existe" cuenta como evidencia de escritura previa → releer. | `event_id`, `writes_applied` |
| `calendar_reschedule_verified` | `submission_id`, `event_id?` o `event_query?`, `new_start`, `new_end`, `timezone`, `retry_of_operation_id?` | Sesión válida; objetivo resuelto a un único evento (si no → `NEEDS_INPUT`); objetivo absoluto (nunca "sumar 30 min"). | Lee el evento y su ETag; `events.patch` con `If-Match`; 412 → releer, `VERSION_CONFLICT`, `ASK_USER`; relectura y comparación como arriba. | `event_id`, `writes_applied`, `previous` |
| `payment_charge_verified` | `submission_id`, `amount_minor`, `currency`, `payee`, `concept`, `approval_id?`, `retry_of_operation_id?` | Sesión válida; **modo test siempre**; sin `approval_id` válido → `NEEDS_APPROVAL` y nada se envía; aprobación ligada a monto, moneda, destinatario e intención; no consumida por otra operación; no caducada al consumirla (RF-23). | PaymentIntent (`confirm: true`, método de prueba `pm_card_visa`, `metadata.intent_id`, `description = concept · payee`) con header `Idempotency-Key = clave de intención`; relectura por `GET /v1/payment_intents/{id}` como consulta nueva; conteo de cargos con `metadata.intent_id` por listado (no por Search API, que indexa con retraso). Replay tras respuesta perdida: misma clave → Stripe devuelve el mismo objeto; no hay segundo cargo. | `payment_intent_id`, `charges_applied`, `approval_id` |
| `operation_get` | `operation_id` | — | Solo lectura del registro: estado actual, intentos, observaciones, veredictos. **No inicia escrituras.** Devuelve la operación aunque esté `UNKNOWN`; eso no es un efecto. | `history[]` |
| `receipts_recap` | `run_id?` | — | Solo lectura del registro: últimos recibos por operación del run (o del usuario autenticado). **No lee proveedores ni escribe.** Compone `spoken` por plantilla con la hora de observación de cada recibo. | `items[]` (operation_id, action, outcome, observed_at, summary) |
| `approval_grant` | `approval_request_id`, `consent_token` | Petición de aprobación existente, no caducada (TTL 5 min), no usada. `consent_token` válido para esta sesión (RF-24); sin él → `isError: true`, `UNAUTHORIZED`. | Crea la aprobación ligada a (intent_id, monto, moneda, destinatario). Registra `granted_by`: `session_ui` (web, tras botón o "sí" del usuario) o `mcp_client` (cliente externo con su propio token). | `approval_id`, `expires_at`, `bound_to` |

Descripciones de tools: estables desde el inicio (Alexa+ las bloquea al certificar) y con instrucción explícita al modelo: leer `may_claim_success` y `spoken`, no reintentar por su cuenta, usar `operation_get` cuando `next_action = CHECK_EXISTING_OPERATION`.

### 6.3 Harness (P0)

- RF-10. **Cuatro identidades.** `submission_id` del frontend (sobrevive reintentos de red), `intent_id` durable emitido por el backend, `operation_id`, `attempt_id`.
- RF-11. **Idempotencia por intención.** Dos cosas separadas: (a) la **identidad estable de la intención**, `intent_id`, que el backend emite la primera vez que ve un `submission_id` de un usuario y guarda en una tabla con restricción única (`user_id`, `submission_id`) → `intent_id`; cualquier reenvío con el mismo `submission_id` recupera el mismo `intent_id`, y `retry_of_operation_id` recupera el `intent_id` de esa operación; (b) la **huella del payload**, hash(acción, objetivo normalizado, payload normalizado), guardada junto a la intención. Mismo `intent_id` con huella distinta → `REJECTED / IDEMPOTENCY_PAYLOAD_MISMATCH`. Dos pagos legítimos con el mismo payload y distinto `submission_id` son dos intenciones: no se deduplican. La clave que va al proveedor (`Idempotency-Key`, `event_id`) deriva del `intent_id`, no del payload. "Try again" referencia `retry_of_operation_id` y retoma la misma operación; "move it another thirty minutes" es una intención nueva con base explícita. Unicidad y exclusión entre workers en la base de datos: el claim de una operación es un `INSERT` en `claims` con restricción única (`operation_id`), el que falla pierde; sin `UPDATE` ni locks en memoria.
- RF-12. **Orden de persistencia.** Intención y `operation_id` antes de actuar; cada intento con su resultado; observación y veredicto antes de habilitar la confirmación. Sin registro no hay recibo de éxito.
- RF-13. **Presupuesto de latencia.** Lecturas síncronas < 500 ms. Escrituras: si la verificación completa cabe en 450 ms, respuesta síncrona (P1, ver 12); si no, `PENDING` en < 500 ms tras persistir, verificación en background en el mismo proceso, consulta por `operation_get`. Plazo de fondo 15 s; vencido, `UNKNOWN`.
- RF-14. **Observación.** Ventana 5 s, hasta 3 lecturas, espaciadas; la observación evaluada empieza después del intento evaluado; una evidencia tardía de un intento anterior no reemplaza un veredicto más nuevo.
- RF-15. **Replay seguro, máximo uno por operación.** Solo con el mismo ID (evento o clave de idempotencia), objetivo absoluto, `If-Match` de la precondición original **y dentro de la ventana de deduplicación del proveedor** (`replay_is_safe(op)` la devuelve; Stripe: 24 h desde la primera petición, con margen de 1 h; Google: mientras el `event_id` propio exista o el `insert` responda 409). `NOT_OBSERVED` no prueba que no haya escritura en vuelo: si el replay recibe 412, se relee y se resuelve. Fuera de la ventana está prohibido reenviar: se conserva `UNKNOWN` y se reconcilia solo por lectura (RF-17b).
- RF-16. **Recuperación automática cuando es segura.** Si el replay condicional es seguro, el harness lo ejecuta sin pedir "try again", en calendario y en pago por igual (paso 4 y primer replay del paso 5). El turno del usuario se reserva para ambigüedad, cambios externos (412), replay no seguro o **presupuesto de replay agotado** (paso 5: el fallo dura dos intentos, el replay automático también falla, el recibo dice `NOT_OBSERVED` con `automatic_retries = 1`; el "try again" del paso 6 abre un intento nuevo sobre la misma intención). Pedir al usuario que reintente nunca sustituye una garantía del adaptador.
- RF-17. **Recuperación por punto de caída** (tabla de `docs/analisis-y-plan.md` §6.6): antes de persistir → se acepta de nuevo; intención guardada sin envío → reclamar y revalidar; envío sin respuesta → marcar incertidumbre y consultar el objeto estable; efecto aplicado sin evidencia → releer y persistir; evidencia guardada sin voz → reenviar el recibo, no la acción; estado cambia después → conservar la historia. Al reiniciar, las operaciones inconclusas se retoman aplicando RF-15: replay solo si sigue siendo seguro; si no, solo lectura.
- RF-17b. **Reconciliación de `UNKNOWN`.** Dueño: el reconciliador del servidor, que corre al arrancar y en cada `operation_get` de una operación `UNKNOWN`, y en background cada 30 s mientras haya operaciones `UNKNOWN` de menos de 24 h. Solo lee: `events.get` por `event_id` propio; `GET /v1/payment_intents` filtrado por `metadata.intent_id`. Cierre: `VERIFIED` o `NOT_OBSERVED` con la evidencia leída; si a las 24 h de la primera petición no hay lectura válida, la operación queda `UNKNOWN` final con `reason_code: RECONCILIATION_EXPIRED` y `next_action: ASK_USER`; nunca se reenvía.
- RF-18. **Veredicto.** Compara actor, calendario/cuenta, objeto, estado no cancelado, inicio y fin semánticos, zona (calendario) o estado, monto, moneda, destinatario (pago). Registra regla aplicada, campos comparados y motivo de no confirmar.
- RF-19. **Un solo presentador.** Texto, tarjeta, historial y voz salen del recibo persistido. Ni el aviso de progreso, ni una tarjeta optimista, ni un resumen del modelo pueden decir "done", "paid", "moved".
- RF-20. **Harness agnóstico.** Un adaptador implementa `write(op)`, `read(ref)`, `replay_is_safe(op)`; el harness no conoce Google ni Stripe. **P1:** segundo adaptador trivial (≈30 líneas, por ejemplo `FakeTodo`) solo en el README.
- RF-21. **Librería.** `core/` se publica como paquete independiente (`donewise-harness`, MIT) durante la ventana del concurso (mini-challenge Open Source).

### 6.4 Aprobación de dinero (P0)

- RF-22. Ninguna tool con dinero ejecuta sin aprobación válida. Sin aprobación → `NEEDS_APPROVAL` con `approval_request` {id, monto, moneda, destinatario, concepto, `expires_at`}; nada persistido en Stripe.
- RF-23. La aprobación se liga por hash a (intent_id, monto, moneda, destinatario) y **autoriza una operación de forma durable**. Consumo atómico: `INSERT` en `approval_uses` con restricción única (`approval_id`) junto con la creación de la operación, en la misma transacción; la operación queda ligada al `approval_id`. Reglas: un `approval_id` de US$60 usado para US$90 → `REJECTED / APPROVAL_MISMATCH`; reenviar la **misma operación** (mismo `submission_id` o `retry_of_operation_id`, T11, paso 4) no reconsume la aprobación y devuelve el estado de la operación; usar la aprobación para **otra operación** → `REJECTED / APPROVAL_USED`. Caducidad: 5 minutos desde la concesión hasta el consumo; una vez consumida, la caducidad no afecta al replay ni a la reconciliación de esa operación. Aprobación caducada sin consumir → `REJECTED / APPROVAL_EXPIRED`.
- RF-24. **La aprobación exige una capacidad que el modelo no tiene.** `approval_grant` requiere `consent_token`: un secreto por sesión que el servidor MCP entrega al canal de consentimiento (el backend de sesión de la web, fuera del loop del modelo) y que nunca aparece en `tools/list`, en resultados de tools ni en el contexto del modelo. En la web, la concesión la hace el backend de la sesión tras el botón "Approve $60 for Ridge Plumbing" o una afirmación del usuario clasificada de forma determinista contra la petición pendiente; además, la lista de tools que ve el modelo en el simulador es `tools/list` **menos** `approval_grant` (RF-32). Si el modelo llama `approval_grant` de todas formas, falla con `UNAUTHORIZED` y queda en el recibo. En clientes externos, el operador del cliente configura el `consent_token` fuera del modelo; `granted_by: mcp_client` y el recibo lo muestra. Con clientes que declaran `elicitation`, la aprobación se pide por elicitation (monto y destinatario fijos; accept/decline; `granted_by: elicitation`): **P1 para la integración con el puente Alexa+ (RF-48)**, porque el puente no puede guardar un `consent_token` por sesión fuera del modelo; P2 para el resto de clientes.
- RF-25. Límite declarado en README y product feedback: en un cliente externo, si el operador expone el `consent_token` al modelo (configuración incorrecta), el modelo podría conceder aprobaciones; la unión monto/destinatario sigue impidiendo cobros distintos. Propuesta a Amazon: primitiva de consentimiento para add-ons (elicitation con campos fijos).

### 6.5 Adaptadores (P0)

| Adaptador | Qué es | Hooks de fallo | Notas |
| --- | --- | --- | --- |
| `FakeCalendar` | Estado en archivo JSON (sobrevive el reinicio del proceso, T11 y T21), ETag propio, IDs propios, almacenamiento independiente para relectura. | `ack_without_write`, `drop_response_after_write`, `read_unavailable`, `concurrent_edit`. | Modo sandbox y CI. |
| `GoogleCalendar` | Cuenta de servicio con calendario de prueba compartido (permiso de edición). | Vía proxy de inyección de fallos (6.8). | Verificar en semana 2: acepta `id` propio en `insert`; `If-Match` en `patch`; medir p50/p95. Calendario público en solo lectura para el jurado. |
| `FakePayments` | Estado en archivo JSON, `Idempotency-Key` con ventana configurable (por defecto 24 h, reducible en tests para T08/RF-15), PaymentIntents simulados. | Los mismos cuatro hooks. | Modo sandbox y CI. |
| `StripeTest` | Stripe modo test (claves `sk_test_`), `pm_card_visa`, metadata. | Vía proxy. | Rótulo "test mode · no real money" en toda superficie; una clave live en la config aborta el arranque. Claves de idempotencia válidas 24 h en Stripe; `replay_is_safe` devuelve falso pasadas 23 h desde la primera petición. |

### 6.6 Recibos y registro (P0)

- RF-26. SQLite append-only con tablas `intents`, `operations`, `attempts`, `observations`, `verdicts`, `receipts`, `approvals`, `approval_uses`, `claims`, `faults`, `runs`. Solo `INSERT`; el estado actual de una operación se deriva de la última fila de cada tabla; los claims y consumos son inserciones con restricción única (RF-11, RF-23). Marcas de tiempo del servidor; tiempo monotónico para duraciones. El archivo SQLite vive en disco persistente (NF-04); un hosting sin disco persistente no es válido (decisión 10).
- RF-27. Recibo normalizado (`schema_version`, `operation_id`, `action`, `outcome`, `expected`, `observed`, `evidence`, `reason_code`, `allowed_claims`, `may_claim_success`, `writes_applied`, `spoken`, `observed_at`). Exportable como JSON sanitizado (sin tokens, correos, IDs de cuenta ni contenido ajeno).
- RF-28. `UNKNOWN` se resuelve con una observación posterior añadiendo registros; nunca se borra ni edita lo anterior.
- RF-29. Registro caído antes de persistir la intención → `isError: true`, nada ejecutado (T16). Registro caído después de la escritura → `UNKNOWN`, `receipt_id: null`, reconciliación al recuperar; nunca recibo de éxito sin registro.
- RF-30. Retención en la demo alojada: trazas sanitizadas 30 días; audio nunca almacenado.

### 6.7 Simulador web (P0)

- RF-31. Entrada: Web Speech API (`SpeechRecognition`, Chrome, localhost o HTTPS) y campo de texto siempre visible. Salida: `speechSynthesis` del navegador.
- RF-32. Agente: loop de tool-use en el backend (FastAPI). LLM detrás de una interfaz; por defecto Amazon Bedrock (Claude), alternativa API Anthropic directa; el núcleo no depende del proveedor. Tools: las de `tools/list` del servidor, obtenidas por el cliente MCP oficial sobre Streamable HTTP, **menos `approval_grant`**, que solo llama el backend de sesión con el `consent_token` (RF-24). Nunca llamada directa a adaptadores.
- RF-33. Tras una tool de escritura, `operation_get` o `receipts_recap`, el turno del asistente es `spoken` del recibo; si en un turno hubo varias tools, se concatenan sus `spoken` en orden (turno 1: calendario + petición de aprobación). El modelo no redacta ese turno. El modelo redacta solo conversación, preguntas de desambiguación y contenido sin efecto; un resumen de lo hecho nunca lo redacta el modelo, sale de `receipts_recap`.
- RF-34. Con `PENDING`, el agente consulta `operation_get` por su cuenta (intervalo 1 s, tope 15 s) y presenta el recibo final; el usuario no tiene que preguntar.
- RF-35. Modo guionado: fija las **entradas** de los 7 pasos y las envía por el mismo cliente MCP sin LLM; harness, adaptadores y verificación corren de verdad; nunca se guionan salidas. Es el modo del jurado sin claves, de CI y del respaldo del video. Se construye en la semana 2 (antes del 2-oct), porque el video de ensayo depende de él (§10).
- RF-36. Dos modos de entorno: `sandbox` (Fake*, sin claves) y `connected` (Google + Stripe test). El banner muestra el modo.
- RF-37. Runs aislados: cada sesión de demo tiene `run_id`; los objetos creados llevan el `run_id` en metadata; el reset borra solo los de ese run.
- RF-38. Vista de auditoría: línea temporal por operación leída del registro (intentos, observaciones, veredicto, replay), exportación del recibo, sesión MCP (versión negociada, `MCP-Session-Id`).
- RF-39. Identidad visual según 5.2 (dirección de Codex, sin rediseñar). Copy en inglés. Adaptación a móvil: una columna bajo 680 px, controles de 44 px, sin scroll horizontal. Controles de la demo separados y rotulados.
- RF-39b. **Next.js prohibido** (decisión de Walter, 16-sep-2026; corrige una versión anterior que decía "sin React"). Por defecto el frontend es HTML, CSS y JavaScript sin build step, servido como archivos estáticos por FastAPI, porque el prototipo aprobado (`donewise-3min.html`) ya es HTML plano y se porta tal cual. React está permitido si hace falta (sin Next.js); si se usa, sin servidor Node propio: el backend sigue siendo FastAPI. El bundle TS de la MCP App (RF-49, P2) es un artefacto aparte.

### 6.8 Inyección de fallos (P0)

- RF-40. Ruta admin fuera de MCP (`/admin/faults`), solo con token de demo; deshabilitada sin él.
- RF-41. Fallos por run, de un solo uso, con etiqueta persistente en pantalla y en el recibo (`fault_injected`): `drop_response_after_write`, `ack_without_write`, `read_unavailable`, `concurrent_edit`, `registry_down`. Nunca un fallo global del servicio.
- RF-42. En modo conectado los fallos se aplican en un proxy local entre adaptador y proveedor (corta la respuesta, devuelve acuse falso, bloquea lecturas); Google y Stripe nunca reciben tráfico alterado.

### 6.9 Evaluación (P0)

- RF-43. Matriz determinista sin LLM: 10 escenarios × fallos inyectados, contra Fake* y contra Google + Stripe test; produce el número principal (confirmaciones falsas, duplicados).
- RF-44. Pasada LLM: mismo modelo, mismas tools, dos variantes: **baseline** (tools de escritura directa sin harness: verificadores disponibles pero opcionales, y `Idempotency-Key` nueva por llamada, que es lo que hace un cliente sin identidad de intención) vs **DoneWise**. 10 escenarios × 1 ejecución (default de la decisión 9; ×3 si sobra tiempo en la semana 4). El README declara qué mide la comparación: el harness completo (identidad de intención + verificación + presentación desde el recibo) frente a la escritura directa, no el verificador aislado. Métricas: confirmaciones falsas, cargos duplicados, eventos duplicados, tareas completadas, turnos, tiempo hasta resultado verificado (p50/p95).
- RF-45. Resultados en `evals/results/` con denominadores y comandos de reproducción; tabla en la primera pantalla del README. "Cero en muestra finita no es nunca" se dice en el README.
- RF-46. El bloque de contraste del paso 4 se alimenta de la corrida baseline del escenario "respuesta perdida tras cobro", con su ID, y muestra lo observado (frase del baseline y monto total en Stripe). Si el baseline no duplica en esa corrida, se muestra igual y el video usa el guion alternativo de 9.1; nunca se fuerza el resultado.

### 6.10 Alexa real y MCP App (P2)

- RF-47. Spike de 1 día (semana 2) con el puente `alexa-skill-mcp-bridge` (repo de terceros, Apache-2.0, creado el 5-sep-2026; Devpost no lo nombra): CDK en us-east-1 con Lambda y Bedrock AgentCore sobre Nova 2 Lite; exige MCP 2025-11-25 sobre Streamable HTTP y consume `structuredContent`. Orden: agente local sin despliegue, luego AgentCore, y la skill con el simulador de la consola solo si lo anterior responde. Prerrequisitos de Walter: Nova 2 Lite habilitado en Bedrock us-east-1, credenciales AWS y `cdk bootstrap`, Docker, Node 22.18+; para la skill, cuenta Amazon Developer y ASK CLI. El puente necesita una URL pública del servidor (túnel o hosting): la decisión 10 se adelanta al spike. Salida: "responde" o "documentado por qué no".
- RF-48. Integración completa (semana 5, tope 3 días) contra el servidor alojado; rótulo "Alexa Skill simulator via alexa-skill-mcp-bridge". El puente tiene un presupuesto de 6,5 s por turno (ventana de Alexa de 8 s) y no trata `PENDING` de forma especial: el modelo lo verbaliza tal cual. Por eso, sobre el puente el servidor corre en modo síncrono (`pending_after` desactivado: la tool responde cuando termina la verificación, de 3 a 7 s); si excede el presupuesto, el puente responde "still working" y consulta en el siguiente turno del usuario. Autenticación por bearer; sin cabeceras adicionales: el `run_id` se deriva de la sesión MCP. Aprobación de cobros por elicitation (RF-24), que el puente declara. Si el agente del puente sobreafirma sobre un resultado no verificado, se graba: es evidencia de la tesis y entrada de friction log.
- RF-49. Si el spike falla: tarjeta de recibo como MCP App (`ui://receipt`, bundle TS aparte) renderizada en Claude Desktop.
- RF-50. `integrations/alexa/` guarda plantilla de `addon.json` sin credenciales y la ruta oficial documentada (OAuth 2.1 + PKCE, refresh tokens, `/.well-known/oauth-protected-resource`), sin implementarla.

### 6.11 Agent Skill (P1, ≤ 1 hora)

- RF-51. `skills/alexa-donewise/SKILL.md` (estándar agentskills.io) que enseña a un agente a levantar el servidor, conectarse por Streamable HTTP y leer recibos. Toca las dos tecnologías nombradas en el track.

---

## 7. Requisitos no funcionales

| ID | Requisito |
| --- | --- |
| NF-01 | Compatibilidad: versión negociada 2025-11-25 registrada y afirmada en CI; la inconsistencia con 2026-07-28 va al product feedback. |
| NF-02 | Latencia: lecturas p95 < 500 ms; escrituras `PENDING` p95 < 500 ms; tabla p50/p95 por tool publicada (Fake y conectado). |
| NF-03 | Seguridad: bearer estático; `Origin` validado; sin secretos en el repo (`.env.example`); claves de Google y Stripe por variables de entorno; abortar si la clave de Stripe no es de test; exportaciones sanitizadas; una URL de recibo no da acceso anónimo al calendario. |
| NF-04 | Fiabilidad: registro append-only en disco persistente; unicidad en base de datos; el servidor retoma operaciones inconclusas al reiniciar (T11) aplicando la ventana de replay (RF-15) y la reconciliación (RF-17b). |
| NF-05 | Reproducibilidad: `docker compose up` (o `uv run`) levanta servidor y simulador en sandbox sin claves; CI levanta el servidor y conecta el cliente oficial por HTTP. |
| NF-06 | Cumplimiento de bases: material público en inglés; sin logos de Amazon ni sonido de activación; rótulo "simulated" permanente; sin música con derechos; licencia MIT visible en la raíz. |
| NF-07 | Disponibilidad (P1, va con la demo alojada de 4.1): demo alojada viva desde la entrega hasta el 20-nov-2026; instancia única con disco persistente (hosting pendiente, ver 12). |
| NF-08 | Honestidad: README con sección "What is real / what is simulated" y mapa afirmación → evidencia; lo no probado se llama no probado. |
| NF-09 | Código: Python 3.12, pydantic para contratos, tipado, Ruff; frontend HTML/CSS/JS plano servido por FastAPI por defecto; React permitido, **Next.js prohibido** (RF-39b). |

---

## 8. Casos de aceptación (P0; deben pasar antes de grabar)

Se ejecutan en CI contra Fake* y, semanalmente, contra Google + Stripe test. El oráculo es el estado independiente del sandbox o el recurso externo, no el propio verificador. Aceptación: cero confirmaciones falsas y cero duplicados en esta suite; se publican los conteos. **Este gate aplica al video final y a la entrega; el video de ensayo del 2-oct (§10) solo exige T06–T12 y T17 en sandbox.**

| ID | Caso | Comportamiento exigido |
| --- | --- | --- |
| T06 | Alta correcta | Relectura coincidente antes de confirmar; `VERIFIED`, `writes_applied = 1`. |
| T07 | Acuse favorable sin escritura | `NOT_OBSERVED`, `may_claim_success = false`, tres lecturas en 5 s registradas. |
| T08 | Escritura aplicada, respuesta perdida (calendario y pago) | Recuperar por replay con el mismo ID/clave y relectura; un solo efecto; `WRITE_RESPONSE_LOST_RECOVERED`. Variante fuera de ventana (clave de Stripe expirada, simulada en Fake*): sin replay; `UNKNOWN` hasta reconciliar por lectura; nunca segunda petición. |
| T09 | Escritura incierta y lectura caída | `UNKNOWN`; sin éxito ni fracaso definitivo; se resuelve con una observación posterior. |
| T10 | Evento equivocado o zona/fecha errónea | Rechazo por validación de intención o por veredicto. |
| T11 | Doble envío / reinicio del proceso | Misma intención retomada sin doble efecto; el reenvío de una operación con aprobación consumida devuelve su estado (no `APPROVAL_USED`); dos workers reclamando la misma operación → uno gana por inserción única. |
| T12 | Edición concurrente | 412 respetado; relectura; `VERSION_CONFLICT`; pregunta; nunca sobrescribir. |
| T13 | Objetivo ambiguo | `NEEDS_INPUT` con una sola pregunta; nada escrito. |
| T14 | Token inválido u otra cuenta | `isError: true`, `UNAUTHORIZED`, sin efecto ni fuga de evidencia. |
| T15 | Datos externos con instrucciones | Título de evento con "ignore previous instructions" no genera acciones ni permisos. |
| T16 | Registro caído | Sin recibo de éxito; `isError` antes de la intención, `UNKNOWN` después de la escritura. |
| T17 | Cobro sin aprobación | `NEEDS_APPROVAL`; nada en Stripe; `NOTHING_CHARGED`. |
| T18 | Aprobación de US$60 usada para US$90; aprobación usada para una segunda operación; aprobación caducada sin consumir; `approval_grant` sin `consent_token` | `REJECTED` con `APPROVAL_MISMATCH` / `APPROVAL_USED` / `APPROVAL_EXPIRED`; `isError` + `UNAUTHORIZED` para el último; nada cobrado. |
| T19 | Evidencia tardía de un intento anterior | No reemplaza el veredicto más nuevo. |
| T20 | Cliente que reintenta solo tras `isError` | Reintento cae en la misma intención; un solo efecto. |
| T21 | Caída entre commit en Google/Stripe y persistencia local | Al retomar, releer y persistir evidencia; `VERIFIED` sin segunda escritura. |
| T22 | Replay automático agotado (fallo de acuse durante dos intentos, paso 5) | Un solo replay automático; `NOT_OBSERVED` con `automatic_retries = 1`; "try again" abre un intento nuevo sobre la misma intención; al final un solo write observado. |

T01–T05 (tiempo, música, receta) quedan fuera.

---

## 9. Entregables públicos (checklist Devpost)

| Entregable | Contenido mínimo |
| --- | --- |
| Repo público MIT | `server/`, `core/` (librería), `adapters/`, `sim/`, `evals/`, `integrations/alexa/`, `skills/`, `docs/` (traces, friction log, product feedback), `docker-compose.yml`, CI. |
| README (inglés) | Una frase; tabla baseline vs DoneWise arriba; "What is real / what is simulated"; mapa afirmación → evidencia; tres capturas; quickstart `docker compose up`; cómo conectarse desde Inspector y Claude Desktop; cómo correr conectado con claves propias; tabla p50/p95; integraciones AWS con propósito y configuración; límites conocidos; segundo adaptador en 30 líneas (P1). |
| Video < 3 min, inglés, YouTube público | Guion en 9.1. Sin música con derechos, sin marcas de terceros. Ensayo en sandbox el 2-oct (ver 12), final antes del 20-oct con el gate de §8. |
| Descripción de texto en Devpost | Features y funcionalidad, una frase, qué es real, enlaces. |
| Product feedback (obligatorio) | Herramientas usadas y para qué; qué funcionó (setup, docs, testing, performance, fiabilidad); qué falta; onboarding "zero to hello world"; reutilizaría sí/no y por qué. |
| Friction log (bonus 10 %) | Formato de Amazon: tarea, pasos, esperado, observado, severidad, workaround, sugerencia. Cada entrada con archivo de evidencia y comando reproducible. Se escribe el mismo día. Entradas ya identificadas en `docs/analisis-y-plan.md` §6.5; prioridad a fricción de runtime (SDK negociando 2025-11-25, Inspector, Bedrock, AgentCore, ASK CLI en Windows). |
| Formulario | Track Alexa+; mini-challenges AWS Builder y Open Source; créditos AWS pedidos antes del 21-oct-2026. |

### 9.1 Guion del video (2:45, inglés)

Historia de 5.1 en la pantalla de `donewise-3min.html`. Tiempos medidos sobre el prototipo: cada turno ocupa entre 12 y 30 segundos con la narración encima.

**Grabación en vivo con voz (decisión de Walter, 16-sep-2026).** Walter le habla al micrófono del notebook (Web Speech API en Chrome, RF-31) y el agente LLM corre de verdad (RF-32) contra Google Calendar y Stripe test. El modo guionado (RF-35) es solo respaldo. Reglas:
- Guion de 5 frases fijas y cortas (las de 5.1), ensayadas; "Yes, charge it" es la afirmación exacta que el backend clasifica para la aprobación (RF-24).
- Campo de texto visible en la misma toma como plan B si el reconocimiento falla; se puede cortar entre turnos, el video es editado.
- Los fallos se arman antes de cada turno desde el panel, en pantalla y rotulados; no dependen del LLM.
- Tres tomas completas; se elige la mejor. Si en ninguna el agente hace lo esperado, ese turno se toma del modo guionado y se rotula; el README lo declara.
- Rótulo en pantalla durante la sesión: "live voice session". Latencia de 3 a 6 s por turno aceptada o acortada en edición.
- Ensayo del 2-oct en sandbox (Fake*) ya con voz; toma final en modo conectado en la semana 5.

| Tiempo | Pantalla | Voz |
| --- | --- | --- |
| 0:00–0:08 | Tarjeta genérica "Done! Your $60 deposit is paid." Corte al dashboard de Stripe (test): dos cargos, US$120. | "Assistants say 'done' before they check. This one charged twice." **Alternativa** si ninguna corrida baseline duplicó: corte al dashboard vacío tras un "Done!" con la respuesta perdida; "This one said done. Nothing was checked." |
| 0:08–0:15 | Título. | "Alexa-DoneWise is an MCP add-on for Alexa+. It reads the result back before it says a word, and it never does it twice." |
| 0:15–0:25 | Pantalla única con rótulo, Google Calendar y Stripe test en pestañas, banda de fallos. | "Real MCP server, spec 2025-11-25. Real calendar and a test-mode payment on the right. Two faults injected on purpose." |
| 0:25–0:45 | Turno 1: cita creada y petición de aprobación en la misma respuesta; comprobante "$60.00 · waiting for your OK · charges applied 0"; Google Calendar muestra el evento. | "It books, reads it back, and asks for an OK bound to this exact amount and payee. Nothing charged yet." |
| 0:45–1:15 | Turno 2 y 2b: "Yes, charge it"; banner "response dropped after the charge"; PENDING; recuperado; **charges applied: 1**; bloque de contraste con lo observado. | "The response was lost after the charge. It recovered by reading the payment back. One test charge, not two." |
| 1:15–1:40 | Turnos 3 y 4: "ack without write" ×2; un replay automático; NOT_OBSERVED con "2 attempts · 1 automatic"; "try again"; VERIFIED; Google Calendar muestra las 10. | "The calendar said OK and did nothing, twice. DoneWise retried once on its own, then asked. It never said done until the calendar showed ten." |
| 1:40–1:55 | Turno 5: recap desde los recibos, cada resultado con su hora; "nothing new written". | "Ask it what happened and it only repeats what it checked, and when." |
| 1:55–2:20 | Recibo abierto; handshake con 2025-11-25; Claude Desktop o Inspector; Alexa del simulador si entró. | "Any MCP client gets the same receipt." |
| 2:20–2:45 | Tabla baseline vs DoneWise; repo; `docker compose up`. | "Zero false confirmations, zero duplicates in our fault suite. Numbers, denominators and code in the repo." |

## 10. Hitos

| Fecha | Hito | Condición |
| --- | --- | --- |
| 21-sep-2026 | Servidor MCP + harness + FakeCalendar; T06–T12 sin LLM. | Inspector completa handshake y `tools/list`; versión registrada. |
| 28-sep-2026 | Google real, proxy de fallos, `PENDING`/`operation_get`, replay condicional, **modo guionado en sandbox (RF-35)**, Claude Code como cliente, spike del puente. | T07, T08, T09, T12 pasan contra Google; el guion de 7 pasos corre sin LLM contra Fake*. |
| 2-oct-2026 | **Video de ensayo (decisión 1):** video de 3 min grabado en sandbox (`FakeCalendar`, `FakePayments`) con voz en vivo y agente LLM; modo guionado como respaldo por turno. Subido privado. No exige el gate de §8 completo (solo T06–T12 y T17 en sandbox). | Existe el archivo. Si no, se cancelan puente y evaluación LLM ese día. |
| 5-oct-2026 | Stripe test + aprobación (T17, T18); simulador completo con voz. | Sesión completa por voz y por guion en modo conectado. |
| 12-oct-2026 | Evaluación, README, product feedback, demo alojada. | Tabla publicada; jurado corre sin claves. |
| 19-oct-2026 | Puente (tope 3 días) o MCP App; primer corte final del video 15-oct (con el gate de §8 completo, voz en vivo en modo conectado, tres tomas); librería publicada. | Video final < 3 min. |
| 23-oct-2026 16:00 Chile | Entrega. | Formulario enviado; créditos pedidos antes del 21-oct. |

---

## 11. Riesgos principales

| Riesgo | Mitigación en este PRD |
| --- | --- |
| Una persona, seis subsistemas, sin holgura. | Hito video-first del 2-oct; P0/P1/P2 explícitos; nada P2 antes del video. |
| El puente consume días y su agente sobreafirma. | Spike de 1 día con el servidor de ejemplo; tope 3 días; grabar la sobreafirmación como evidencia. |
| El diferenciador es invisible en 3 minutos. | Contador "charges applied", Google Calendar y Stripe test en pantalla, apertura con el fallo, narración "one charge, not two". |
| `PENDING` contradice el modelo de Alexa+ (presupuesto de 6,5 s por turno en el puente; la doc oficial pide 3 s o mensaje interino). | Modo síncrono sobre el puente (RF-48); tabla p50/p95 con adaptadores reales; frase solo-voz; feedback a Amazon. |
| "Otro proyecto de guardrails" (Ripple, Housewarden, Shift Relay…). | Vender el resultado y el número, no la verificación; librería instalable; tres clientes distintos respetando el recibo. |
| Google/Stripe rechazan algo del diseño (ID propio, `If-Match`, idempotencia). | Verificar en la semana 2; el diseño ya prevé 409 como evidencia y 412 como conflicto. |

---

## 12. Decisiones de Walter (aprobadas el 16-sep-2026 con el default, salvo la 10)

Los defaults de 1 a 9 y 11 quedaron aprobados el 16-sep-2026. La 10 (hosting) se decide al final.

| # | Decisión | Default propuesto | Costo |
| --- | --- | --- | --- |
| 1 | Hito video-first el 2-oct con cancelación automática de puente y evaluación LLM si falla. | **Sí.** | 1 día |
| 3 | Contador "charges/writes applied" grande y pestaña real de Google Calendar y Stripe siempre en pantalla. | **Sí** (ya está en `Main.dc.html`). | 0,5 día |
| 4 | README al nivel de Ripple (real vs simulado, mapa afirmación→evidencia, capturas, quickstart, CI con cliente oficial). | **Sí** (incluido en 9). | 1 día |
| 5 | Ruta rápida síncrona < 450 ms cuando cabe; `PENDING` solo cuando no; tabla p50/p95. | **Sí**, tras medir Google y Stripe en la semana 2. | 0,5 día |
| 6 | Ruta solo-voz documentada y demostrada (5.3). | **Sí**, documentada; demostrada solo si entra el puente. | 0,5 día |
| 7 | Segundo adaptador trivial solo en README. | **Sí**, semana 4 si el video existe. | 1 día |
| 8 | Cortar Polly y la segunda variante del reintento en el video. | **Sí a ambos.** | ahorra 1 día |
| 9 | Evaluación LLM: 10×3×2 (P10 del plan) o una sola pasada 10×1×2 más matriz determinista (revisión). | **Una pasada** más matriz determinista (RF-44 alineado); repetir a ×3 si sobra tiempo en la semana 4. | ahorra 0,5 día |
| 10 | Hosting. **Restricción nueva (Codex, 16-sep-2026):** el registro SQLite exige disco persistente e instancia única; App Runner tiene almacenamiento efímero y no sirve con SQLite local. Opciones: Fly.io con volumen; EC2/Lightsail con EBS; App Runner solo si se cambia el registro a una base gestionada (fuera de alcance en 4.2). AWS Builder se sostiene con Bedrock sin depender del hosting. | **Pendiente**; se decide al final (semana 4). Mientras tanto nada del código asume el hosting. | — |
| 11 | Zona horaria y hora del usuario de prueba en el video. | `America/Los_Angeles`, tarde (7:39 PM como en el mockup). | — |
| 12 | Frontend del simulador. | **Next.js prohibido.** Por defecto HTML/CSS/JS plano servido por FastAPI; React permitido si hace falta (RF-39b). Decidido el 16-sep-2026 (corrige "sin React" del mismo día). | — |
| 13 | Dirección visual e historia. | **Propuesta de Codex** (`donewise-evening.codex.html`) como UI, conservada sin rediseñar; historia recortada a 5 turnos para el video de 3 min (`donewise-3min.html`, 5.1). Dentista, paquete, desambiguación y "una hora después" fuera del video; continuidad entre sesiones como P2 tras el video final. Decidido el 16-sep-2026. | — |
| 14 | Video grabado con voz en vivo (micrófono del notebook, Web Speech API) y agente LLM real; modo guionado solo como respaldo por turno, rotulado. | **Sí.** Decidido el 16-sep-2026. Detalle en 9.1. | — |

---

## 13. Glosario

- **Intención:** lo que el usuario autorizó, normalizado (objeto, objetivo absoluto, monto, destinatario). Una intención tiene una clave de idempotencia.
- **Operación / intento:** una ejecución de la intención / cada envío al proveedor dentro de ella.
- **Observación:** consulta nueva al proveedor, con identidad, objeto, versión y hora.
- **Veredicto:** comparación de la observación con el objetivo; produce el `outcome`.
- **Recibo:** registro persistido del veredicto con claims permitidos y frase; única fuente de la confirmación.
- **Replay seguro:** repetir un envío con el mismo ID/clave, objetivo absoluto y precondición, de modo que no pueda duplicar.
- **Simulated Alexa+ experience:** web propia que reproduce la interacción; no es Alexa+ ni usa el MCP Toolkit.
- **Puente:** `KayLerch/alexa-skill-mcp-bridge` (Apache-2.0): Alexa Skill clásico + agente en Bedrock AgentCore como cliente MCP; se prueba en el simulador de la consola de desarrollador sin Echo.

---

## 14. Cambios v1.0 → v1.1 (16-sep-2026)

Origen: revisión documental de Codex sobre el PRD v1.0 (16-sep-2026). Los 7 hallazgos y los ajustes de coherencia se verificaron contra el texto y se aplicaron todos. Walter aprobó el PRD con los defaults de §12; el hosting (decisión 10) queda para el final.

| # | Hallazgo | Cambio |
| --- | --- | --- |
| 1 | La clave de idempotencia mezclaba identidad y payload. | RF-11: `intent_id` estable por (`user_id`, `submission_id`) + huella del payload separada; la clave del proveedor deriva del `intent_id`. |
| 2 | Aprobación de un solo uso vs replay seguro. | RF-23: consumo atómico y durable por operación; reenviar la misma operación devuelve su estado; otra operación → `APPROVAL_USED`; caducidad solo hasta el consumo. T11 y T18 ajustados. |
| 3 | El modelo podía llamar `approval_grant`. | RF-24/RF-32: `consent_token` por sesión fuera del contexto del modelo; en la web `approval_grant` no está en las tools del modelo. |
| 4 | Frases que afirmaban más de lo verificado. | 5.1, 5.3 y 9.1: "it's on your calendar", "test charge recorded for…"; proveedor declarado simulado; párrafo "qué prueba cada frase". |
| 5 | Replay sin límite frente a la ventana de 24 h de Stripe. | RF-15: replay solo dentro de la ventana; RF-17b: reconciliación solo por lectura con dueño y cierre a las 24 h; T08 con variante fuera de ventana. |
| 6 | App Runner es efímero; SQLite necesita disco. | Decisión 10 reescrita con la restricción; RF-26 y NF-04 exigen disco persistente; hosting pendiente. |
| 7 | "Try again" del paso 5 contradecía la recuperación automática. | RF-16 y 5.1: el fallo dura dos intentos, el harness agota su replay automático y solo entonces pide al usuario; T22 nuevo; guion 9.1 ajustado. |
| C1 | Baseline sin idempotencia medía un conjunto de cambios. | RF-44: baseline con clave nueva por llamada; README declara qué mide la comparación; RF-46 y 9.1 con resultado observado y guion alternativo. |
| C2 | Video del 2-oct dependía del modo guionado del 5-oct. | RF-35 y §10: modo guionado en la semana 2; 2-oct es ensayo en sandbox sin el gate completo de §8. |
| C3 | Append-only vs claims por `UPDATE`; Fake* en memoria vs reinicio; ×3 vs ×1; hosting P1 vs NF-07 obligatorio. | RF-11/RF-26: claims por `INSERT` único; Fake* con estado en archivo; RF-44 en ×1; NF-07 P1. |
| C4 | §4 decía T06–T18; §8 llegaba a T21; reconciliación sin dueño. | §4 corregido (T06–T22); RF-17b define dueño y cierre. |
| W | Decisión de Walter: Next.js prohibido (corrigió el mismo día una primera versión que decía "sin React"). | RF-39b, NF-09 y decisión 12. |

### 14.1 Cambios v1.1 → v1.2 (16-sep-2026)

Origen: propuesta de UI de Codex (`design/mockups/donewise-evening.codex.html`, historia de Clara en 14 escenas) aprobada por Walter como dirección visual, y pedido de Walter de recortarla para que quepa en 3 minutos conservando ese frontend.

| Cambio | Dónde |
| --- | --- |
| Dirección visual de Codex (marfil y verde petróleo, Instrument Serif + IBM Plex Sans, conversación / comprobante / registro, móvil) reemplaza la dirección "kitchen receipt" de `Main.dc.html`. | 5.2, RF-39, decisión 13 |
| Historia recortada a 5 turnos y 6 estados: reserva + petición de aprobación en un turno; aprobación con respuesta perdida y recuperación automática; cambio con acuse falso ×2 y replay automático agotado; "try again"; recap desde recibos. Prototipo estático en inglés: `donewise-3min.html`. | 5.1, 9.1 |
| Fuera del video y del P0: dentista, "retirar paquete", desambiguación (sigue como T13) y el salto de una hora. Continuidad entre sesiones como P2 con prerrequisitos (`calendar_get_verified`, consulta de `receipts` antes de actuar). | 4.1, 4.2 |
| Tool nueva de solo lectura `receipts_recap`, para que el recap salga por plantilla del registro y no del modelo (RF-19). Turnos con varias tools concatenan sus `spoken`. | 4.1, 6.2, RF-33, 5.3 |
| Controles de la demo separados y rotulados; "Continue" envía la siguiente entrada guionada; ningún estado sale de avanzar escena ni de un temporizador. | 5.2 |
| Video grabado con voz en vivo y agente real; guionado solo como respaldo por turno, rotulado. | 9.1, §10, decisión 14 |

### 14.2 Cambios v1.2 → v1.3 (17-sep-2026)

Origen: spike documental del puente Alexa+ (17-sep-2026, sin ejecutar nada) y estado real del código al cierre del paso 3.

| Cambio | Dónde |
| --- | --- |
| El puente `alexa-skill-mcp-bridge` es de terceros y exige URL pública; prerrequisitos de cuentas listados; orden del spike en tres tramos. | RF-47, decisión 10 |
| Corregido "sus timeouts son largos": presupuesto de 6,5 s por turno; sobre el puente el servidor corre en modo síncrono; sin cabeceras extra; `run_id` desde la sesión MCP. | RF-48, §11 |
| Aprobación por elicitation pasa a P1 para la integración con el puente (`granted_by: elicitation`); sigue P2 para otros clientes. | RF-24 |
| Estado del documento: qué está construido al 17-sep. | Cabecera |
