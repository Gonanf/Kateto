"""End-to-end integration tests for the OpenProject sync flow.

These tests verify the integration between LangGraph nodes (ReadOpenProjectContext,
SyncToOpenProject) and the Document state model without requiring a live OpenProject
server or compiling the full project creation graph.

Key design decisions:
  - All OpenProject API calls are mocked via ``unittest.mock``
  - The full graph (``PROJECT_CREATION``) is NOT imported — a pre-existing Calendar
    import error in ``modules.product_owner.agents.sprint`` blocks compilation
  - Node functions are tested directly with realistic ``Document`` state objects
  - Backward compatibility with ``generateMarkdown`` is verified explicitly
"""
import json
from contextlib import contextmanager
from typing import Iterator, Literal
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
from modules.product_owner.agents.output import generateMarkdown


# ── Test data helpers ──────────────────────────────────────────────────────────


PbiType = Literal["User Story", "Epic", "Task", "Bug"]
AsigneeType = Literal["Human", "Agent"]


def _minimal_state(**overrides: object) -> Document:
    """Build a Document with required fields and optional overrides."""
    defaults: dict = {
        "title": "E2E Test Project",
        "team": None,
        "data": None,
        "pbi": None,
        "dod": None,
        "draft_sprints": None,
        "completed_sprints": [],
    }
    defaults.update(overrides)
    return Document(**defaults)


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


def _mock_openproject_client(mocker: mock.MagicMock, **kwargs: object) -> None:
    """Configure common OpenProjectClient mock return values.

    Usage inside a ``mock.patch("...OpenProjectClient")`` context::

        mock_client = mock_client_cls.return_value
        _mock_openproject_client(mock_client, discover_types={"User Story": 1})
    """
    defaults = {
        "check_connectivity.return_value": True,
        "discover_project_by_name.return_value": 42,
        "discover_types.return_value": {"User Story": 1, "Task": 2, "Bug": 3},
        "discover_priorities.return_value": {"Immediate": 1, "Normal": 3},
        "get_team_email_mapping.return_value": {},
        "find_or_create_version.return_value": 100,
        "resolve_type_for_pbi.return_value": 1,
        "resolve_priority.return_value": 3,
        "create_work_package.return_value": 200,
        "create_relation.return_value": 300,
    }
    defaults.update(kwargs)
    for key, value in defaults.items():
        setattr(mocker, key, value)


@contextmanager
def _openproject_patches() -> Iterator[tuple[mock.MagicMock, mock.MagicMock]]:
    """Context manager with the two common mock patches.

    Yields ``(mock_get_config, mock_client_cls)``.

    Example::

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            ...
    """
    with (
        mock.patch("modules.product_owner.agents.openproject.get_openproject_config") as mock_config,
        mock.patch("modules.product_owner.agents.openproject.OpenProjectClient") as mock_client_cls,
    ):
        yield (mock_config, mock_client_cls)


# ═══════════════════════════════════════════════════════════════════════════════
# TestReadOpenProjectContextIntegration
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadOpenProjectContextIntegration:
    """Integration scenarios for the ReadOpenProjectContext node.

    These tests exercise the node with realistic Document state and mocked
    OpenProjectClient responses, verifying the full call chain from
    Document → config → client → context.
    """

    def test_read_context_with_real_state(self) -> None:
        """Read context from a fully populated Document.

        Given a Document with title, team, data, PBIs, DODs and sprints,
        and a well-behaved OpenProjectClient that returns a valid project,
        ReadOpenProjectContext should return a dict with ``openproject_context``
        set to an ``OpenProjectReadContext`` instance.
        """
        state = _minimal_state(
            title="My Real Project",
            team=[_asignee("Chaos"), _asignee("Kateto", "Agent")],
            data=DocumentData(
                description="E2E test project",
                project_values=["Quality", "Speed", "Learning"],
                dependencies=["Setup CI", "Configure DB", "Deploy infra"],
            ),
            pbi=[_pbi(title="Auth module"), _pbi(title="Dashboard", type_="Epic")],
            dod=[
                DOD(
                    category="Testing",
                    dod_items=["Unit tests", "Integration tests", "E2E tests"],
                )
            ],
        )
        expected_context = OpenProjectReadContext(
            project_id=1,
            project_name="My Real Project",
            existing_work_packages=[{"id": 10, "subject": "Existing task"}],
            existing_versions=[{"id": 20, "name": "Sprint 1"}],
        )

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 1
            mock_client.read_project_context.return_value = expected_context

            result = ReadOpenProjectContext(state)

        assert "openproject_context" in result
        ctx = result["openproject_context"]
        assert isinstance(ctx, OpenProjectReadContext)
        assert ctx.project_id == 1
        assert ctx.project_name == "My Real Project"
        assert len(ctx.existing_work_packages) == 1
        # Verify the full chain was exercised
        mock_client.check_connectivity.assert_called_once()
        mock_client.discover_project_by_name.assert_called_once_with("My Real Project")
        mock_client.read_project_context.assert_called_once_with(1)

    def test_read_context_no_existing_project(self) -> None:
        """Returns None when no matching OpenProject project exists.

        verify the Document title is used for discovery and the node
        returns empty context (non-fatal).
        """
        state = _minimal_state(title="Brand New Project")

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = None

            result = ReadOpenProjectContext(state)

        assert result == {"openproject_context": None}
        mock_client.read_project_context.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# TestSyncToOpenProjectIntegration
# ═══════════════════════════════════════════════════════════════════════════════


class TestSyncToOpenProjectIntegration:
    """Integration scenarios for the SyncToOpenProject node."""

    def test_sync_with_complete_state(self) -> None:
        """Full sync with 2 PBIs (different types), 2 sprints, 1 completed sprint.

        Verifies:
        - 2 versions created (one per SprintDraft)
        - 4 work packages (2 PBIs + 2 tasks from completed sprint)
        - 1 predecessor relation between sequential PBIs
        - Human task gets assigned, Agent task remains unassigned
        """
        state = _minimal_state(
            title="E2E Sync",
            team=[_asignee("Alice"), _asignee("Bot", "Agent")],
            data=DocumentData(
                description="Integration test project",
                project_values=["Value1", "Value2", "Value3"],
                dependencies=["Dep1", "Dep2", "Dep3"],
            ),
            pbi=[
                _pbi(title="User Story PBI", type_="User Story", priority=1),
                _pbi(title="Bug fix PBI", type_="Bug", priority=2),
            ],
            dod=[
                DOD(
                    category="Testing",
                    dod_items=["Alpha", "Beta", "Gamma"],
                )
            ],
            draft_sprints=[
                SprintDraft(goal="Sprint 1", description="First", duration_weeks=2),
                SprintDraft(goal="Sprint 2", description="Second", duration_weeks=3),
            ],
            completed_sprints=[
                Sprint(
                    data=SprintDraft(
                        goal="Sprint 1",
                        description="First sprint",
                        duration_weeks=2,
                    ),
                    tasks=[
                        SprintTask(
                            title="User Story PBI - Frontend UI",
                            description="Build the UI components",
                            asignee=_asignee("Alice"),
                            effort_hours=12.0,
                        ),
                        SprintTask(
                            title="User Story PBI - Backend API",
                            description="Implement the API endpoints",
                            asignee=_asignee("Bot", "Agent"),
                            effort_hours=8.0,
                        ),
                        SprintTask(
                            title="User Story PBI - Database schema",
                            description="Design the data model",
                            asignee=_asignee("Alice"),
                            effort_hours=6.0,
                        ),
                    ],
                )
            ],
        )

        # Custom resolve functions to map PBI types
        def mock_resolve_type(pbi_type: str, _discovered: dict) -> int | None:
            return {"User Story": 1, "Bug": 2, "Task": 3}.get(pbi_type, 1)

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {
                "User Story": 1,
                "Bug": 2,
                "Task": 3,
            }
            mock_client.discover_priorities.return_value = {
                "Immediate": 1,
                "High": 2,
                "Normal": 3,
            }
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            # Return different IDs for each version and WP
            mock_client.find_or_create_version.side_effect = [101, 102]
            mock_client.resolve_type_for_pbi.side_effect = mock_resolve_type
            mock_client.resolve_priority.return_value = 3
            # 5 IDs: 2 PBIs + 3 tasks
            mock_client.create_work_package.side_effect = [201, 202, 203, 204, 205]
            mock_client.create_relation.return_value = 301

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)

        # 2 versions created
        assert len(report.versions_created) == 2
        assert report.versions_created == [101, 102]

        # 5 WPs: 2 PBIs + 3 tasks
        assert len(report.work_packages_created) == 5
        assert report.work_packages_created == [201, 202, 203, 204, 205]

        # 1 relation (201 precedes 202)
        assert len(report.relations_created) == 1
        assert report.relations_created[0] == (201, 202, "precedes")

        # No errors
        assert len(report.errors) == 0

        # Verify version creation calls
        version_calls = mock_client.find_or_create_version.call_args_list
        assert len(version_calls) == 2
        assert version_calls[0].kwargs["name"] == "Sprint 1"
        assert version_calls[1].kwargs["name"] == "Sprint 2"

        # Verify PBI WP creation
        pbi_calls = [
            c for c in mock_client.create_work_package.call_args_list
            if c.kwargs.get("parent_id") is None
        ]
        assert len(pbi_calls) == 2
        assert pbi_calls[0].kwargs["subject"] == "[User Story] User Story PBI"
        assert pbi_calls[1].kwargs["subject"] == "[Bug] Bug fix PBI"

        # Verify task WP creation — human tasks get assigned, agent task does not
        task_calls = [
            c for c in mock_client.create_work_package.call_args_list
            if c.kwargs.get("parent_id") is not None
        ]
        assert len(task_calls) == 3
        # Frontend UI → assigned to Alice (id=10)
        assert task_calls[0].kwargs["subject"] == "User Story PBI - Frontend UI"
        assert task_calls[0].kwargs["assignee_id"] == 10
        # Backend API → Agent task → assignee is None
        assert task_calls[1].kwargs["subject"] == "User Story PBI - Backend API"
        assert task_calls[1].kwargs["assignee_id"] is None
        # Database schema → assigned to Alice (id=10)
        assert task_calls[2].kwargs["subject"] == "User Story PBI - Database schema"
        assert task_calls[2].kwargs["assignee_id"] == 10

        # Verify only Humans were sent to email resolution
        mock_client.get_team_email_mapping.assert_called_once_with(["Alice"])

    def test_sync_empty_state(self) -> None:
        """Sync a Document with no PBIs and no sprints.

        Verifies the node gracefully handles empty lists and returns a
        clean SyncReport with no errors and no creations.
        """
        state = _minimal_state(title="Empty Project")

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"Task": 1}
            mock_client.discover_priorities.return_value = {"Normal": 3}

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)
        assert len(report.versions_created) == 0
        assert len(report.work_packages_created) == 0
        assert len(report.relations_created) == 0
        assert len(report.errors) == 0

    def test_sync_handles_partial_failure(self) -> None:
        """First PBI succeeds, second PBI fails.

        Verifies the log-and-continue error handling: the report records
        1 successful WP creation and 1 error, and no relations are created
        when consecutive WPs are missing.
        """
        state = _minimal_state(
            title="Partial Failure",
            team=[_asignee("Alice")],
            pbi=[
                _pbi(title="Working PBI"),
                _pbi(title="Failing PBI"),
            ],
            draft_sprints=[
                SprintDraft(
                    goal="Sprint 1", description="Only sprint", duration_weeks=2
                )
            ],
        )

        with _openproject_patches() as (_, mock_client_cls):
            mock_client = mock_client_cls.return_value
            mock_client.check_connectivity.return_value = True
            mock_client.discover_project_by_name.return_value = 42
            mock_client.discover_types.return_value = {"User Story": 1}
            mock_client.discover_priorities.return_value = {"Normal": 3}
            mock_client.get_team_email_mapping.return_value = {"Alice": 10}
            mock_client.find_or_create_version.return_value = 100
            mock_client.resolve_type_for_pbi.return_value = 1
            mock_client.resolve_priority.return_value = 3
            # First PBI succeeds (201), second fails (None)
            mock_client.create_work_package.side_effect = [201, None]

            result = SyncToOpenProject(state)

        report = result["sync_report"]
        assert isinstance(report, SyncReport)
        assert len(report.work_packages_created) == 1
        assert report.work_packages_created[0] == 201
        assert len(report.errors) == 1
        assert "Failing PBI" in report.errors[0]
        # Relations skipped — not enough WPs
        assert len(report.relations_created) == 0

    def test_sync_preserves_generate_markdown_compatibility(self) -> None:
        """``generateMarkdown`` ignores the ``openproject_context`` field.

        The ``openproject_context`` field was added to the Document model
        after ``generateMarkdown`` was written. This test verifies that
        ``generateMarkdown`` does not error when the field is present and
        returns the expected markdown string.
        """
        state = Document(
            title="Compat Test",
            team=[_asignee("Chaos"), _asignee("Kateto", "Agent")],
            data=DocumentData(
                description="Testing backward compatibility",
                project_values=["A", "B", "C"],
                dependencies=["X", "Y", "Z"],
            ),
            pbi=[_pbi(title="Compat PBI")],
            dod=[DOD(category="Testing", dod_items=["One", "Two", "Three"])],
            draft_sprints=None,
            completed_sprints=[
                Sprint(
                    data=SprintDraft(
                        goal="Sprint 1",
                        description="Backward compat sprint",
                        duration_weeks=1,
                    ),
                    tasks=[
                        SprintTask(
                            title="Compat PBI - Task",
                            description="A task",
                            asignee=_asignee("Chaos"),
                            effort_hours=4.0,
                        ),
                        SprintTask(
                            title="Compat PBI - Review",
                            description="Review it",
                            asignee=_asignee("Kateto", "Agent"),
                            effort_hours=2.0,
                        ),
                        SprintTask(
                            title="Compat PBI - Deploy",
                            description="Ship it",
                            asignee=_asignee("Chaos"),
                            effort_hours=1.0,
                        ),
                    ],
                )
            ],
            # This is the field under test — should be silently ignored
            openproject_context=OpenProjectReadContext(
                project_id=99,
                project_name="Compat Project",
                existing_work_packages=[{"id": 1, "subject": "Old WP"}],
            ),
        )

        result = generateMarkdown(state)

        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Compat PBI" in result
        assert "Compat PBI" in result
        # The openproject_context values should NOT appear in the markdown
        assert "Compat Project" not in result
        assert "Old WP" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# TestGraphFlow  (tests WITHOUT compiling the full graph)
# ═══════════════════════════════════════════════════════════════════════════════


class TestGraphFlow:
    """Tests for graph-level concerns — serialisation, function signatures.

    These tests verify that the individual node functions fit together as
    expected without needing to compile the full ``PROJECT_CREATION`` graph.
    """

    def test_sync_report_serialization(self) -> None:
        """SyncReport round-trips through JSON serialization.

        Pydantic models used in the graph must be JSON-serializable for
        LangGraph checkpointing. This test verifies SyncReport produces
        valid JSON and can be deserialised back.
        """
        original = SyncReport(
            versions_created=[101, 102],
            milestones_created=[301],
            work_packages_created=[201, 202, 203],
            relations_created=[(201, 202, "precedes")],
            errors=["Warning: type not found"],
        )

        # Serialize via model_dump (Pydantic v2)
        data = original.model_dump()
        serialized = json.dumps(data, indent=2)
        deserialized = json.loads(serialized)

        # Reconstruct from deserialized dict
        restored = SyncReport.model_validate(deserialized)

        assert restored.versions_created == [101, 102]
        assert restored.milestones_created == [301]
        assert restored.work_packages_created == [201, 202, 203]
        assert restored.relations_created == [(201, 202, "precedes")]
        assert restored.errors == ["Warning: type not found"]
        # Verify no data was lost in transit
        assert restored.model_dump() == original.model_dump()

    def test_sync_report_empty_round_trip(self) -> None:
        """An empty SyncReport also round-trips cleanly."""
        original = SyncReport()
        data = original.model_dump()
        serialized = json.dumps(data)
        deserialized = json.loads(serialized)
        restored = SyncReport.model_validate(deserialized)
        assert restored.model_dump() == original.model_dump()

    def test_node_functions_follow_pattern(self) -> None:
        """Both nodes are plain callable functions that accept a single Document.

        The LangGraph node pattern requires:
        1. The node to be a callable (not a class)
        2. Accept a single positional argument (the state)
        3. Return a dict

        This test verifies the signature without executing any logic.
        """
        # Verify both are functions (not classes)
        assert callable(ReadOpenProjectContext)
        assert callable(SyncToOpenProject)
        # Verify they are plain functions (not bound methods, not classes)
        import inspect

        assert inspect.isfunction(ReadOpenProjectContext)
        assert inspect.isfunction(SyncToOpenProject)

        # Verify signature: (state: Document) -> dict
        read_sig = inspect.signature(ReadOpenProjectContext)
        sync_sig = inspect.signature(SyncToOpenProject)

        assert len(read_sig.parameters) == 1
        assert len(sync_sig.parameters) == 1

        # Verify the parameter name (convention is 'state')
        read_param = list(read_sig.parameters.values())[0]
        sync_param = list(sync_sig.parameters.values())[0]
        assert read_param.name == "state"
        assert sync_param.name == "state"
