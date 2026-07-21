from __future__ import annotations

from pydantic import JsonValue

from space.app import submit_prompt
from space.contracts import ProviderSelection
from space.runtime import create_runtime_session


def test_fixture_two_prompts_project_orchestration_evidence() -> None:
    # Given: a deterministic Space runtime behind the provider gate.
    session = create_runtime_session(
        ProviderSelection(provider="bonsai", session_key=None)
    )

    # When: two prompts travel through the real event bus.
    _, first = submit_prompt(session, "map the release")
    _, second = submit_prompt(session, "prepare the launch checklist")

    # Then: structured outputs show plans, agent actions, workflow progress, and evolution.
    assert _records(first["plans"])
    assert len(_records(second["plans"])) == 2
    assert {str(agent["name"]) for agent in _records(second["agents"])} == {
        "Jane",
        "Doktor",
        "Conquest",
    }
    assert all(
        agent["actions"]
        for agent in _records(second["agents"])
        if str(agent["name"]) == "Doktor"
    )
    assert _records(second["workflows"])[0]["current_phase"] == "plan"
    assert _records(second["workflows"])[0]["task"] == "prepare the launch checklist"
    assert _records(second["workflows"])[0]["checkpoints_passed"]
    assert len(_records(second["evolution"])) == 2
    assert all(entry["artifacts"] for entry in _records(second["evolution"]))

    session.close_sync()


def test_snapshot_projection_preserves_event_name_and_source() -> None:
    # Given: one prompt has emitted a real event timeline.
    session = create_runtime_session(
        ProviderSelection(provider="byok", session_key="sk-test")
    )

    # When: the callback returns the structured presentation.
    _, outputs = submit_prompt(session, "trace the orchestration")

    # Then: the timeline remains attributable to its event source and provider model is visible.
    assert outputs["provider"] == "byok"
    assert outputs["model"] == "fixture/demo-model"
    assert all(
        event["name"] and event["source"] for event in _records(outputs["events"])
    )
    assert any(
        event["name"] == "space_plan" and event["source"] == "space_fixture_runtime"
        for event in _records(outputs["events"])
    )

    session.close_sync()


def _records(value: JsonValue) -> list[dict[str, JsonValue]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
