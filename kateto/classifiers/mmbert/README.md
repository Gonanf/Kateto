# mmBERT Classifier Server

Intent classifier for Kateto. Embedding-similarity based (MiniLM-L6, 384-d). Stateless, no GPU training required.

## Categories

| Category | Meaning |
|---|---|
| `EXECUTE` | Directs an agent — commands, greetings to agents, questions addressed to the system |
| `IGNORE_SELF_TALK` | User thinking aloud, not addressed at anyone |
| `IGNORE_THIRD_PARTY` | User talking *about* someone, not *to* them |

## API

`POST /v1/chat/completions` — OpenAI-compatible format.

### Request

```json
{
  "model": "classifier",
  "messages": [
    {"role": "user", "content": "Hola, buen día Jane."}
  ],
  "agents": ["Jane", "Carlos", "Ana"]
}
```

| Field | Required | Notes |
|---|---|---|
| `messages` | yes | Last `user` or `system` message is classified |
| `agents` | no | List of known agent/speaker names. If any name appears in the text, `EXECUTE` gets a +0.25 logit boost. Caller must populate this from its own roster. |

### Response

```json
{
  "choices": [
    {
      "message": {
        "content": "{\"category\": \"EXECUTE\", \"confidence\": 0.82}"
      }
    }
  ]
}
```

`content` is a JSON string — parse it to get `{category, confidence}`.

To dynamically select a workflow, send candidates in the request:

```json
{
  "workflows": [
    {
      "name": "project-initiation",
      "voice": "Jane",
      "description": "Start a new project and gather requirements."
    }
  ]
}
```

The response includes the selected `workflow`, `voice`, and `workflow_confidence`.

## What the client must do

1. **Pass `agents`** — Without it, greetings like "Hola Jane" classify as `IGNORE_SELF_TALK`. With it, name-matching boosts `EXECUTE`.
2. **Parse `choices[0].message.content`** — It's a JSON string, not an object.
3. **Handle low confidence** — Confidence < 0.4 means the classifier is uncertain. Consider falling back to a larger model or asking for clarification.

## Running

```
python server.py                    # http://127.0.0.1:8091
python server.py --port 9091        # custom port
python server.py --no-vulkan        # CPU only
```
