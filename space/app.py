from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

import gradio as gr

ProviderName = Literal["byok", "bonsai"]
MAX_BYOK_KEY_LENGTH: Final = 256


class ProviderChoiceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    provider: ProviderName
    session_key: str | None


def select_provider(raw_provider: str, raw_key: str) -> ProviderSelection:
    normalized_provider = raw_provider.strip().casefold()
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

        def reveal_key(choice: str | None) -> gr.Textbox:
            return gr.Textbox(visible=choice == "BYOK")

        def submit_choice(choice: str | None, session_key: str) -> tuple[str, gr.Textbox]:
            try:
                selection = select_provider(choice or "", session_key)
            except ProviderChoiceError as error:
                return f"**Provider selection error:** {error}", gr.Textbox(visible=choice == "BYOK")
            return accept_provider(selection.provider, selection.session_key or "", on_provider_ready), gr.Textbox(value="", visible=False)

        _ = provider.change(reveal_key, inputs=provider, outputs=key)
        _ = submit.click(submit_choice, inputs=[provider, key], outputs=[status, key])
    return app


app = create_app()


if __name__ == "__main__":
    _ = app.launch()
