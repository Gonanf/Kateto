# Plan de Features Post-Ponytail

## Feature 1: MCP para que agentes modifiquen journal/memory

**Contexto:** `VoiceMemory` (kateto/voices/memory.py) ya abstrae SOUL.md, JOURNAL.md y MEMORIES.md pero solo es accesible desde `VoiceAgent`. El MCP server solo expone `send_event`.

**Qué implementar:**

| Tool MCP | Acción | ¿Ya existe en VoiceMemory? |
|----------|--------|---------------------------|
| `memory_read(source: "soul"\|"journal"\|"memories")` | Devuelve texto | `read_soul()`, `read_journal()`, `read_memories()` |
| `memory_append(target: "journal"\|"memories", entry: str)` | Agrega entrada | `append_journal()`, `append_memories()` |
| `memory_set_soul(soul: str)` | Sobrescribe SOUL | `write_soul()` |
| `journal_list` | Devuelve entradas como lista | implícito en `read_journal()` |

**Arquitectura:**
- Agregar un nuevo `MemoryMcpPlugin` (o extender `McpEventServer`)
- Inyectar `VoiceMemory` en `McpEventServer` desde `run_mode.py` donde se arma el assembly
- Las tools se registran en `self.fastmcp.add_tool()`
- Los MCP tools reciben `voice_name` como parámetro para saber qué voz modificar
- Seguridad: validar que la voz esté autorizada para ese MCP server (misma lógica que `_authorize`)

**Estimación:** ~150 líneas en `mcp_server.py` + ~20 en `run_mode.py`

---

## Feature 2: cognee como plugin de memoria vectorial

**cognee** (https://github.com/topoteretes/cognee) es un framework de memoria para AI agents con 28.1k stars, v1.4.0, Apache 2.0.

### ¿Qué ofrece?

| Capa | descripción |
|------|-------------|
| **Vector store** | Embeddings semánticos (ChromaDB, pgvector, Qdrant, LanceDB, Milvus, Weaviate) |
| **Knowledge graph** | GraphRAG con ontologías auto-generadas (Postgres, Neo4j, Neptune, Kuzudb) |
| **Session memory** | Cache rápido con sync automático al grafo permanente |
| **MCP server built-in** | `cognee-mcp` expone `remember`, `recall`, `improve`, `forget` sobre HTTP/SSE/stdio |
| **BEAM SOTA** | 0.79 en 100K tokens vs 0.735 del SOTA anterior, 0.67 en 10M tokens |

### API Core

```python
await cognee.remember("text", session_id="chat_1")   # guardar
results = await cognee.recall("query")                 # buscar
await cognee.forget(dataset="main")                    # olvidar
```

### Integración con Kateto

Actualmente `VoiceMemory` usa 3 archivos markdown planos:
- `SOUL.md` — identidad fija (~200 tokens)
- `JOURNAL.md` — evento por línea, limitado a ~500 palabras
- `MEMORIES.md` — memoria episódica por entrada, limitado a ~1500 palabras

**Propuesta: Plugin opcional `kateto/plugins/memory/cognee.py`**

```toml
[plugin.cognee_memory]
enabled = false
backend = "postgres"  # postgres | chromadb | qdrant | lancedb
# Cuando backend="postgres", todo corre en Postgres (graph + vectors + sessions)
```

```
config.toml:
embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
```

**Interface del plugin:**

```python
class CogneeMemoryPlugin(Plugin):
    async def remember(self, text: str, context: dict | None = None) -> None
    async def recall(self, query: str, limit: int = 5) -> list[str]
    async def consolidate(self) -> None
    async def forget(self, criteria: dict) -> None
```

**Estrategia de integración:**

1. **Fase 1 — Plugin paralelo:** `CogneeMemoryPlugin` se registra como plugin separado. No reemplaza nada. El agente puede optar por usar memory MCP tools (files planos) o cognee tools.
2. **Fase 2 — Reemplazo de VoiceMemory:** Cuando `plugin.cognee_memory.enabled=true`, las MCP memory tools (`memory_read`, `memory_append`, `memory_set_soul`) redirigen a cognee en vez de archivos. SOUL.md se mantiene como fuente de identidad fija.
3. **Fase 3 — Full migration:** Eliminar `VoiceMemory` legacy, migrar SOUL a metadato en cognee.

### ¿Por qué plugin y no reemplazo directo?

- cognee requiere `pysqlite3-binary` + `chromadb` (opcional) + `sentence-transformers` 
- El embedding model all-MiniLM-L6-v2 son ~400MB extra
- Para un deploy mínimo de Kateto, tener cognee como opcional permite elegir
- cognee ya tiene MCP server propio, podríamos delegar directamente

### Bloqueantes actuales

- cognee necesita una LLM configurada (`LLM_API_KEY` o provider local)
- Para Postgres backend, necesita base de datos
- El plugin de integración oficial para Claude Code usa hooks de lifecycle — habría que adaptar al event bus de Kateto

---

## Feature 3: Bonsai 27B GGUF Q1_0

**Modelo:** prism-ml/Bonsai-27B-gguf, cuantización Q1_0 (~3-4 GB en RAM)
**Propósito:** Evaluar si un modelo de 27B en quantización extrema es viable para agentes.

### Descarga

```bash
huggingface-cli download prism-ml/Bonsai-27B-gguf Q1_0.gguf --local-dir ~/models/bonsai/
```

### Configurar llama.cpp

```bash
# Verificar que llama.cpp está instalado (del provider existente en Kateto)
# El endpoint llama.cpp ya se puede configurar en kateto/config.toml
```

### Pruebas

| Prueba | Métrica | Método |
|--------|---------|--------|
| Memoria RAM | RSS (resident set size) | `ps -o rss` + `nvidia-smi` (si hay GPU) |
| Velocidad | tokens/segundo | Prompt estándar de 500 tokens, medir tiempo de generación |
| Capacidad agentica | Tool calling correcto | Evaluación con herramientas Kateto |
| Capacidad agentica | Seguimiento de instrucciones | Prompt de sistema complejo |
| Calidad de output | Coherencia vs Bonsai no cuantizado | Comparación cualitativa |

### Config de Kateto para probarlo

```toml
[plugin.llm]
enabled = true
endpoint = "http://localhost:8080/v1"  # llama.cpp server
model = "bonsai-27b-q1_0"
```

### Comandos para benchmark

```bash
# Iniciar servidor
llama-server -m ~/models/bonsai/Q1_0.gguf -c 4096 --port 8080

# Medir con llama-bench
llama-bench -m ~/models/bonsai/Q1_0.gguf -p 512 -n 128 -ngl 0

# Probar con curl
curl http://localhost:8080/v1/chat/completions \
  -d '{"model":"bonsai-27b-q1_0","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

**Estimación:** ~30 min descarga + ~15 min benchmarks
