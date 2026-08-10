---
id: 47
title: Config de usuario apunta voice_llm a endpoint muerto (:8642 api_key inválida)
severity: high
status: workaround-applied
discovered: 2026-08-06
---

## Síntoma
Con el config de usuario (`~/.config/kateto/config.toml`), las voces no generaban
nada: el log mostraba `Retrying request to /chat/completions` en loop y nunca
salía `text_chunk`.

## Causa raíz
`[plugin.voice_llm]` apuntaba a `http://127.0.0.1:8642/v1` con `model=hermes-agent`
y `api_key=amogas`. Ese endpoint responde `{"error":"Invalid API key"}` → el
provider reintenta indefinidamente y la voz nunca produce tokens.

## Workaround aplicado
Se redirigió a `http://127.0.0.1:11434/v1` (`model=KatetoTalker`) en el config de
usuario. Backup en `~/.config/kateto/config.toml.bak.*`.

## Nota
No es bug de Kateto sino de config por defecto del dev. El `load_config` no valida
que el endpoint del LLM responda antes de arrancar el runtime.
