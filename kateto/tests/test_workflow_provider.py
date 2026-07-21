from __future__ import annotations

import httpx
import pytest

from kateto.core.config import PluginSettings
from kateto.providers.classifier import ClassifierProvider
from kateto.providers._models import WorkflowCandidate


@pytest.mark.asyncio
async def test_classifier_selects_a_workflow_from_dynamic_candidates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert b'"name":"project-initiation"' in body
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": '{"workflow":"project-initiation","voice":"jane","confidence":0.91}',
                    },
                }],
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ClassifierProvider(
            PluginSettings(model_endpoint="http://classifier.test", model="classifier"),
            client=client,
        )
        async with provider:
            result = await provider.select_workflow(
                "start a new project",
                candidates=(
                    WorkflowCandidate(
                        name="project-initiation",
                        voice="jane",
                        description="Start a new project and gather requirements.",
                    ),
                ),
            )

    assert result is not None
    assert result.name == "project-initiation"
    assert result.voice == "jane"
