from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kateto.core.config import PluginSettings
from kateto.core.event import Classification
from kateto.core.exceptions import ProviderError
from kateto.plugins.executor.classifier import ClassifierExecutor
from kateto.providers._models import WorkflowCandidate
from kateto.providers.classifier import (
    LlamaCppClassifierProvider,
    MmBertClassifierProvider,
)


@pytest.mark.asyncio
async def test_mmbert_classifier_provider_classifies_and_selects_workflow():
    # Given: a mock PrototypeClassifier
    mock_clf = MagicMock()
    mock_clf.classify.return_value = ("EXECUTE", 0.95)
    mock_clf.select_workflow.return_value = ("project-initiation", "jane", 0.92)

    provider = MmBertClassifierProvider(PluginSettings())
    provider._classifier = mock_clf

    # When: classifying text
    result = await provider.classify("start the project", agents=("jane", "doktor"))

    # Then:
    assert result.category == Classification.EXECUTE
    assert result.confidence == 0.95
    assert result.text == "start the project"

    # When: selecting workflow
    candidates = (
        WorkflowCandidate(name="project-initiation", voice="jane", description="initiate"),
        WorkflowCandidate(name="sprint-planning", voice="doktor", description="plan"),
    )
    sel = await provider.select_workflow("start the project", candidates=candidates)

    # Then:
    assert sel is not None
    assert sel.name == "project-initiation"
    assert sel.voice == "jane"
    assert sel.confidence == 0.92


@pytest.mark.asyncio
async def test_llamacpp_classifier_provider_classifies_with_mocked_llm():
    # Given: mock Llama instance
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"category": "EXECUTE", "confidence": 0.88, "voice": "jane", "workflow": null, "project_state": "new"}'
                }
            }
        ]
    }

    provider = LlamaCppClassifierProvider(PluginSettings(model="/path/model.gguf"))
    provider._llm = mock_llm

    # When: classifying text
    result = await provider.classify("organize the backlog")

    # Then:
    assert result.category == Classification.EXECUTE
    assert result.confidence == 0.88


def test_mmbert_server_fails_with_actionable_error_without_hub_deps():
    # Given: huggingface-hub / tokenizers unavailable
    from kateto.classifiers.mmbert import server as mmbert_server

    with (
        patch.object(mmbert_server, "hf_hub_download", None),
        patch.object(mmbert_server, "Tokenizer", None),
    ):
        # When / Then: guard raises an install hint, not "'NoneType' is not callable"
        with pytest.raises(RuntimeError, match=r"kateto\[classifier\]"):
            mmbert_server._require_hub_deps()
        with pytest.raises(RuntimeError, match=r"kateto\[classifier\]"):
            mmbert_server._load_tokenizer("Qdrant/all-MiniLM-L6-v2-onnx")


@pytest.mark.asyncio
async def test_classifier_executor_selects_mmbert_backend():    # Given: settings with backend="mmbert"
    settings = PluginSettings(backend="mmbert")
    executor = ClassifierExecutor(settings)

    # When: enabling with mocked MmBertClassifierProvider
    with patch("kateto.providers.MmBertClassifierProvider") as mock_provider_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_provider_cls.return_value = mock_instance
        await executor.enable()

        assert executor._classifier == mock_instance
        mock_instance.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_classifier_executor_selects_llamacpp_backend():
    # Given: settings with backend="llamacpp"
    settings = PluginSettings(backend="llamacpp")
    executor = ClassifierExecutor(settings)

    # When: enabling with mocked LlamaCppClassifierProvider
    with patch("kateto.providers.LlamaCppClassifierProvider") as mock_provider_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_provider_cls.return_value = mock_instance
        await executor.enable()

        assert executor._classifier == mock_instance
        mock_instance.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_classifier_executor_selects_server_backend():
    # Given: settings with backend="server"
    settings = PluginSettings(backend="server")
    executor = ClassifierExecutor(settings)

    # When: enabling with mocked MmBertServerProcessProvider
    with patch("kateto.providers.MmBertServerProcessProvider") as mock_provider_cls:
        mock_instance = AsyncMock()
        mock_instance.__aenter__.return_value = mock_instance
        mock_provider_cls.return_value = mock_instance
        await executor.enable()

        assert executor._classifier == mock_instance
        mock_instance.__aenter__.assert_awaited_once()

