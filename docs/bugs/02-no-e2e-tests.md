---
id: 2
title: "Sin tests end-to-end"
severity: Media
status: open
component: kateto/tests/
---

## 2. Sin tests end-to-end

**Severidad:** Media
**Componente:** `kateto/tests/`

Actualmente hay **33 archivos de test**, todos unitarios o con fixtures/mocks. Ningún test verifica el pipeline completo:

```
audio in → VAD → whisper → classifier → LLM → TTS → audio out
```

**Impacto:** El código que integra los componentes (especialmente `live.py` y `run_mode.py`) no tiene cobertura. Regresiones en integración real no se detectan hasta ejecución manual.

**Causa:** El MVP se construyó con Codex priorizando features sobre infraestructura de test. Los tests existentes se generaron para módulos específicos (event bus, plugin manager, VAD, backlog).

**Posible solución:** Agregar tests de integración que:
1. Inicien servidores mock de whisper/zonos/LLM
2. Ejecuten escenarios completos (transcripción → clasificación → generación → TTS)
3. Verifiquen tiempos de respuesta y eventos emitidos
