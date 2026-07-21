from __future__ import annotations

from dataclasses import dataclass

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
    WorkflowCandidate,
    WorkflowSelectionPayload,
    WorkflowSelectionRequest,
)
from .errors import MalformedUpstreamResponse


@dataclass(frozen=True, slots=True)
class WorkflowSelection:
    name: str
    voice: str
    confidence: float | None


class ClassifierProvider(HttpProvider):
    _model: str | None
    _path: str

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

    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        request = ClassifierRequest(
            model=self._model,
            messages=(
                ChatMessage(role="system", content="Return the classification JSON object."),
                ChatMessage(role="user", content=text),
            ),
            agents=agents,
            workflows=workflows,
        )
        response = await self._client_or_raise().post(
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        )
        _ = response.raise_for_status()
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
        return ClassificationData(
            text=text,
            category=payload.category,
            confidence=payload.confidence,
            voice=payload.voice,
            workflow=payload.workflow,
            project_state=payload.project_state,
        )

    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        request = WorkflowSelectionRequest(
            model=self._model,
            messages=(ChatMessage(role="user", content=text),),
            workflows=candidates,
        )
        response = await self._client_or_raise().post(
            self._url(self._path),
            json=request.model_dump(mode="json", exclude_none=True),
            headers=self._request_headers,
        )
        _ = response.raise_for_status()
        try:
            completion = ClassificationResponse.model_validate_json(response.content)
            payload = WorkflowSelectionPayload.model_validate_json(completion.choices[0].message.content)
        except (ValidationError, IndexError) as error:
            raise MalformedUpstreamResponse(
                provider="classifier",
                reason="expected workflow selection JSON",
            ) from error
        if payload.workflow is None or payload.voice is None:
            return None
        return WorkflowSelection(
            name=payload.workflow,
            voice=payload.voice,
            confidence=(
                payload.workflow_confidence
                if payload.workflow_confidence is not None
                else payload.confidence
            ),
        )
