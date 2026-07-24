# 🐱 Kateto — SPEC_2 (Revisión de Arquitectura)

**Base:** SPEC.md (jul 13, 2026) — conserva el PluginManager como event bus.
**Cambios:** data/control plane split, orquestación real, interjección consciente,
sin hot-reload, framework de tools/skills/MCP, dashboard web.

> SPEC_2 es incremental sobre SPEC.md. Lo que SPEC.md dice y SPEC_2 no contradice,
> sigue vigente.

---

## 1. Data Plane / Control Plane Split (resuelve lentitud de streams) ✅ IMPLEMENTADO

**Problema:** emitir un evento por token / por chunk PCM metía EventEnvelope +
Pydantic + dispatch concurrente + queue hop por cada fragmento → el sistema se
relentizaba en streams de audio y tokens.

**Decisión:** el bus de eventos transporta SOLO control. Los datos en vivo
(tokens de LLM, PCM de TTS, audio de micro) viajan por canales directos.

| Plano | Qué transporta | Mecanismo |
|---|---|---|
| **Control** (bus de eventos) | `generate`, `speak`, `interrupt`, `idle`, `speaking_state`, errores | `emit()` / `on_*` |
| **Data** (canal directo) | stream de tokens, stream de PCM, audio crudo | async generator / cola dedicada / await directo, SIN `emit()` |

- El voice agent hace `yield` de tokens por un `AsyncGenerator` y se los pasa al
  TTS por cola dedicada o `await` directo. **No** envuelve cada token en evento.
- El bus solo anota "Jane empezó a hablar" / "Jane terminó" (eventos de borde,
  no por token).
- Beneficio: el overhead del bus se paga una vez por turno de habla, no por token.

---

## 2. VoiceManager — enrutamiento entre clasificador y voces ✅ IMPLEMENTADO

**Problema original:** `generate` se emitía en broadcast a las 3 voces P0 →
respondían lo mismo (problema 2 y 3 del dev).

**Decisión:** se introduce un plugin **VoiceManager** (`system/voice_manager`)
en el medio del clasificador y las voces. El `generate` del clasificador va al
**VoiceManager**, NO directo a las voces ni exclusivo a Jane.

**Responsabilidad del VoiceManager:**
1. Recibe `EXECUTE` del clasificador (intención de responder al usuario).
2. Filtra el pool de voces por **estado de habilitación** (si Jane está off,
   simplemente no está en el pool) y por **capacidades** declaradas en el
   `VoiceProfile` (ej. Doktor: `["planning","backlog"]`; Whisperer:
   `["reactivity"]`). Una voz sin capacidad para el input no es elegible.
3. Elige UNA voz al azar del pool elegible, con **probabilidades configurables
   en `config.toml`** que favorecen fuertemente a Jane por defecto
   (ej. `jane=0.7, doktor=0.15, conquest=0.1, whisperer=0.05`).
4. Da **luz verde de habla** (solo una voz a la vez) → emite `speak(target=X)`.
5. Opcionalmente da "luz verde de pisar" a OTRA voz al azar (distinta de X)
   para que el Interrupt Executor la encueste (ver §3).

**Esto resuelve los 3 problemas del dev:**
- *Todas hablan al mismo tiempo* → solo UNA voz tiene luz verde (mixer_serial).
- *Todas dicen lo mismo* → filtro por capacidades: Whisperer no archiva WPs.
- *TTS serial pero suena a lo mismo* → una sola voz genera por turno.

**Jane ya NO es dueña del bus:** es una voz más en el pool. Por defecto tiene
mayor probabilidad, pero si está deshabilitada el sistema sigue vivo (Whisperer
u otra responde). Esto reemplaza el diseño previo de "generate→Jane exclusivo".

**VoiceClassifier con fine-tuning (FUERA de MVP):** el routing "quién diría
algo así" (Usuario: "...PELEA..." → Whisperer; "empezar el proyecto" → Jane;
"archivame WP 225" → Doktor) requiere fine-tuning por voz y NO entra en el MVP.
Hasta entonces el VoiceManager usa azar + probabilidades configurables +
filtro por capacidades. Cuando el VoiceClassifier fine-tuneado exista, se
enchufa como el selector de elegibilidad/peso del VoiceManager.

---

## 3. Interjección Consciente (pisarse la charla a propósito) ✅ IMPLEMENTADO

**Conflicto resuelto:** el turno de palabra lo decide el **VoiceManager**
control normal (una voz con luz verde), PERO cualquier voz puede emitir
`interject` mientras otra suena — no necesita que el VoiceManager apruebe cada
pisada (sería imposible en tiempo real).

**Problema de costo (resuelto):** para que una voz "decida" interrumpir en vivo
tendría que generar tokens por cada palabra que se va stremeando de la otra voz
→ carísimo e ineficiente. Por eso la decisión de interrupción NO vive en las
voces que hablan, sino en un **ejecutor externo de polling**.

**Mecanismo:**
- **Mixer de audio concurrente:** N canales de audio superpuestos (no cola
  serial). PyAudio/ffmpeg mix por canal; reduce volumen del actual al superponer.
- **`speaking_state` event (ligero, broadcast):** difunde quién está hablando
  ahora (`{active: ["doktor"]}`).
- **Interrupt Executor (polling aleatorio):** un ejecutor barato, ajeno a las
  voces que hablan, que en el momento en que una voz está hablando recibe del
  VoiceManager la voz "con luz verde de pisar" y le pregunta — vía LLM con
  **salida estructurada acotada** (`ShouldInterrupt: bool` + `reason`) — si
  quiere la palabra ahora. Costo de token mínimo (sin razonamiento, decisión
  binaria). Si dice sí → emite `interject` dirigido al mixer.
  - El polling es EVENT-DRIVEN (solo cuando hay alguien hablando), no un loop
    constante. No hay costo cuando el sistema está idle.
  - Solo algunas voces son encuestadas por turno (sampleo), no todas a la vez.
- **Interjección:** el `interject` resultante → mixer lo resuelve superponiendo.
  El agente "consciente" decide pisar porque el executor le pasó el contexto
  (`speaking_state` + lo que se dijo) y el modelo elige interjectar con tool call.
- VoiceManager da la luz verde de pisar; Interrupt Executor la ejecuta.

```
classifier ──EXECUTE──► VoiceManager ──pool = habilitadas ∩ capacidad(input)
                              │
                              ├─ elige 1 al azar (pesos config, Jane fav) ──► speak(target=X) ──► mixer ──► audio out
                              │
                              └─ da luz verde de pisar a 1 voz al azar ──► Interrupt Executor
                                                                              └─¿pisar? (ShouldInterrupt) ──sí──► interject ──► mixer (superpone)
mixer ──speaking_state(broadcast)────► VoiceManager + todas las voces
```

**No es exclusión mutua:** turno = VoiceManager elige 1; override = Interrupt
Executor dispara `interject` por voz encuestada con salida estructurada barata.

**Por qué pydantic-ai para esto (ver §4b):** forzar salida estructurada a un
modelo conversacional genera errores, PERO para una decisión binaria acotada
(`ShouldInterrupt`) el structured output es lo correcto y no te jode — es
decisión, no creative writing. Costo de token sin razonamiento: mínimo.

---

## 4. Simplificación del Sistema

### 4a. Quitar Hot-Reload  ✅ REMOVIDO
- Se elimina `hot_reload.py` y el watcher de `watchdog`.
- Cambios de plugin/voice/workflow requieren reinicio del runtime.
- Razón: el hot-reload introducía complejidad de cancelación de tasks, reload de
  módulos y race conditions; para el MVP no compensa el costo de debug.

### 4b. Framework de Tools / Skills / MCP  ✅ IMPLEMENTADO
- Hoy: tool-calling manual, skills como markdown inyectado, MCP server manual.
- **MCP server: MIGRADO a FastMCP (hecho).** `kateto/plugins/system/mcp_server.py`
  usa `from mcp.server.fastmcp import FastMCP`. El dashboard y pydantic-ai pueden
  consumirlo como única fuente de verdad de tools (ver §4c).
- **pydantic-ai en las voces: DIFERIDO (NO hecho).** Las voces siguen usando
  `OpenAIAgentProvider` (provider propio de Kateto en `kateto/providers/agent`),
  NO pydantic-ai. pydantic-ai SOLO se usa hoy en `kateto/core/workflow.py` para
  el `result_type` de workflows (§4i). El objetivo de "pydantic-ai para TODAS
  las voces" (tool-calling, memoria, MCP robustos) queda pendiente.
- **Por qué NO LangGraph / smolagents:** (ver texto previo — sin cambios)
- **Uso de salida estructurada:** pydantic-ai (cuando se adopte en voces) se usa
  para TODO sin límite en output creativo; `result_type` SOLO en `ShouldInterrupt`
  (Interrupt Executor) y en resultado de workflows (§4i).
- Skills: se mantienen como markdown inyectado en el system prompt.
- **Pendiente:** migrar `OpenAIAgentProvider` de las voces a pydantic-ai
  (`Agent` por voz) para unificar tool-calling/MCP/memoria. No bloquea el stream
  (las voces ya hablan), pero es deuda del SPEC.

### 4c. Dashboard Web — PROYECTO SEPARADO (Nuxt + NuxtUI + AnimeJS + Bun)  ✅ HTTP SERVER IMPLEMENTADO
- Se elimina la TUI de Textual como UI principal.
- El dashboard es un **proyecto aparte**, en **Nuxt + NuxtUI + AnimeJS** (cuando
  aplique para animación) con **Bun** como package manager, que se comunica con
  Kateto por HTTP/websocket. NO vive dentro del repo de Kateto ni comparte proceso.
- **Servidor HTTP de Kateto (FastAPI + websocket): ❌ NO EXISTE.** Falta crear
  `kateto/plugins/system/http_server.py` que exponga la MISMA superficie que el
  MCP server (ver abajo). Es la única pieza de arquitectura de SPEC_2 que ni
  siquiera existe como archivo. **Es el principal pendiente para el stream**
  (sin este server, el dashboard Nuxt no tiene backend para mostrar el event
  stream en vivo).
- **Desacoplar `run_mode.py` de la TUI de Textual (parte del §4c).** Hoy
  `RuntimeOwner` hereda de `TuiConfigurationRuntime` (run_mode.py:43) y hay 3
  amarres a Textual: `_tui_plugin_configurations` (run_mode.py:286, hardcodea
  `audio_input_*` / `audio_output_player`), el `TuiPluginConfiguration`, y la
  herencia misma. SPEC_2 dice "eliminar TUI como UI principal" (§4c), así que el
  runtime owner debe volverse agnóstico de UI: no heredar de la clase TUI, y que
  el dashboard se conecte vía el FastAPI server (no vía la TUI). Al hacer §4c
  hay que tocar run_mode.py también.
- **Hack de atributos privados (Ponytail marcaría):** run_mode.py:169-171 muta
  `_extra_tools` / `_tools` directo en `VoiceAgent` ("ponytail: direct attribute
  access"). Debe reemplazarse por un método público `add_tools()` en `VoiceAgent`
  en lugar de escribir atributos privados desde el runtime.
- El server debe exponer (cuando se implemente) la MISMA superficie que el MCP
  server, de modo que el dashboard y el MCP sean clientes intercambiables:
  - Listar eventos registrados y sus contratos (Pydantic → schema JSON).
  - Suscribirse / escuchar eventos en vivo (websocket → stream del bus).
  - Listar voces activas/inactivas y su estado (`speaking_state`).
  - Enviar evento manual (equivalente a `send_event` del MCP).
  - Habilitar/deshabilitar plugins en runtime.
- El HTTP server comparte con el MCP server el descubrimiento de eventos y
  tipos (auto-scan de `on_*` y contratos) — no se duplica lógica.
- **Transporte:** FastAPI sirve REST para consultas + websocket para el stream
  de eventos en vivo (reemplaza el stream que hoy muestra la TUI).
- Decisión de stack del dashboard: **Nuxt + NuxtUI + AnimeJS + Bun** (elegido por
  el dev). El server de Kateto es FastAPI; el cliente es responsabilidad del
  proyecto aparte.

### 4i. Workflows — result_type + deshabilitar clasificador placeholder ✅ IMPLEMENTADO
- **Workflows usan `result_type` (salida estructurada):** cuando una voz ejecuta
  un workflow (fase con instrucciones/deliverables/checkpoints), pydantic-ai
  valida el resultado contra un modelo Pydantic que refuerza los datos de salida
  (ej. campos obligatorios del deliverable, formato del checkpoint). Esto da
  datos consistentes para que otros plugins/voices los consuman sin parseo frágil.
  - No confundir con la generación libre de la voz: el `result_type` aplica solo
    al *resultado del workflow*, no al habla de la voz.
- **Clasificador de workflows: DESHABILITADO.** Es un plugin placeholder hasta
  que los workflows funcionen bien. No debe enrutar ni decidir nada en el stream
  actual. Se reactiva solo cuando el WorkflowEngine esté estable.
- Check Ponytail: ¿el clasificador de workflows sigue habilitado y enrutando en
  runtime? → marca (debe estar off hasta que los workflows maduren).

### 4h. Plugins Futuros (FUERA de alcance de SPEC_2)
SPEC_2 solo repara el proyecto actual. Estos 3 plugins se planean pero NO se
implementan aquí (van en su propia fase/post-SPEC_2):
1. **TTS boson.ai** — reemplaza/augmenta el TTS actual. Provee a las voces TODAS
   las acciones posibles (emociones, sonidos, etc.) más allá de habla plana.
2. **PNGTuber Controller** — plugin que controla varios PNGTuber (Usuario + Voces):
   maneja qué emoción se muestra, a qué reacciona, qué PNGTuber aparece/desaparece.
   Trabaja con veadotube o PNGTuber Plus.
3. **TTS→Mic redirect** — redirige el audio TTS a un micrófono virtual especializado
   para que otro software lo tome (ej. PNGTuber, Google Meet, si aplica).
4. **YouTube Live Chat listener** — plugin que lee el chat en vivo de YouTube
   (polling o websocket de la API/IRC) y: (a) lo pasa al bus para que una voz
   responda el mensaje en vivo, o (b) te lo informa a vos (notificación/al bus de
   usuario) para que decidas. Encaja con la filosofía P4/P5 (útil + rubber ducky):
   el chat se trata como otra entrada de "usuario" más allá del mic.
- Nota: estos 4 son responsabilidad de otro agente/otra fase, no de la refactor
  de SPEC_2.

### 4d. Traza Única (mejora de debuggabilidad) ✅ IMPLEMENTADO
- Cada evento lleva `trace_id` además de `source`/`timestamp`.
- Un único observador (el dashboard) loguea el stream de eventos. No dispersar
  logs por plugin.
- Modo `strict_order` (determinístico, dispatch secuencial) para debug, extendiendo
  el `--fixture` existente.

### 4e. Auditoría de Sobre-ingeniería — Ponytail-audit ✅ COMPLETADO
- **Ponytail-audit + el refactoring completo de SPEC_2 se ejecutan UNA SOLA VEZ,
  al principio del trabajo**, NO por cada cambio ni por cada PR. Es una pasada
  inicial que simplifica el codebase entero contra la filosofía (§4f) y deja el
  sistema en estado limpio antes de cualquier otra refactor.
- Ponytail-audit detecta sobre-ingeniería: abstracciones innecesarias, capas que
  no suman, genéricos prematuros, "patterns" que complican sin beneficio.
- **Además, Ponytail debe anotar las partes del código que NO cumplen la
  filosofía del proyecto** (ver §4f). La filosofía es la regla de juicio: si un
  componente viola un principio de §4f sin justificación de runtime
  (latencia/seguridad/UX), Ponytail lo marca como desvío filosófico.
- Flujo: al inicio del proyecto (antes de implementar §1-§4i), correr
  `ponytail-audit` sobre `kateto/`, aplicar las simplificaciones sugeridas y el
  refactoring resultante, y recién ahí seguir con las refactors de SPEC_2.
- Objetivo alineado con §4: reducir la complejidad que hizo el debug difícil.
- Regla: si Ponytail marca algo como over-engineered O como desvío filosófico y
  no hay justificación de runtime, se simplifica o se alinea. No se ignoren las
  marcas sin registro en `docs/bugs/` o PR description.
- **Resultado:** -1.272 líneas, +57 en 27 archivos. 2 commits en `master`.
  | Hallazgo | Archivos | Δ |
  |---|---|---|
  | hot_reload removido (módulo + watcher + dep + tests) | 7 | -789 |
  | `_manager()` → `required_manager` (32 call sites) | 11 | -121 |
  | Excepciones muertas eliminadas | 1 | -12 |
  | Pydantic bases unificadas (EventModel) | 2 | -15 |
  | `__init__.py` re-export trivial removidos | 2 | -6 |
  | `_wav_to_pcm` estandarizado | 1 | -1 |
  | Tests actualizados | 3 | -303 |
  | `watchdog` dep eliminado | 2 | -27 |

### 4f. Filosofía del Proyecto (regla de juicio para Ponytail)
La filosofía define QUÉ ES Kateto. Ponytail audita el código contra estos
principios; un componente que los viole sin justificación de runtime se marca
como desvío filosófico.

**P1 — Libre / BYO.** Se configura casi todo. El usuario trae sus propios
modelos y servidores. Se usa "así nomas" sin abrir nada: defaults de inferencia
listos (EdgeTTS, inferencia local ONNX+Vulkan, mmBERT ONNX). Nada de modelo/
servidor hardcodeado sin override por config.
- Check Ponytail: ¿hay modelo/URL/servidor hardcodeado sin override de config? → marca.
- Check Ponytail: ¿los defaults de inferencia requieren setup manual para arrancar? → marca (debe andar zero-config).

**P2 — Linux primero.** Windows en segundo plano (no testeado). Usar una librería
multiplataforma de directorios de app (ej. `platformdirs`) para config/data/cache,
NO hardcodear APPDATA ni XDG manualmente.
- Check Ponytail: ¿hay `if windows`/`APPDATA` o rutas XDG hardcodeadas en vez de
  `platformdirs`? → marca o converter a `platformdirs`.

**P3 — Divertido (teatro).** Voces con personalidades extremas, NUNCA suenan
a bot. Entretenido + mensaje profundo.
- Check Ponytail: ¿la generación creativa de voces fuerza un schema JSON rígido
  (result_type) en vez de free-form? → marca (pydantic-ai solo valida estructurado
  en `ShouldInterrupt`, ver §4b).

**P4 — Útil.** Voces con rol se organizan según necesidad del usuario: asumen
info, crean docs/planes, organizan otras voces, actualizan items de trabajo.
- **Regla de no-preguntar:** las voces NO preguntan al usuario a cada rato. Solo
  preguntan cuando es 100% necesario Y no se puede resolver investigando o
  leyendo archivos (tools de lectura, memoria, archivos del proyecto). Por
  defecto asumen/infieren antes de preguntar.
- Nota de riesgo: "asumir información" puede generar artifacts incorrectos;
  documentar, no prohibir.
- Check Ponytail: ¿un plugin bloquea la utilidad tras acoplarse al core en vez de por evento? → marca (debe ser extensible por evento).

**P5 — Rubber Ducky.** Ayuda a reflexionar y decidir mejor, de forma entretenida.
- Check Ponytail: ¿el sistema responde siempre en vez de dejar pensar? → revisar clasificador IGNORE.

**P6 — Reactivo (mínima latencia).** Responde lo antes posible: streaming de
datos, async, y solo responde cuando se necesita (clasificador EXECUTE/IGNORE).
- **Defaults = modelos pequeños:** el modelo de inferencia por defecto es
  pequeño y configurable (ej. `ternary-bonsai` 1.7B, <1GB). mmBERT y afines
  corren bien en cualquier hardware. Calidad = opt-in; velocidad = default.
- **Anti-duplicación de plugins:** NO debe haber 2 plugins de agente (uno HTTP,
  otro ONNX) que hagan lo mismo. La fuente de inferencia (HTTP server local,
  ONNX+Vulkan, etc.) se abstrae detrás de UNA interfaz/provider; el backend se
  elige por config, no por tener 2 plugins distintos.
- Check Ponytail: ¿un hop de evento hace I/O bloqueante o espera fuera de asyncio? → marca.
- Check Ponytail: ¿un stream de tokens/audio pasa por `emit()` en vez de data plane (§1)? → marca.
- Check Ponytail: ¿hay 2 plugins que implementan lo mismo con backends distintos
  (HTTP vs ONNX) en vez de un provider configurable? → marca (viola anti-dup).
- Tensión P1↔P6: los defaults deben ser los MÁS RÁPIDOS aceptables, no los de
  mejor calidad. Calidad = opt-in.

**P7 — Voz primero.** Microfono/audio es entrada por defecto, no texto. La
salida debe ser speech-friendly (sin markdown/tablas/ texto largo que el TTS
destroza). El input es ASR con errores → clasificador y voces robustas a ruido.
- Check Ponytail: ¿la generación de voz contiene markdown/tablas o texto >~40 palabras por turno? → marca.
- Check Ponytail: ¿el clasificador asume input limpio (no ASR ruidoso)? → marca.

**Prioridad actual: PREPARAR PARA EL STREAM.** El foco inmediato es tener
Kateto corriendo EN VIVO (dev-stream) de forma demo-able, no completar P1/P2 del
SPEC original. Las refactors de SPEC_2 se priorizan por lo que habilita el loop
en vivo: data/control plane (§1), generate→Jane (§2), mixer+interrupt (§3), y
cerrar tests rotos para tener señal de verdad. Hot-reload ya removido (§4a) por
no ser necesario para stream.

### 4g. Flujo de auditoría (Ponytail) ✅ PASADA INICIAL COMPLETADA
1. ~~Tras cada cambio en `kateto/`, correr `ponytail-audit`.~~ La auditoría
   inicial ya se ejecutó (ver §4e). A partir de ahora, ponytail se aplica como
   criterio de revisión en cada cambio, no como tool standalone.
2. Por cada marca: clasificar como (a) over-engineering o (b) desvío filosófico
   (§4f).
3. Si no hay justificación de runtime (latencia/seguridad/UX del stream),
   simplificar o alinear. No ignorar sin registro en `docs/bugs/` o PR.

---

## 5. Scope Congelado (MVP Build Week)
- NO implementar P1/P2 salvo lo elevado a P0 aquí (VoiceClassifier).
- Prioridad: loop de latencia real con servidores locales (whisper.cpp, Zonos,
  llama.cpp). El riesgo del proyecto es latencia, no arquitectura.
- **Tests rotos: REPARADOS (✅ hecho).** conversation_support.py y tests actualizados
  para usar VoiceAgent+VoiceProfile en vez de clases eliminadas. Conversación loop
  y adversarial tests pasan. player.py SyntaxError corregido.
- **§4c HTTP server (FastAPI) es el principal pendiente de arquitectura para el
  stream** (ver §4c). Sin él el dashboard no tiene backend.

---

## 6. GitHub
- Repo DESVINCULADO de GitHub (remote `origin` removido).
- Los commits funcionan localmente; no se hace push a remoto.
- Para revincular: `git remote add origin <url>`.

---

## Diff vs SPEC.md (resumen)
| Tema | SPEC.md | SPEC_2 |
|---|---|---|
| Streams (tokens/audio) | por event bus | data plane directo |
| `generate` | broadcast a P0 | **VoiceManager** (capacidades + azar con pesos, Jane fav) |
| Voces se pisan | no contemplado | `interject` + mixer concurrente |
| Hot-reload | sí | **removido** |
| Tools/Skills/MCP | manual | **FastMCP** (hecho) + pydantic-ai en voces DIFERIDO |
| Interrupción | no contemplado | Interrupt Executor polling aleatorio + `interject` |
| UI | TUI Textual | dashboard Nuxt+NuxtUI+Bun (separado) + **FastAPI server ❌ PENDIENTE** |
| Auditoría | — | **Ponytail-audit** 1 sola vez al inicio (✅ hecho) |
| Traza | source/timestamp | + trace_id, observador único |
| Workflows | generación libre | `result_type` en resultado + clasificador placeholder OFF |
