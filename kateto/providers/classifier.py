from __future__ import annotations

from dataclasses import dataclass

import httpx
import json
from pydantic import ValidationError

from kateto.core.config import PluginSettings
from kateto.core.event import Classification, ClassificationData
from kateto.core.exceptions import ProviderError

from ._http import HttpProvider, configured_endpoint
from ._local import LocalCommandProvider, _capture, _first_json
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


class LocalClassifierProvider(LocalCommandProvider):
    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        prompt = _classification_prompt(text, agents, workflows)
        try:
            payload = ClassificationPayload.model_validate(await self._run_json(prompt))
        except ValidationError as error:
            raise ProviderError(f"{type(self).__name__} returned an invalid classification") from error
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
        candidate_lines = "\n".join(
            f"- {candidate.name} (voice: {candidate.voice})"
            f"{': ' + candidate.description if candidate.description else ''}"
            for candidate in candidates
        )
        prompt = (
            "Return a JSON object with the exact schema:\n"
            '  "workflow": string or null (one of the given workflows)\n'
            '  "voice": string or null\n'
            '  "confidence": float between 0 and 1, or null\n'
            "No markdown, no extra keys.\n"
            f"Available workflows:\n{candidate_lines}\n\nText: {text}"
        )
        try:
            payload = WorkflowSelectionPayload.model_validate(await self._run_json(prompt))
        except ValidationError as error:
            raise ProviderError(f"{type(self).__name__} returned an invalid workflow selection") from error
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

    async def _run_json(self, prompt: str) -> dict:
        out = await _capture(self._argv("-p", prompt, "-n", "128", "-no-cnv"))
        data = _first_json(out)
        if data is None:
            raise ProviderError(f"{type(self).__name__} produced no JSON output")
        return data


def _classification_prompt(text: str, agents: tuple[str, ...], workflows: tuple[str, ...]) -> str:
    agent_names = ", ".join(agents) if agents else "none"
    workflow_names = ", ".join(workflows) if workflows else "none"
    return (
        "Return a JSON object with the exact schema:\n"
        '  "category": one of "EXECUTE", "IGNORE_SELF_TALK", "IGNORE_THIRD_PARTY"\n'
        f'  "voice": string or null (one of: {agent_names})\n'
        f'  "workflow": string or null (one of: {workflow_names})\n'
        '  "project_state": "new" or "already_underway"\n'
        '  "confidence": float between 0 and 1, or null\n'
        "No markdown, no extra keys.\n\n"
        f"Text: {text}"
    )


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
                ChatMessage(role="system", content=(
                    "Return a JSON object with the exact schema:\n"
                    '  "category": one of "EXECUTE", "IGNORE_SELF_TALK", "IGNORE_THIRD_PARTY"\n'
                    '  "voice": string or null (one of the given agents)\n'
                    '  "workflow": string or null (one of the given workflows)\n'
                    '  "project_state": "new" or "already_underway"\n'
                    '  "confidence": float between 0 and 1, or null\n'
                    "No markdown, no extra keys."
                )),
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
            # llama-server (and other non-OpenAI servers) append extra top-level
            # fields (__verbose, timings, usage, ...). EventModel forbids extras,
            # so we tolerate them by reading only the chat-completion content.
            _body = json.loads(response.content)
            completion = _body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            raise MalformedUpstreamResponse(provider="classifier", reason="expected chat completion JSON") from error
        try:
            payload = ClassificationPayload.model_validate_json(completion)
        except ValidationError:
            try:
                payload = ClassificationPayload(
                    category=Classification(completion.strip()),
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
            _body = json.loads(response.content)
            completion = _body["choices"][0]["message"]["content"]
            payload = WorkflowSelectionPayload.model_validate_json(completion)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValidationError) as error:
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
