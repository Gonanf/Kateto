from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kateto.providers.agent import HermesProvider


@pytest.mark.asyncio
async def test_hermes_provider_sends_conversation_id_in_body() -> None:
    # Given: a Hermes harness endpoint that requires conversation_id
    provider = HermesProvider(
        conversation_id="conv-42",
        model="hermes-model",
        endpoint="http://hermes.test/v1",
    )
    create = AsyncMock(
        return_value=type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": "hola", "tool_calls": None})},
                    ),
                ],
            },
        )()
    )
    provider._client.chat.completions.create = create
    # When: the voice asks the harness a question
    response = await provider.chat_with_tools(
        messages=[{"role": "user", "content": "hola"}],
        tools=(),
    )
    # Then: the response text is returned and the body carried conversation_id
    assert response.text == "hola"
    kwargs = create.call_args.kwargs
    assert kwargs["extra_body"] == {"conversation_id": "conv-42"}
    assert kwargs["model"] == "hermes-model"


def test_hermes_provider_base_kwargs_inject_extra_body() -> None:
    provider = HermesProvider(
        conversation_id="conv-9",
        model="hermes-model",
        endpoint="http://hermes.test/v1",
    )
    assert provider._base_kwargs(stream=False)["extra_body"] == {
        "conversation_id": "conv-9",
    }
    assert provider._base_kwargs(stream=True)["stream"] is True
