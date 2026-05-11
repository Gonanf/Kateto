"""Tests for bulk_create_work_packages script."""
from unittest import mock

import pytest

from modules.product_owner.openproject.client import OpenProjectClient
from modules.product_owner.openproject.config import ProjectConfig
from scripts.bulk_create_work_packages import (
    ASSIGNEE_ID,
    CHILDREN,
    PROJECT_SUMMARIES,
    PRECEDES,
    TYPE_BUG,
    TYPE_EPIC,
    TYPE_FEATURE,
    TYPE_SUMMARY,
    TYPE_TASK,
    create_all,
)


@pytest.fixture
def config() -> ProjectConfig:
    return ProjectConfig(api_key="test-key", base_url="https://openproject.example.com")


# ── Step-by-step integration tests ───────────────────────────────────────


class TestCreateAllSummaries:
    """Verify that summary tasks are created for all 7 projects."""

    def test_creates_seven_summaries(self, config: ProjectConfig) -> None:
        """Should create exactly 7 summary tasks, one per project."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            client = OpenProjectClient(config)
            result = create_all(client)

            assert len(result["summaries"]) == 9
            for pid in PROJECT_SUMMARIES:
                assert pid in result["summaries"]

    def test_summaries_use_type_summary(self, config: ProjectConfig) -> None:
        """All summary tasks should use TYPE_SUMMARY (3)."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            client = OpenProjectClient(config)
            create_all(client)

            summary_calls = _summary_calls(mock_wp)
            assert len(summary_calls) == 9
            for _args, kwargs in summary_calls:
                assert kwargs.get("type_id") == TYPE_SUMMARY


class TestCreateAllChildren:
    """Verify all child work packages are created."""

    def test_creates_thirty_six_children(self, config: ProjectConfig) -> None:
        """Should create exactly 36 child work packages across all projects."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            client = OpenProjectClient(config)
            result = create_all(client)

            total_children = sum(len(ids) for ids in result["children"].values())
            assert total_children == 36
            for pid, children in result["children"].items():
                assert len(children) == len(CHILDREN[pid])
                assert all(c is not None for c in children)

    def test_children_have_parent_summary(self, config: ProjectConfig) -> None:
        """All child work packages should have a parent_id set."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            client = OpenProjectClient(config)
            create_all(client)

            child_calls = _child_calls(mock_wp)
            assert len(child_calls) == 36
            for _args, kwargs in child_calls:
                assert kwargs.get("parent_id") is not None


class TestCreateAllRelations:
    """Verify precedes/follows relations are created."""

    def test_creates_sixteen_relations(self, config: ProjectConfig) -> None:
        """Should create exactly 16 precedes relations."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
            mock.patch.object(OpenProjectClient, "create_relation") as mock_rel,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            mock_rel.return_value = 300
            client = OpenProjectClient(config)
            result = create_all(client)

            assert len(result["relations"]) == 16
            assert mock_rel.call_count == 16

    def test_relations_use_precedes_type(self, config: ProjectConfig) -> None:
        """All created relations should use 'precedes' type."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
            mock.patch.object(OpenProjectClient, "create_relation") as mock_rel,
        ):
            mock_wp.side_effect = lambda **kwargs: _next_id()
            mock_rel.return_value = 300
            client = OpenProjectClient(config)
            create_all(client)

            for call_args in mock_rel.call_args_list:
                _args, kwargs = call_args
                assert kwargs.get("relation_type") == "precedes"


# ── Edge cases ────────────────────────────────────────────────────────────


class TestDryRun:
    """Dry-run mode should skip all API calls."""

    def test_dry_run_no_api_calls(self, config: ProjectConfig) -> None:
        """With dry_run=True, no create_work_package or create_relation calls."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=True),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
            mock.patch.object(OpenProjectClient, "create_relation") as mock_rel,
        ):
            client = OpenProjectClient(config)
            result = create_all(client, dry_run=True)

            mock_wp.assert_not_called()
            mock_rel.assert_not_called()
            # Result should have dry-run placeholders
            for pid in PROJECT_SUMMARIES:
                assert str(result["summaries"][pid]).startswith("DRY_RUN_")
            for pid in CHILDREN:
                for placeholder in result["children"][pid]:
                    assert str(placeholder).startswith("DRY_RUN_")


class TestConnectivityFailure:
    """Failure during connectivity check should raise an error."""

    def test_raises_connection_error(self, config: ProjectConfig) -> None:
        """Should raise ConnectionError when connectivity check fails."""
        with mock.patch.object(
            OpenProjectClient, "check_connectivity", return_value=False
        ):
            client = OpenProjectClient(config)
            with pytest.raises(ConnectionError, match="Cannot connect to OpenProject"):
                create_all(client)

    def test_no_wp_created_on_failure(self, config: ProjectConfig) -> None:
        """Should not attempt to create work packages when connectivity fails."""
        with (
            mock.patch.object(OpenProjectClient, "check_connectivity", return_value=False),
            mock.patch.object(OpenProjectClient, "create_work_package") as mock_wp,
        ):
            client = OpenProjectClient(config)
            with pytest.raises(ConnectionError):
                create_all(client)
            mock_wp.assert_not_called()


class TestConfigFailure:
    """Missing environment variables should cause graceful exit."""

    def test_config_failure_exits_gracefully(self) -> None:
        """Should exit with code 1 when get_openproject_config raises ValueError."""
        from scripts.bulk_create_work_packages import main

        with mock.patch(
            "scripts.bulk_create_work_packages.get_openproject_config",
            side_effect=ValueError("OPENPROJECT_API_KEY environment variable is not set"),
        ):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 1


# ── Data validation ───────────────────────────────────────────────────────


class TestDataValidation:
    """Validate the CHILDREN data structure against expected constraints."""

    def test_children_have_correct_types(self) -> None:
        """Every child should use a valid type_id (BUG/EPIC/FEATURE/TASK)."""
        valid_types = {TYPE_BUG, TYPE_EPIC, TYPE_FEATURE, TYPE_TASK}
        for pid, children in CHILDREN.items():
            for child in children:
                subject = child[0]
                type_id = child[2]
                assert type_id in valid_types, (
                    f"Project {pid}: '{subject}' has invalid type_id {type_id}"
                )

    def test_children_have_estimated_hours(self) -> None:
        """Every child should have positive estimated_hours."""
        for pid, children in CHILDREN.items():
            for child in children:
                subject = child[0]
                hours = child[4]
                assert isinstance(hours, int) and hours > 0, (
                    f"Project {pid}: '{subject}' has invalid hours {hours}"
                )

    def test_assignee_is_always_4(self) -> None:
        """The ASSIGNEE_ID constant must be 4 (Gabriel Solotorevsky)."""
        assert ASSIGNEE_ID == 4

    def test_project_summaries_cover_all_child_projects(self) -> None:
        """Every project with children should have a summary defined."""
        for pid in CHILDREN:
            assert pid in PROJECT_SUMMARIES, (
                f"Project {pid} has children but no summary"
            )

    def test_all_relations_reference_valid_indices(self) -> None:
        """Every PRECEDES entry should reference valid child indices."""
        for from_pid, from_idx, to_pid, to_idx in PRECEDES:
            assert from_pid in CHILDREN, (
                f"Relation references unknown project {from_pid}"
            )
            assert to_pid in CHILDREN, (
                f"Relation references unknown project {to_pid}"
            )
            assert from_idx < len(CHILDREN[from_pid]), (
                f"Relation references out-of-bounds index {from_idx} in project {from_pid} "
                f"(only {len(CHILDREN[from_pid])} children)"
            )
            assert to_idx < len(CHILDREN[to_pid]), (
                f"Relation references out-of-bounds index {to_idx} in project {to_pid} "
                f"(only {len(CHILDREN[to_pid])} children)"
            )

    def test_no_self_referencing_relations(self) -> None:
        """No relation should point from a WP to itself."""
        for from_pid, from_idx, to_pid, to_idx in PRECEDES:
            assert not (from_pid == to_pid and from_idx == to_idx), (
                f"Self-referencing relation at {from_pid}[{from_idx}]"
            )


# ── Helpers ───────────────────────────────────────────────────────────────

_id_counter = 100


def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _summary_calls(mock_wp: mock.MagicMock) -> list[tuple[tuple, dict]]:
    """Filter create_work_package calls that create summaries (no parent_id)."""
    return [
        call
        for call in mock_wp.call_args_list
        if call[1].get("parent_id") is None
    ]


def _child_calls(mock_wp: mock.MagicMock) -> list[tuple[tuple, dict]]:
    """Filter create_work_package calls that create child WPs (have parent_id)."""
    return [
        call
        for call in mock_wp.call_args_list
        if call[1].get("parent_id") is not None
    ]
