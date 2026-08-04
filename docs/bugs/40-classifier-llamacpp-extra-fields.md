---
id: 40
title: ClassifierProvider.classify crashea con respuesta de llama-server (campos extra)
status: fixed (workaround aplicado, pendiente review)
severity: high
date: 2026-07-25
---

## Síntoma
Con un `llama-server` real (no OpenAI), `ClassifierProvider.classify` caía con
`MalformedUpstreamResponse: bad json` (o `ValidationError`) incluso cuando el
modelo respondía correctamente. El server responde al endpoint `/v1/chat/completions`
pero agrega campos extra en el body: `__verbose`, `timings`, `usage`, `created`,
`id`, `model`.

## Causa raíz
`ClassificationResponse` (y `ChatStreamResponse`) heredan de `ProviderModel` →
`EventModel`, que en `core/event.py` tiene
`model_config = ConfigDict(extra="forbid", frozen=True, strict=True)`.

El `classify` original hacía:

```python
completion = ClassificationResponse.model_validate_json(response.content)
```

`model_validate_json` valida **todo el body** contra el modelo estricto
(`extra="forbid"`), y los campos extra de llama-server rompen la validación →
`ValidationError` → se propaga como `MalformedUpstreamResponse`.

Además, el fallback original accedía a `completion.choices[0].message.content`
sobre lo que ya era el body parseado, lo que daba
`AttributeError: 'str' object has no attribute 'choices'`.

## Fix aplicado (workaround, sesión de debug e2e)
En `kateto/providers/classifier.py` (`classify`, ~líneas 80-103):

```python
_body = json.loads(response.content)
completion = _body["choices"][0]["message"]["content"]
```
y el fallback usa `Classification(completion.strip())` (el `completion` ya es el
string del contenido del mensaje, no el body).

Esto hace el parseo tolerante a los campos extra de llama-server: solo lee
`choices[0].message.content` y valida ese fragmento contra `ClassificationPayload`.

> Nota: el fix lo aplicó la sesión de debug del e2e, no OpenCode. Debe ser
> revisado y posiblemente generalizado a `LlamaCppChatProvider` (voz), que tiene
> el mismo patrón `model_validate_json` sobre el body completo.

## Pasos para reproducir
```bash
# Con un llama-server real que agregue campos extra:
curl -s http://127.0.0.1:11434/v1/chat/completions -d '{
  "model":"KatetoTalker","messages":[{"role":"user","content":"planifica el backlog"}],
  "max_tokens":64}' | head -c 400
# el body incluye "timings", "usage", etc. -> el classify previo crasheaba.
```

## Impacto
Sin el fix, el classifier (y por extensión todo el pipeline de decisión) no
funciona contra llama-server real. Con el fix, el classifier parsea
correctamente siempre que el modelo devuelva un JSON con el schema
`category` (ver bug 39 sobre el dispatch y el schema).

## Estado
Mitigado a nivel de parseo. Queda pendiente: (a) generalizar el fix a
`LlamaCppChatProvider`, (b) que el `ClassifierProvider` instruya al modelo a
devolver el schema `ClassificationPayload` (`category`/`voice`/`workflow`),
no solo depender del system prompt genérico.
