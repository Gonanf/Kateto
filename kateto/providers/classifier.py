from __future__ import annotations

import httpx
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import Classification, ClassificationData

from ._http import HttpProvider, configured_endpoint
from ._models import (
    ChatMessage,
    ClassificationPayload,
    ClassificationResponse,
    ClassifierRequest,
)
from .errors import MalformedUpstreamResponse


class ClassifierProvider(HttpProvider):
    def __init__(
        self,
        settings: PluginSettings,
        *,
        endpoint: str | None = None,
        path: str = "/v1/chat/completions",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        super().__init__(
            provider_name="classifier",
            endpoint=configured_endpoint(
                settings,
                provider="classifier",
                use_model_endpoint=True,
                endpoint=endpoint,
            ),
            client=client,
            timeout_s=timeout_s,
        )
        self._model = settings.model
        self._path = path

    async def classify(self, text: str, *, agents: tuple[str, ...] = ()) -> ClassificationData:
        request = ClassifierRequest(
            model=self._model,
            messages=(
                ChatMessage(role="system", content="Return the classification JSON object."),
                ChatMessage(role="user", content=text),
            ),
            agents=agents,
        )
        response = await self._client_or_raise().post(
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        )
        response.raise_for_status()
        try:
            completion = ClassificationResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise MalformedUpstreamResponse(provider="classifier", reason="expected chat completion JSON") from error
        try:
            payload = ClassificationPayload.model_validate_json(completion.choices[0].message.content)
        except ValidationError:
            try:
                payload = ClassificationPayload(
                    category=Classification(completion.choices[0].message.content.strip()),
                )
            except (ValidationError, ValueError) as plain_error:
                raise MalformedUpstreamResponse(
                    provider="classifier",
                    reason="expected a three-way classification",
                ) from plain_error
        return ClassificationData(text=text, category=payload.category, confidence=payload.confidence)
