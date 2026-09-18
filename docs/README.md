# Documentación de Alexa-DoneWise

Estado al 17-sep-2026. Orden de lectura:

| Archivo | Qué es | Estado |
| --- | --- | --- |
| `prd.md` | PRD v1.3: qué se construye, contratos, casos T06–T22, guion del video, decisiones. **Manda sobre el alcance.** | Aprobado 16-sep-2026; hosting pendiente. |
| `product-feedback.md` | Feedback observado sobre las herramientas de Amazon usadas (entrega obligatoria del hackathon). | En curso. |
| `friction-log.md` | Friction log en formato Amazon: tarea, esperado, observado, severidad, workaround. | En curso. |
| `schemas/` | JSON Schema de entrada y salida de cada tool MCP, exportados con `scripts/export_schemas.py`. | Generados. |
| `traces/` | Evidencia de clientes reales contra el servidor: Inspector, ClientSession, Claude Code, Docker Compose, elicitation. | Capturados 17-sep-2026. |
| `screenshots/` | Capturas del simulador en sandbox usadas en el README. | Capturadas 17-sep-2026. |
| `stripe-sandbox.md` | Creación del sandbox Stripe sin registro, configuración local, caducidad y evidencia de conexión con Google Calendar. | Smoke conectado verificado 18-sep-2026; sandbox temporal hasta 25-sep. |

Los documentos de planificación interna que cita el PRD (`analisis-y-plan.md`, `revision-critica-ganar.md`, `plan-desarrollo.md`, `briefs/`, `archive/`) no se publican en este repositorio.

Mockups en `../design/mockups/`: `donewise-3min.html` es la referencia de pantalla e historia (inglés, 5 turnos); `donewise-evening.codex.html` es la propuesta visual original de Codex (14 escenas, español); los `*.dc.html` son exploración previa.
