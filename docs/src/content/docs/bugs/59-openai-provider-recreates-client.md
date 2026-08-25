---
title: "OpenAICompatibleProvider._stream rebuilds AsyncOpenAI every call"
description: "Symptom"
---


## Symptom
Minor per-turn latency on every LLM generation (connection/handshake cost
repaid each turn).

## Root cause
`OpenAICompatibleProvider._stream` (voices/base.py:160-204) does
`client = AsyncOpenAI(api_key=..., base_url=...)` inside the method body and
`finally: await client.close()` on every generation. A new client + TLS
handshake is created per turn.

## Fix (directional, not applied)
Reuse one `AsyncOpenAI` per `(endpoint, api_key)` — module-level cache or a
single instance stored on the provider. Drop the `finally: client.close()`.

```python
from functools import lru_cache
@lru_cache(maxsize=16)
def _client(endpoint, api_key):
    return AsyncOpenAI(api_key=api_key, base_url=endpoint)
# in _stream: client = _client(self.endpoint, self.api_key)
```

## Why it matters
~20-50ms saved per turn; trivial diff. Not the main bottleneck (handoff is),
but free once you touch the streaming path.

## Ceiling
lru_cache keyed on (endpoint, api_key) is fine for a handful of voices.
If per-voice client config grows, hold the client on the provider instance
instead.
