from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx
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
        model_endpoint: str | None = None,
        path: str = "/v1/chat/completions",
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
    ) -> None:
        target_endpoint = endpoint or model_endpoint
        super().__init__(
            provider_name="classifier",
            endpoint=configured_endpoint(
                settings,
                provider="classifier",
                use_model_endpoint=True,
                endpoint=target_endpoint,
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


class MmBertClassifierProvider:
    """In-process mmBERT embedding similarity intent classifier."""

    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        model: str | None = None,
        use_vulkan: bool = True,
    ) -> None:
        self._settings = settings
        self._model = model or (settings.model if settings else None) or "Qdrant/all-MiniLM-L6-v2-onnx"
        self._use_vulkan = use_vulkan
        self._classifier: Any = None

    async def __aenter__(self) -> MmBertClassifierProvider:
        await self._ensure_initialized()
        return self

    async def aclose(self) -> None:
        if self._classifier is not None:
            self._classifier = None
            import gc
            gc.collect()

    async def _ensure_initialized(self) -> None:
        if self._classifier is not None:
            return
        try:
            from kateto.classifiers.mmbert.server import (
                MODEL_REPO,
                PrototypeClassifier,
                _create_session,
                _load_tokenizer,
                _resolve_model_path,
            )
        except ImportError as err:
            raise ProviderError(
                f"mmBERT classifier dependencies are missing. Install the optional feature with "
                f"`uv pip install 'kateto[classifier]'` or `uv tool install 'kateto[classifier]'` "
                f"(prebuilt binary wheels, no manual compilation needed). Error: {err}"
            ) from err

        model_ref = self._model
        tokenizer_repo = MODEL_REPO

        def _load() -> Any:
            tokenizer = _load_tokenizer(tokenizer_repo)
            model_path = _resolve_model_path(model_ref)
            session = _create_session(model_path, use_vulkan=self._use_vulkan)
            return PrototypeClassifier(session, tokenizer)

        self._classifier = await asyncio.to_thread(_load)

    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        await self._ensure_initialized()
        cat, conf = await asyncio.to_thread(
            self._classifier.classify,
            text,
            agents=list(agents) if agents else None,
        )
        return ClassificationData(
            text=text,
            category=Classification(cat),
            confidence=conf,
        )

    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        await self._ensure_initialized()
        if not candidates:
            return None
        candidate_dicts = [
            {"name": c.name, "voice": c.voice, "description": c.description or ""}
            for c in candidates
        ]
        name, voice, conf = await asyncio.to_thread(
            self._classifier.select_workflow,
            text,
            candidate_dicts,
        )
        return WorkflowSelection(name=name, voice=voice, confidence=conf)


class LlamaCppClassifierProvider:
    """Local GGUF classifier using llama-cpp-python bindings."""

    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        model_path: str | None = None,
        n_ctx: int = 2048,
        n_gpu_layers: int = -1,
    ) -> None:
        self._settings = settings
        self._model_path = model_path or (settings.model if settings else None) or ""
        self._n_ctx = n_ctx
        self._n_gpu_layers = n_gpu_layers
        self._llm: Any = None

    async def __aenter__(self) -> LlamaCppClassifierProvider:
        await self._ensure_initialized()
        return self

    async def aclose(self) -> None:
        if self._llm is not None:
            del self._llm
            self._llm = None
            import gc
            gc.collect()

    async def _ensure_initialized(self) -> None:
        if self._llm is not None:
            return
        try:
            from llama_cpp import Llama
        except ImportError as err:
            raise ProviderError(
                "llama-cpp-python is not installed. Install the optional feature with `uv pip install 'kateto[llamacpp]'` "
                "or `uv tool install 'kateto[llamacpp]'`, or connect to your local llama-server via HTTP "
                "(backend = 'http', model_endpoint = 'http://127.0.0.1:11434/v1')."
            ) from err

        if not self._model_path or not Path(self._model_path).exists():
            raise ProviderError(f"GGUF model file not found: {self._model_path}")

        def _load() -> Any:
            return Llama(
                model_path=self._model_path,
                n_ctx=self._n_ctx,
                n_gpu_layers=self._n_gpu_layers,
                verbose=False,
            )

        self._llm = await asyncio.to_thread(_load)

    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        await self._ensure_initialized()
        prompt = _classification_prompt(text, agents, workflows)

        def _run() -> str:
            response = self._llm.create_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a classifier. Always answer with a valid JSON object "
                            "matching the requested schema. No markdown formatting."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=128,
                response_format={"type": "json_object"},
            )
            return response["choices"][0]["message"]["content"]

        content = await asyncio.to_thread(_run)
        try:
            payload = ClassificationPayload.model_validate_json(content)
        except ValidationError:
            data = _first_json(content) or {}
            payload = ClassificationPayload.model_validate(data)
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
        await self._ensure_initialized()
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

        def _run() -> str:
            response = self._llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=128,
                response_format={"type": "json_object"},
            )
            return response["choices"][0]["message"]["content"]

        content = await asyncio.to_thread(_run)
        data = _first_json(content) or {}
        payload = WorkflowSelectionPayload.model_validate(data)
        if payload.workflow is None or payload.voice is None:
            return None
        return WorkflowSelection(
            name=payload.workflow,
            voice=payload.voice,
            confidence=payload.confidence,
        )


class MmBertServerProcessProvider:
    """Manages the external mmBERT classifier server process at classifiers/mmbert."""

    def __init__(
        self,
        settings: PluginSettings | None = None,
        *,
        server_dir: Path | str | None = None,
        port: int = 8091,
        host: str = "127.0.0.1",
        no_vulkan: bool = False,
    ) -> None:
        self._settings = settings or PluginSettings()
        candidate_paths = [
            Path(server_dir) if server_dir else None,
            Path(os.environ.get("MMBERT_SERVER_DIR", "")) if os.environ.get("MMBERT_SERVER_DIR") else None,
        ]
        self._server_dir = next((p for p in candidate_paths if p and p.exists()), None)
        self._port = port
        self._host = host
        self._no_vulkan = no_vulkan
        self._process: asyncio.subprocess.Process | None = None
        self._http_provider: ClassifierProvider | None = None

    async def __aenter__(self) -> MmBertServerProcessProvider:
        await self.start()
        return self

    async def aclose(self) -> None:
        await self.stop()

    async def start(self) -> None:
        endpoint = f"http://{self._host}:{self._port}"
        # Check if already running
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{endpoint}/health", timeout=1.0)
                if resp.status_code == 200:
                    self._http_provider = ClassifierProvider(self._settings, endpoint=endpoint)
                    await self._http_provider.__aenter__()
                    return
            except Exception:
                pass

        if self._server_dir and (self._server_dir / "server.py").exists():
            cmd = [
                sys.executable,
                str(self._server_dir / "server.py"),
                "--host", self._host,
                "--port", str(self._port),
            ]
        else:
            cmd = [
                sys.executable,
                "-m", "kateto.classifiers.mmbert.server",
                "--host", self._host,
                "--port", str(self._port),
            ]
        if self._no_vulkan:
            cmd.append("--no-vulkan")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as err:
            raise ProviderError(f"Failed to launch mmBERT server: {err}") from err

        async with httpx.AsyncClient() as client:
            for _ in range(40):
                await asyncio.sleep(0.5)
                if self._process.returncode is not None:
                    raise ProviderError(
                        f"mmBERT server exited prematurely with code {self._process.returncode}"
                    )
                try:
                    resp = await client.get(f"{endpoint}/health", timeout=1.0)
                    if resp.status_code == 200:
                        break
                except Exception:
                    continue
            else:
                await self.stop()
                raise ProviderError(f"Timed out waiting for mmBERT server on {endpoint}")

        self._http_provider = ClassifierProvider(self._settings, endpoint=endpoint)
        await self._http_provider.__aenter__()

    async def stop(self) -> None:
        if self._http_provider is not None:
            await self._http_provider.aclose()
            self._http_provider = None
        if self._process is not None:
            try:
                self._process.terminate()
                await self._process.wait()
            except Exception:
                pass
            self._process = None

    async def classify(
        self,
        text: str,
        *,
        agents: tuple[str, ...] = (),
        workflows: tuple[str, ...] = (),
    ) -> ClassificationData:
        if self._http_provider is None:
            raise ProviderError("mmBERT server provider not started")
        return await self._http_provider.classify(text, agents=agents, workflows=workflows)

    async def select_workflow(
        self,
        text: str,
        *,
        candidates: tuple[WorkflowCandidate, ...],
    ) -> WorkflowSelection | None:
        if self._http_provider is None:
            raise ProviderError("mmBERT server provider not started")
        return await self._http_provider.select_workflow(text, candidates=candidates)


