"""Tests for ReadOpenProjectContext and SyncToOpenProject LangGraph nodes."""
from typing import Literal
from unittest import mock

import pytest

from modules.product_owner.states.project import (
    Asignee,
    Critery,
    Document,
    DocumentData,
    DOD,
    PBI,
    Sprint,
    SprintDraft,
    SprintTask,
)
from modules.product_owner.openproject.models import (
    OpenProjectReadContext,
    SyncReport,
)
from modules.product_owner.agents.openproject import (
    ReadOpenProjectContext,
    SyncToOpenProject,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _minimal_state(**overrides: object) -> Document:
    """Build a Document with required fields and optional overrides."""
    defaults: dict = {
        "title": "Test Project",
        "team": None,
        "data": None,
        "pbi": None,
        "dod": None,
        "draft_sprints": None,
        "completed_sprints": [],
    }
    defaults.update(overrides)
    return Document(**defaults)


PbiType = Literal["User Story", "Epic", "Task", "Bug"]
AsigneeType = Literal["Human", "Agent"]


def _pbi(
    title: str = "User login",
    type_: PbiType = "User Story",
    priority: int = 1,
) -> PBI:
    return PBI(
        type=type_,
        title=title,
        description=f"As a user, I want to {title.lower()}",
        score=5,
        priority=priority,
        notes="",
        criteries=[Critery(given_clause="G", when_clause="W", then_clause="T")],
    )


def _asignee(name: str = "Alice", type_: AsigneeType = "Human") -> Asignee:
    return Asignee(type=type_, name=name)


# ── ReadOpenProjectContext tests ──────────────────────────────────────────────


class TestReadOpenProjectContext:
    """Coverage for the ReadOpenProjectContext node."""

    def test_no_title(self) -> None:
        """Returns None context when state has no title (early exit)."""
        state = _minimal_state(title="")
        result = ReadOpenProjectContext(state)
        assert result == {"openproject_context": None}

    def test_unreachable(self) -> None:
        """Returns None context non-fatally when OpenProject is unreachable."""
        state = _minimal_state()
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = False

            result = ReadOpenProjectContext(state)

        assert result == {"openproject_context": None}

    def test_no_matching_project(self) -> None:
        """Returns None context when no project name matches."""
        state = _minimal_state(title="Unknown Project")
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = None

            result = ReadOpenProjectContext(state)

        assert result == {"openproject_context": None}

    def test_returns_context(self) -> None:
        """Returns populated OpenProjectReadContext when everything succeeds."""
        state = _minimal_state(title="Alpha")
        expected_context = OpenProjectReadContext(
            project_id=1,
            project_name="Alpha",
            existing_work_packages=[{"id": 100, "subject": "Task 1"}],
        )

        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 1
            mock_client.read_project_context.return_value = expected_context

            result = ReadOpenProjectContext(state)

        assert result == {"openproject_context": expected_context}
        mock_client.read_project_context.assert_called_once_with(1)

    def test_exception_is_non_fatal(self) -> None:
        """Returns None context when an unexpected exception occurs."""
        state = _minimal_state()
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.side_effect = RuntimeError("Boom")

            result = ReadOpenProjectContext(state)

        assert result == {"openproject_context": None}


# ── SyncToOpenProject tests ───────────────────────────────────────────────────


class TestSyncToOpenProject:
    """Coverage for the SyncToOpenProject node."""

    def test_missing_api_key(self) -> None:
        """Returns report with error when config raises ValueError."""
        state = _minimal_state()
        with mock.patch(
            "modules.product_owner.agents.openproject.get_openproject_config",
            side_effect=ValueError("OPENPROJECT_API_KEY not set"),
        ):
            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)
        assert len(report.errors) == 1
        assert "OPENPROJECT_API_KEY" in report.errors[0]

    def test_unreachable(self) -> None:
        """Returns report with error when connectivity check fails."""
        state = _minimal_state()
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = False

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)
        assert len(report.errors) == 1
        assert "Cannot connect to OpenProject" in report.errors[0]

    def test_no_project_found(self) -> None:
        """Returns report with error when project discovery returns None."""
        state = _minimal_state(title="Missing")
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = None

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)
        assert len(report.errors) == 1
        assert "No project found" in report.errors[0]

    def test_no_types_discovered(self) -> None:
        """Returns report with error when type discovery returns empty."""
        state = _minimal_state()
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ) as mock_get_config,
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {}
            mock_client.discover_priorities.return_value = {"Normal": 3}

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert len(report.errors) == 1
        assert "No work package types discovered" in report.errors[0]

    def test_empty_pbis(self) -> None:
        """Creates versions but no WPs when PBIs list is empty."""
        state = _minimal_state(
            team=[_asignee("Alice")],
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="First sprint", duration_weeks=2
                )
            ],
        )
        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ),
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"Task": 1}
            mock_client.discover_priorities.return_value = {"Normal": 3}
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            mock_client.find_or_create_version.return_value = 100

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert len(report.versions_created) == 1
        assert report.versions_created[0] == 100
        assert len(report.work_packages_created) == 0
        assert len(report.relations_created) == 0
        assert len(report.errors) == 0

    def test_with_pbi_and_sprint(self) -> None:
        """Full sync: 1 PBI + 1 sprint with 1 task creates versions, WPs, no relations."""
        state = _minimal_state(
            team=[_asignee("Alice")],
            data=DocumentData(
                description="Test",
                project_values=["V1", "V2", "V3"],
                dependencies=["D1", "D2", "D3"],
            ),
            pbi=[_pbi(title="User login")],
            dod=[
                DOD(
                    category="Code Quality",
                    dod_items=["Item 1", "Item 2", "Item 3"],
                )
            ],
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="First sprint", duration_weeks=2
                )
            ],
            completed_sprints=[
                Sprint(
                    data=SprintDraft(
                        goal="Sprint 1", description="First sprint", duration_weeks=2
                    ),
                    tasks=[
                        SprintTask(
                            title="User login - Implement form",
                            description="Build the login UI",
                            asignee=_asignee("Alice"),
                            effort_hours=8.0,
                        ),
                        SprintTask(
                            title="User login - Backend validation",
                            description="Add input validation",
                            asignee=_asignee("Bob", "Human"),
                            effort_hours=4.0,
                        ),
                        SprintTask(
                            title="User login - Write tests",
                            description="Add e2e test coverage",
                            asignee=_asignee("Alice"),
                            effort_hours=6.0,
                        ),
                    ],
                )
            ],
        )

        discovered_types = {"User Story": 1, "Task": 2, "Bug": 3}
        discovered_priorities = {"Immediate": 1, "Normal": 3}

        def mock_resolve_type(pbi_type: str, _discovered: dict) -> int | None:
            return {"User Story": 1, "Task": 2, "Bug": 3}.get(pbi_type, 1)

        def mock_resolve_priority(priority: int, _discovered: dict) -> int | None:
            return {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}.get(priority, 3)

        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ),
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = discovered_types
            mock_client.discover_priorities.return_value = discovered_priorities
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            mock_client.find_or_create_version.return_value = 100
            mock_client.resolve_type_for_pbi.side_effect = mock_resolve_type
            mock_client.resolve_priority.side_effect = mock_resolve_priority
            mock_client.create_work_package.return_value = 200
            mock_client.create_relation.return_value = 300

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        # 1 version, 4 WPs (1 PBI + 3 tasks), 0 relations (only 1 PBI)
        assert len(report.versions_created) == 1
        assert len(report.work_packages_created) == 4
        assert len(report.relations_created) == 0
        assert len(report.errors) == 0

        # Verify version creation
        mock_client.find_or_create_version.assert_called_once_with(
            project_id=42, name="Sprint 1", description="First sprint"
        )

        # Verify PBI WP creation (first call)
        pbi_call = mock_client.create_work_package.call_args_list[0]
        assert pbi_call.kwargs["subject"] == "[User Story] User login"
        assert pbi_call.kwargs["type_id"] == 1  # resolved "User Story"
        assert pbi_call.kwargs["assignee_id"] is None
        assert pbi_call.kwargs["version_id"] == 100

        # Verify task WP creation — all 3 tasks contain PBI title "User login"
        task_calls = mock_client.create_work_package.call_args_list[1:]
        assert len(task_calls) == 3
        for call in task_calls:
            assert call.kwargs["type_id"] == 2  # resolved "Task"
            assert call.kwargs["parent_id"] == 200  # linked to PBI WP
        # First task is assigned to Alice
        assert task_calls[0].kwargs["subject"] == "User login - Implement form"
        assert task_calls[0].kwargs["assignee_id"] == 10  # Alice → 10

    def test_creates_relations_with_multiple_pbis(self) -> None:
        """Creates predecessor relations when multiple sequential PBIs exist."""
        state = _minimal_state(
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="First sprint", duration_weeks=2
                )
            ],
            pbi=[
                _pbi(title="First feature", priority=1),
                _pbi(title="Second feature", priority=2),
            ],
        )

        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ),
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"User Story": 1}
            mock_client.discover_priorities.return_value = {"Normal": 3}
            mock_client.get_team_email_mapping.return_value = {}
            mock_client.find_or_create_version.return_value = 100
            mock_client.resolve_type_for_pbi.return_value = 1
            mock_client.resolve_priority.return_value = 3
            # Return different IDs for each WP so relations can be created
            mock_client.create_work_package.side_effect = [201, 202]
            mock_client.create_relation.return_value = 301

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert len(report.versions_created) == 1
        assert len(report.work_packages_created) == 2
        assert len(report.relations_created) == 1
        assert len(report.errors) == 0

        # Verify relation: 201 precedes 202
        mock_client.create_relation.assert_called_once_with(
            from_id=201,
            to_id=202,
            relation_type="precedes",
            description="Sequential dependency from sprint ordering",
        )
        assert report.relations_created[0] == (201, 202, "precedes")

    def test_skips_agent_assignees(self) -> None:
        """Agent-type team members are excluded from email resolution and not assigned."""
        state = _minimal_state(
            team=[
                _asignee("Alice", "Human"),
                _asignee("BotAgent", "Agent"),
            ],
            pbi=[_pbi(title="Core feature")],
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="S1", duration_weeks=1
                )
            ],
            completed_sprints=[
                Sprint(
                    data=SprintDraft(
                        goal="Sprint 1", description="S1", duration_weeks=1
                    ),
                    tasks=[
                        SprintTask(
                            title="Core feature - research",
                            description="Research phase",
                            asignee=_asignee("Alice"),
                            effort_hours=4.0,
                        ),
                        SprintTask(
                            title="Core feature - sub task",
                            description="Automated execution",
                            asignee=_asignee("BotAgent", "Agent"),
                            effort_hours=4.0,
                        ),
                        SprintTask(
                            title="Core feature - review",
                            description="Review results",
                            asignee=_asignee("Alice"),
                            effort_hours=2.0,
                        ),
                    ],
                )
            ],
        )

        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ),
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"User Story": 1, "Task": 2}
            mock_client.discover_priorities.return_value = {"Normal": 3}
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            mock_client.find_or_create_version.return_value = 100
            mock_client.resolve_type_for_pbi.return_value = 1
            mock_client.resolve_priority.return_value = 3
            mock_client.create_work_package.return_value = 200

            result = SyncToOpenProject(state)

        # Only "Alice" (Human) should be in the resolution call
        mock_client.get_team_email_mapping.assert_called_once_with(["Alice"])

        report = result["sync_report"]
        # Find the task WP creation call
        task_calls = [
            c
            for c in mock_client.create_work_package.call_args_list
            if c.kwargs.get("subject") == "Core feature - sub task"
        ]
        assert len(task_calls) == 1
        assert task_calls[0].kwargs["assignee_id"] is None

    def test_logs_individual_failures(self) -> None:
        """Continues with remaining work when one PBI or task fails."""
        state = _minimal_state(
            team=[_asignee("Alice")],
            pbi=[
                _pbi(title="First PBI", priority=1),
                _pbi(title="Second PBI", priority=2),
            ],
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="S1", duration_weeks=1
                )
            ],
        )

        with (
            mock.patch(
                "modules.product_owner.agents.openproject.get_openproject_config"
            ),
            mock.patch(
                "modules.product_owner.agents.openproject.OpenProjectClient"
            ) as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"User Story": 1, "Task": 2}
            mock_client.discover_priorities.return_value = {"Normal": 3}
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            mock_client.find_or_create_version.return_value = 100
            mock_client.resolve_type_for_pbi.return_value = 1
            mock_client.resolve_priority.return_value = 3
            # First PBI succeeds, second fails
            mock_client.create_work_package.side_effect = [201, None]
            mock_client.create_relation.return_value = 301

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert len(report.work_packages_created) == 1  # only first PBI succeeded
        assert len(report.errors) == 1
        assert "Second PBI" in report.errors[0]

        # Relations are skipped when not enough successive WPs exist
        assert len(report.relations_created) == 0
