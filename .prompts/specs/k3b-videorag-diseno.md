# k3b — Video RAG: cómo se indexa hoy y qué falta para indexar solo (SOLO DISEÑO)

**Repo a LEER:** `~/proyectos/video-rag` (Rust) · **Repo donde podés escribir sólo lo que diga acá**
**NO escribas ni un archivo en ninguno de los dos repos. No commitees. No corras la pipeline.**

## REGLA 0 — el artefacto primero
Lo PRIMERO que hacés, antes de investigar, es crear `/home/chaos/harness-run/k3b/DESIGN.md` con las
secciones vacías del final de este brief. **Se va llenando mientras trabajás.** Si la sesión se corta
a mitad, ese archivo con lo que alcanzaste es el entregable. Una corrida sin ese archivo es una
corrida fallida, aunque hayas pensado mucho.

## Meta
El usuario quiere que el video/directo se **indexe solo** mientras streamea, apoyándose en video-rag,
en vez de indexarlo a mano. Este brief es **sólo averiguar y diseñar**: no se implementa nada, ni en
Kateto ni en video-rag.

## Lo ya averiguado por el orquestador (no lo repitas, usalo)
- Kateto ya le habla a video-rag **por MCP**: `kateto/plugins/executor/static_vision_plugin.py`
  (líneas 1147, 1189, 1254, 1321) llama `call_mcp(["video_rag"], "ocr_images" | "detect_objects" |
  "describe_images", {...})`, y resuelve el nombre del server con `getattr(result, "server", "video_rag")`.
- video-rag es **Rust** y tiene pipeline de indexado propia: `src/pipeline/checkpoint.rs` guarda un
  sidecar `out/<stem>.checkpoint.json` **por turno de ASR** y lo borra al terminar ("Finished
  indexing"), y `src/pipeline/chunking.rs` arma los chunks indexables. O sea el indexado **ya es
  incremental y reanudable**.
- Los escenarios del dataset de Kateto ya usan las tools `list_videos`, `summarize`, `answer`,
  `search` de ese server.

## Las 4 preguntas (esto ES el trabajo)
1. **¿Qué tools MCP expone video-rag hoy?** Buscá dónde se declaran (mirá `src/`, y si hay un binario
   o módulo de MCP; revisá también `BRIEFS/`, `docs/` y `config.toml`). Dame la **lista completa con
   nombre exacto y argumentos**, y `archivo:línea` de cada una. ¿Hay alguna de indexado
   (`index`, `ingest`, `add_video`, `index_video`)? Si no hay, decilo así de claro.
2. **¿Cómo se dispara hoy el indexado?** El comando exacto del CLI, qué recibe (path del video, flags,
   config), si es incremental/reanudable, y cuánto tarda o cómo se estima (duración del video vs
   tiempo de indexado, si hay algún log o doc que lo diga).
3. **¿Quién graba el directo y dónde queda el archivo?** Buscá en `~/proyectos/OpenaiBuildWeek/Kateto`
   y en `~/proyectos/obs-*`/lo que encuentres del lado del streaming: ¿OBS? ¿qué path y qué formato?
   ¿hay algún evento o indicador de "el stream arrancó/terminó"? Si no lo encontrás, decí que no lo
   encontraste y qué habría que definir.
4. **¿Qué falta para que sea automático?** El hueco exacto entre "video-rag sabe indexar" y "Kateto lo
   pide solo".

## Entregable — `/home/chaos/harness-run/k3b/DESIGN.md`
Creá el archivo con este esqueleto y completá cada sección:
```
## TL;DR
(5 líneas: se puede automatizar hoy o falta algo, y qué)

## 1. Tools MCP de video-rag (listado real)
| tool | args | archivo:línea | sirve para indexar? |

## 2. Cómo se dispara el indexado hoy
(comando exacto, args, incremental sí/no, evidencia en archivo:línea)

## 3. Quién graba y dónde queda el archivo
(con evidencia, o "no encontrado")

## 4. Diseño de la indexación automática
- Disparador (qué evento/momento, concreto)
- Quién lo llama en Kateto (archivo/plugin, concreto)
- Cómo se evita indexar dos veces el mismo tramo (el checkpoint sirve?)
- Cómo se consulta después (las tools de consulta que ya existen)

## 5. Pedido concreto a video-rag (si falta una tool)
| tool propuesta | entrada | salida | por qué |

## 6. Lo que NO verifiqué / supuestos
```
Reglas de contenido: todo lo que afirmes de video-rag o de Kateto va con `archivo:línea`. Lo que no
puedas confirmar va en §6, no en las otras secciones. **No inventes tools ni flags**: si una tool no
existe, va en §5. Nada de bloques de código de implementación: es un documento de diseño.

## Gates
```bash
test -s /home/chaos/harness-run/k3b/DESIGN.md && wc -l /home/chaos/harness-run/k3b/DESIGN.md
grep -c "archivo:línea\|:[0-9]" /home/chaos/harness-run/k3b/DESIGN.md   # evidencia citada
```
Pegá la salida cruda de los dos comandos al final del DESIGN.md, en una sección `## Gates`.
