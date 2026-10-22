# k3 — Video RAG como indexación automática de lo que se streamea

**Repo de trabajo:** `~/proyectos/OpenaiBuildWeek/Kateto` (rama `fix/jaw-snap-idle`, 46 archivos
sucios: **no pises nada existente**, creá archivos nuevos).
**Repo a LEER (nunca escribir):** `~/proyectos/video-rag` — es Rust, con la pipeline de indexado.

## Meta
Hoy el video/directo se indexa **a mano**. El usuario quiere que Kateto lo **indexe solo** mientras
streamea, apoyándose en video-rag, y que el resultado sea más confiable porque los insumos ya vienen
procesados por separado (video, audio, chat, OCR).

## Lo que ya está averiguado (no lo re-diagnostiques)
- Kateto **ya habla con video-rag por MCP**: en `kateto/plugins/executor/static_vision_plugin.py`
  (líneas 1147, 1189, 1254, 1321) llama `call_mcp(["video_rag"], "ocr_images" | "detect_objects" |
  "describe_images", {...})`. Ese plugin es el patrón a copiar para pegarle al server.
- video-rag es **Rust** y su indexado es una pipeline con comando propio (`video-rag index`,
  `pipeline/checkpoint.rs` guarda un `out/<stem>.checkpoint.json` por turno de ASR y lo borra al
  terminar; `pipeline/chunking.rs` arma los chunks indexables). Los escenarios del dataset de Kateto
  usan las tools `list_videos`, `summarize`, `answer`, `search`, así que el server MCP ya expone
  consulta.

## Lo primero que tenés que averiguar (esto decide el diseño)
1. **¿El server MCP de video-rag expone algo de indexado?** Buscá en `~/proyectos/video-rag` dónde se
   declaran las tools MCP (probablemente en `src/` o en un binario aparte; mirá también
   `config.toml` y `mcp.json`/similar). Si existe una tool de indexado (`index`, `ingest`, `add_video`),
   anotá su nombre exacto y sus argumentos.
2. **¿Si no existe, cómo se dispara el indexado hoy?** Comando exacto, qué necesita (path del video,
   flags, config), cuánto tarda y si es incremental (checkpoint por turno sugiere que sí).
3. **Cómo está declarado el server MCP en Kateto**: `config.toml` / `config/defaults/config.toml`
   (sección de MCP servers) y cómo el plugin resuelve `server="video_rag"`.

## Diseño (entregable principal)
Con eso, escribí el diseño de la indexación automática, concreto y con nombres:
- **Qué dispara el indexado**: ¿arranque/fin de stream? ¿cada N minutos mientras se graba? ¿un evento
  del runtime? Elegí uno y justificá con lo que permite la pipeline (el checkpoint por turno es la
  pista fuerte de que se puede indexar incremental).
- **Ruta del archivo**: quién graba el directo y dónde queda el `.mp4`/`.mkv` antes de indexarlo, y
  cómo se evita indexar dos veces el mismo tramo.
- **Quién lo dispara en Kateto**: un plugin nuevo (patrón `static_vision_plugin.py`), una tool de voz,
  o un workflow programado. Decilo con nombre de archivo.
- **Cómo se consulta después**: la voz ya tiene `summarize`/`answer`/`search`; ¿qué falta para que
  apunten al material recién indexado sin que el usuario diga nada?
- **Qué NO se puede hacer sin tocar video-rag**: si el indexado necesita una tool MCP que no existe,
  eso va como **pedido concreto a video-rag** (nombre de la tool, entrada, salida). No la implementes
  vos: Kateto es el repo de esta corrida.

## Implementación mínima (sólo si el camino existe hoy)
Si hay una tool MCP de indexado (o el comando CLI es estable), implementá **la parte de Kateto**:
- Un plugin nuevo en `kateto/plugins/executor/` que dispare el indexado y registre el resultado
  (aprovechá el `conversation_log` que ya existe para dejar traza: `logs/session-*.jsonl`).
- Con tests propios (pytest-asyncio, `tmp_path`, sin red y **sin MCP real**: mockeá el cliente).
- Si el camino NO existe hoy, **no inventes un puente trucho**: entregá el diseño y el pedido a
  video-rag, y decilo en el reporte.

## Reglas
- `~/proyectos/video-rag`: **sólo lectura**. Ni un archivo, ni un commit.
- No toques `static_vision_plugin.py` ni el `conversation_log.py` recién creado (podés importar de él).
- **No commitees ni pushees.**
- Todo lo que afirmes de video-rag va con `archivo:línea`. Lo no verificado, en su sección.
- No corras la pipeline de indexado de verdad (tarda y escribe en `out/` de video-rag): si necesitás
  medir, medí sobre `--help`, los docs del repo o una corrida en seco.

## Gates
```bash
cd ~/proyectos/OpenaiBuildWeek/Kateto
uv run pytest kateto/tests/<tu_test_nuevo>.py -q
uv run pytest -q 2>&1 | tail -6
```
**Baseline conocido** (de `AGENTS.md`): 7 archivos con error de colección por falta de `kateto.qa`,
más `test_cli_connector` y `test_conversation_support`. Corré la suite completa antes y después, y
pegá los dos conteos.

## Entregable
`/home/chaos/harness-run/k3/DESIGN.md` (ruta ABSOLUTA):
1. `## TL;DR` (15 líneas): se puede o no, y qué falta.
2. Estado de video-rag para indexado (con `archivo:línea`) y del MCP en Kateto.
3. Diseño de la indexación automática completa (disparador, ruta del archivo, plugin, consulta).
4. Pedido concreto a video-rag si hace falta una tool nueva (nombre, entrada, salida).
5. Lo implementado (si aplica) + salida cruda de los gates.
6. No verificado / supuestos.
