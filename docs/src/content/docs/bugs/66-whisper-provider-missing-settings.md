---
id: 66
title: "AttributeError en WhisperProvider por atributo _settings no inicializado al consultar language"
severity: Alta
status: resolved
component: kateto/providers/whisper.py
resolved: 2026-08-29
---

## 66. AttributeError en WhisperProvider por atributo _settings no inicializado al consultar language

**Severidad:** Alta
**Componente:** `kateto/providers/whisper.py`

### Descripción

Al enviar audio transcrito a través del backend HTTP o del proceso `whisper-server`, el método `transcribe()` arrojaba la excepción:
`[whisper] Transcription error: 'WhisperProvider' object has no attribute '_settings'`

### Impacto

- Ningún audio capturado por el micrófono podía ser transcrito, bloqueando por completo la entrada de usuario.

### Causa

El constructor `WhisperProvider.__init__` recibía el objeto `settings` de configuración pero no asignaba `self._settings = settings`. Al implementar el soporte para selección de idioma y consultar `getattr(self._settings, "language", None)`, Python lanzaba un `AttributeError`.

**Solución aplicada:**

Se añadió la asignación `self._settings = settings` en `WhisperProvider.__init__`.

**Archivos:** `kateto/providers/whisper.py`
