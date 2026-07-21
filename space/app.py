from collections.abc import Callable
import gradio as gr

from space.contracts import MAX_BYOK_KEY_LENGTH, ProviderChoiceError, ProviderSelection
from space.runtime import JsonRecord, SpaceRuntimeSession, create_runtime_session


def select_provider(raw_provider: str | None, raw_key: str) -> ProviderSelection:
    normalized_provider = (raw_provider or "").strip().casefold()
    match normalized_provider:
        case "byok":
            if not raw_key or not raw_key.strip():
                raise ProviderChoiceError("A BYOK key is required.")
            if raw_key != raw_key.strip():
                raise ProviderChoiceError("The BYOK key cannot start or end with whitespace.")
            if len(raw_key) > MAX_BYOK_KEY_LENGTH:
                raise ProviderChoiceError("The BYOK key exceeds the maximum length.")
            return ProviderSelection(provider="byok", session_key=raw_key)
        case "bonsai":
            return ProviderSelection(provider="bonsai", session_key=None)
        case _:
            raise ProviderChoiceError("Choose exactly BYOK or Bonsai.")


def _status(selection: ProviderSelection) -> str:
    provider_label = "BYOK" if selection.provider == "byok" else "Bonsai"
    return f"**Fixture mode · live runtime not connected · provider: {provider_label} · ready**\n\nThis adapter does not start a runtime or prompt."


def accept_provider(
    raw_provider: str,
    raw_key: str,
    on_provider_ready: Callable[[ProviderSelection], None] | None = None,
) -> str:
    selection = select_provider(raw_provider, raw_key)
    if on_provider_ready is not None:
        on_provider_ready(selection)
    return _status(selection)


def _empty_outputs() -> JsonRecord:
    return {
        "events": [],
        "notifications": [],
        "plans": [],
        "agent_statuses": [],
        "workflows": [],
        "mcp": [],
        "plugins": [],
        "artifacts": [],
    }


def _snapshot_outputs(session: SpaceRuntimeSession | None) -> JsonRecord:
    if session is None:
        return _empty_outputs()
    snapshot = session.snapshot()
    return snapshot.as_outputs()


def submit_prompt(session: SpaceRuntimeSession | None, prompt: str) -> tuple[str, JsonRecord]:
    if session is None:
        return "**Runtime unavailable:** choose BYOK or Bonsai first.", _empty_outputs()
    try:
        snapshot = session.prompt_sync(prompt)
    except (RuntimeError, ValueError) as error:
        return f"**Prompt error:** {error}", _snapshot_outputs(session)
    if snapshot.notifications:
        return "**Runtime degraded:** provider error recorded; inspect runtime state.", snapshot.as_outputs()
    return "**Runtime ready:** prompt processed through the event bus.", snapshot.as_outputs()


def _cleanup_session(session: SpaceRuntimeSession | None) -> None:
    if session is not None:
        session.close_sync()


def create_app(
    on_provider_ready: Callable[[ProviderSelection], None] | None = None,
) -> gr.Blocks:
    with gr.Blocks(title="Kateto Space") as app:
        _ = gr.Markdown("# Kateto\nChoose a provider to enter the demo.")
        _ = gr.Markdown("**Status:** fixture mode · live runtime not connected · provider choice required")
        provider = gr.Radio(
            choices=["BYOK", "Bonsai"],
            label="Provider",
            info="Your first action must be exactly one provider choice.",
            elem_id="provider-choice",
        )
        key = gr.Textbox(
            label="OpenRouter key",
            info=f"Session-only; maximum {MAX_BYOK_KEY_LENGTH} characters.",
            type="password",
            max_length=MAX_BYOK_KEY_LENGTH,
            visible=False,
            elem_id="byok-key",
        )
        submit = gr.Button("Continue", variant="primary", elem_id="provider-submit")
        status = gr.Markdown("Select BYOK or Bonsai to continue.", elem_id="provider-status")
        session_state = gr.State(value=None, delete_callback=_cleanup_session)
        prompt = gr.Textbox(label="Prompt", placeholder="Ask the team to plan work", visible=False, elem_id="prompt")
        prompt_submit = gr.Button("Send", visible=False, elem_id="prompt-submit")
        outputs = gr.JSON(value=_empty_outputs(), label="Runtime state", elem_id="runtime-state")

        def reveal_key(choice: str | None) -> gr.Textbox:
            return gr.Textbox(visible=choice == "BYOK")

        def submit_choice(
            choice: str | None,
            session_key: str,
            previous_session: SpaceRuntimeSession | None,
        ) -> tuple[str, gr.Textbox, SpaceRuntimeSession | None, gr.Textbox, gr.Button, gr.JSON]:
            try:
                selection = select_provider(choice or "", session_key)
            except ProviderChoiceError as error:
                return (
                    f"**Provider selection error:** {error}",
                    gr.Textbox(visible=choice == "BYOK"),
                    previous_session,
                    gr.Textbox(visible=False),
                    gr.Button(visible=False),
                    gr.JSON(value=_empty_outputs()),
                )
            _cleanup_session(previous_session)
            selected_session = create_runtime_session(selection)
            return (
                accept_provider(selection.provider, selection.session_key or "", on_provider_ready),
                gr.Textbox(value="", visible=False),
                selected_session,
                gr.Textbox(visible=True),
                gr.Button(visible=True),
                gr.JSON(value=_snapshot_outputs(selected_session)),
            )

        def submit_prompt_callback(
            session: SpaceRuntimeSession | None,
            value: str,
        ) -> tuple[str, JsonRecord]:
            return submit_prompt(session, value)

        _ = provider.change(reveal_key, inputs=provider, outputs=key)
        _ = submit.click(
            submit_choice,
            inputs=[provider, key, session_state],
            outputs=[status, key, session_state, prompt, prompt_submit, outputs],
        )
        _ = prompt_submit.click(
            submit_prompt_callback,
            inputs=[session_state, prompt],
            outputs=[status, outputs],
        )
    return app


app = create_app()


if __name__ == "__main__":
    _ = app.launch()
