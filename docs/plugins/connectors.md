# Connector Plugins

Plugins that integrate external services via event getter/setter patterns.

## Communication Pattern

Connectors use a getter/setter event pattern with async routing:

- **Getter**: Plugin listens for an event (`on_get_calendar_events`) and responds by emitting another event with the data
- **Setter**: Plugin listens for an event with data to write/create in the external service

Connectors use a `reply_to` field in event contracts: when a voice requests data, the connector processes it and emits the response back to the requesting voice's queue using the `reply_to` target.

### Secrets

All credentials go in `.env` — never in `config.toml`.

## Plugins

### `connector_calendar` (P0)
Google Calendar integration via OAuth2 installed-app flow.

- Reads/writes calendar events
- Token cached in `config/kateto/secrets/`
- Listens to getter/setter events for calendar operations

### `connector_google_meet` (P0)
Google Meet integration.

- Joins meetings
- Captures meeting audio (routes through `audio_input_meet`)

### `connector_cli` (P0)
Terminal command execution.

- Commands restricted to an **allow-list** in `config.toml`
- No arbitrary shell execution
- Security boundary: the allow-list is the only permitted commands

### `connector_discord` (P2 — Postergated)
Discord voice channel integration. Postergated.

### `connector_openproject` (P2 — Postergated)
OpenProject integration for project management. Postergated.
