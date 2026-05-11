"""Tests for OpenProjectClient wrapper."""
from types import SimpleNamespace
from unittest import mock

import pytest

from modules.product_owner.openproject.client import OpenProjectClient
from modules.product_owner.openproject.config import ProjectConfig
from modules.product_owner.openproject.models import OpenProjectReadContext


@pytest.fixture
def config() -> ProjectConfig:
    """Return a minimal ProjectConfig for testing."""
    return ProjectConfig(
        api_key="test-key",
        base_url="https://openproject.example.com",
    )


@pytest.fixture
def config_with_team() -> ProjectConfig:
    """Return a ProjectConfig with team email mapping."""
    return ProjectConfig(
        api_key="test-key",
        base_url="https://openproject.example.com",
        team_emails={"Alice": "alice@example.com", "Bob": "bob@example.com"},
    )


class TestCheckConnectivity:
    """Tests for check_connectivity()."""

    def test_returns_true(self, config: ProjectConfig) -> None:
        """Should return True when get_projects succeeds."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.return_value = [SimpleNamespace(id=1)]

            client = OpenProjectClient(config)
            result = client.check_connectivity()
            assert result is True
            mock_client.get_projects.assert_called_once()

    def test_returns_false(self, config: ProjectConfig) -> None:
        """Should return False when get_projects raises."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.side_effect = RuntimeError("API unreachable")

            client = OpenProjectClient(config)
            result = client.check_connectivity()
            assert result is False
            mock_client.get_projects.assert_called_once()


class TestDiscoverProjectByName:
    """Tests for discover_project_by_name()."""

    def test_found(self, config: ProjectConfig) -> None:
        """Should return project ID when name matches."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.return_value = [
                SimpleNamespace(id=1, name="Alpha", identifier="alpha"),
                SimpleNamespace(id=2, name="Beta", identifier="beta"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_project_by_name("alpha")
            assert result == 1

    def test_not_found(self, config: ProjectConfig) -> None:
        """Should return None when no project matches."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.return_value = [
                SimpleNamespace(id=1, name="Alpha", identifier="alpha"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_project_by_name("Gamma")
            assert result is None

    def test_empty_list(self, config: ProjectConfig) -> None:
        """Should return None when projects list is empty."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.return_value = []

            client = OpenProjectClient(config)
            result = client.discover_project_by_name("Alpha")
            assert result is None

    def test_none_response(self, config: ProjectConfig) -> None:
        """Should return None when get_projects returns None."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_projects.return_value = None

            client = OpenProjectClient(config)
            result = client.discover_project_by_name("Alpha")
            assert result is None


class TestDiscoverTypes:
    """Tests for discover_types()."""

    def test_returns_mapping(self, config: ProjectConfig) -> None:
        """Should return {type_name: type_id} dict."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_types_by_project_id.return_value = [
                SimpleNamespace(id=1, name="Task"),
                SimpleNamespace(id=2, name="Bug"),
                SimpleNamespace(id=3, name="Feature"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_types(project_id=5)
            assert result == {"Task": 1, "Bug": 2, "Feature": 3}

    def test_returns_empty_on_exception(self, config: ProjectConfig) -> None:
        """Should return empty dict when API call fails."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_types_by_project_id.side_effect = RuntimeError("fail")

            client = OpenProjectClient(config)
            result = client.discover_types(project_id=5)
            assert result == {}


class TestDiscoverPriorities:
    """Tests for discover_priorities()."""

    def test_returns_mapping(self, config: ProjectConfig) -> None:
        """Should return {priority_name: priority_id} dict."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_priorities.return_value = [
                SimpleNamespace(id=1, name="Immediate"),
                SimpleNamespace(id=2, name="High"),
                SimpleNamespace(id=3, name="Normal"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_priorities()
            assert result == {"Immediate": 1, "High": 2, "Normal": 3}

    def test_returns_empty_on_exception(self, config: ProjectConfig) -> None:
        """Should return empty dict when API call fails."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_priorities.side_effect = RuntimeError("fail")

            client = OpenProjectClient(config)
            result = client.discover_priorities()
            assert result == {}


class TestDiscoverUsers:
    """Tests for discover_users()."""

    def test_returns_mapping(self, config: ProjectConfig) -> None:
        """Should return {email: user_id} dict."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@test.com", login="alice"),
                SimpleNamespace(id=20, email="bob@test.com", login="bob"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_users()
            assert result == {"alice@test.com": 10, "bob@test.com": 20}

    def test_caches_results(self, config: ProjectConfig) -> None:
        """Should cache users dict and only call API once."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@test.com", login="alice"),
            ]

            client = OpenProjectClient(config)
            result1 = client.discover_users()
            result2 = client.discover_users()
            assert result1 == result2
            mock_client.get_users.assert_called_once()

    def test_uses_login_fallback(self, config: ProjectConfig) -> None:
        """Should fall back to login when email is missing."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=30, email=None, login="service-bot"),
            ]

            client = OpenProjectClient(config)
            result = client.discover_users()
            assert result == {"service-bot": 30}


class TestCreateVersion:
    """Tests for create_version()."""

    def test_returns_id(self, config: ProjectConfig) -> None:
        """Should return the created version's ID."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=42)

            client = OpenProjectClient(config)
            result = client.create_version(
                project_id=5,
                name="Sprint 1",
                description="First sprint",
            )
            assert result == 42
            mock_client.post.assert_called_once()

    def test_with_dates(self, config: ProjectConfig) -> None:
        """Should pass start and end dates in payload."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=43)

            client = OpenProjectClient(config)
            result = client.create_version(
                project_id=5,
                name="Sprint 2",
                description="Second sprint",
                start_date="2026-06-01",
                end_date="2026-06-14",
            )
            assert result == 43
            call_args = mock_client.post.call_args
            assert call_args[0][0] == "projects/5/versions"
            payload = call_args[0][1]
            assert payload["startDate"] == "2026-06-01"
            assert payload["endDate"] == "2026-06-14"

    def test_returns_none_on_failure(self, config: ProjectConfig) -> None:
        """Should return None when API call fails."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.side_effect = RuntimeError("fail")

            client = OpenProjectClient(config)
            result = client.create_version(
                project_id=5,
                name="Sprint 1",
                description="First sprint",
            )
            assert result is None


class TestCreateMilestone:
    """Tests for create_milestone()."""

    def test_returns_id(self, config: ProjectConfig) -> None:
        """Should create a milestone and return its ID."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=50)

            client = OpenProjectClient(config)
            result = client.create_milestone(
                project_id=5,
                name="Release 1.0",
                description="First release",
            )
            assert result == 50
            call_args = mock_client.post.call_args
            payload = call_args[0][1]
            assert "Milestone:" in payload["name"]

    def test_with_date(self, config: ProjectConfig) -> None:
        """Should include end date when provided."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=51)

            client = OpenProjectClient(config)
            result = client.create_milestone(
                project_id=5,
                name="Release 2.0",
                description="Second release",
                date="2026-07-01",
            )
            assert result == 51
            call_args = mock_client.post.call_args
            payload = call_args[0][1]
            assert payload["endDate"] == "2026-07-01"


class TestFindOrCreateVersion:
    """Tests for find_or_create_version()."""

    def test_finds_existing(self, config: ProjectConfig) -> None:
        """Should return existing version ID when found by name."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_versions.return_value = [
                SimpleNamespace(id=10, name="Sprint 1"),
                SimpleNamespace(id=20, name="Sprint 2"),
            ]

            client = OpenProjectClient(config)
            result = client.find_or_create_version(
                project_id=5,
                name="Sprint 1",
                description="First sprint",
            )
            assert result == 10
            mock_client.get_versions.assert_called_once()
            mock_client.post.assert_not_called()

    def test_creates_when_not_found(self, config: ProjectConfig) -> None:
        """Should create version when not found."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_versions.return_value = [
                SimpleNamespace(id=10, name="Sprint 1"),
            ]
            mock_client.post.return_value = SimpleNamespace(id=30)

            client = OpenProjectClient(config)
            result = client.find_or_create_version(
                project_id=5,
                name="Sprint 2",
                description="Second sprint",
            )
            assert result == 30
            mock_client.post.assert_called_once()


class TestCreateWorkPackage:
    """Tests for create_work_package()."""

    def test_returns_id(self, config: ProjectConfig) -> None:
        """Should create a work package using the library method and return its ID."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.create_workpackage.return_value = SimpleNamespace(id=100)

            client = OpenProjectClient(config)
            result = client.create_work_package(
                project_id=5,
                subject="Implement login",
                description="Add login page",
                type_id=1,
            )
            assert result == 100
            mock_client.create_workpackage.assert_called_once_with(
                project_id=5,
                subject="Implement login",
                description="Add login page",
                type_id=1,
                assignee_id=None,
                priority_id=None,
                version_id=None,
                parent_id=None,
                estimated_time=None,
            )

    def test_with_optional_fields(self, config: ProjectConfig) -> None:
        """Should pass optional fields to the library method."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.create_workpackage.return_value = SimpleNamespace(id=101)

            client = OpenProjectClient(config)
            result = client.create_work_package(
                project_id=5,
                subject="Fix bug",
                description="Fix the bug",
                type_id=2,
                assignee_id=10,
                priority_id=1,
                version_id=20,
                parent_id=99,
                estimated_hours=8,
            )
            assert result == 101
            mock_client.create_workpackage.assert_called_once_with(
                project_id=5,
                subject="Fix bug",
                description="Fix the bug",
                type_id=2,
                assignee_id=10,
                priority_id=1,
                version_id=20,
                parent_id=99,
                estimated_time="PT8H",
            )

    def test_returns_none_on_failure(self, config: ProjectConfig) -> None:
        """Should return None when API call fails."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.create_workpackage.side_effect = RuntimeError("fail")

            client = OpenProjectClient(config)
            result = client.create_work_package(
                project_id=5,
                subject="Fail task",
                description="Will fail",
                type_id=1,
            )
            assert result is None


class TestCreateRelation:
    """Tests for create_relation()."""

    def test_creates_valid_relation(self, config: ProjectConfig) -> None:
        """Should create a valid relation and return ID."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=200)

            client = OpenProjectClient(config)
            result = client.create_relation(
                from_id=10, to_id=20, relation_type="follows"
            )
            assert result == 200
            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            assert args[0] == "work_packages/10/relations"
            payload = args[1]
            assert payload["type"] == "follows"
            assert payload["_links"]["to"]["href"] == "/api/v3/work_packages/20"

    def test_rejects_invalid_type(self, config: ProjectConfig) -> None:
        """Should return None for invalid relation type."""
        client = OpenProjectClient(config)
        result = client.create_relation(
            from_id=10, to_id=20, relation_type="invalid_type"
        )
        assert result is None

    def test_with_description(self, config: ProjectConfig) -> None:
        """Should pass description to API."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.post.return_value = SimpleNamespace(id=201)

            client = OpenProjectClient(config)
            result = client.create_relation(
                from_id=10, to_id=20, relation_type="blocks", description="Because reasons"
            )
            assert result == 201
            mock_client.post.assert_called_once()
            args, kwargs = mock_client.post.call_args
            assert args[0] == "work_packages/10/relations"
            payload = args[1]
            assert payload["type"] == "blocks"
            assert payload["description"] == "Because reasons"
            assert payload["_links"]["to"]["href"] == "/api/v3/work_packages/20"


class TestUserIdByEmail:
    """Tests for user_id_by_email()."""

    def test_found(self, config: ProjectConfig) -> None:
        """Should return user ID when email exists."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@test.com", login="alice"),
            ]

            client = OpenProjectClient(config)
            result = client.user_id_by_email("alice@test.com")
            assert result == 10

    def test_not_found(self, config: ProjectConfig) -> None:
        """Should return None when email not found."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@test.com", login="alice"),
            ]

            client = OpenProjectClient(config)
            result = client.user_id_by_email("unknown@test.com")
            assert result is None


class TestResolveTypeForPbi:
    """Tests for resolve_type_for_pbi()."""

    def test_exact_match_case_insensitive(self, config: ProjectConfig) -> None:
        """Should match type name case-insensitively."""
        discovered = {"Task": 1, "Bug": 2, "Feature": 3}
        client = OpenProjectClient(config)
        result = client.resolve_type_for_pbi("bug", discovered)
        assert result == 2

    def test_substring_match(self, config: ProjectConfig) -> None:
        """Should match via substring when exact fails."""
        discovered = {"User Story": 1, "Technical Task": 2}
        client = OpenProjectClient(config)
        result = client.resolve_type_for_pbi("Story", discovered)
        assert result == 1

    def test_fallback_to_first(self, config: ProjectConfig) -> None:
        """Should return first available type when no match."""
        discovered = {"Task": 1, "Bug": 2}
        client = OpenProjectClient(config)
        result = client.resolve_type_for_pbi("Unknown", discovered)
        assert result == 1

    def test_no_types_returns_none(self, config: ProjectConfig) -> None:
        """Should return None when discovered_types is empty."""
        client = OpenProjectClient(config)
        result = client.resolve_type_for_pbi("Task", {})
        assert result is None


class TestResolvePriority:
    """Tests for resolve_priority()."""

    def test_maps_immediate(self, config: ProjectConfig) -> None:
        """Should map priority 1 to Immediate."""
        discovered = {"Immediate": 1, "High": 2, "Normal": 3}
        client = OpenProjectClient(config)
        result = client.resolve_priority(1, discovered)
        assert result == 1

    def test_maps_high(self, config: ProjectConfig) -> None:
        """Should map priority 2 to High."""
        discovered = {"Immediate": 1, "High": 2, "Normal": 3}
        client = OpenProjectClient(config)
        result = client.resolve_priority(2, discovered)
        assert result == 2

    def test_maps_very_low(self, config: ProjectConfig) -> None:
        """Should map priority 5 to Very Low."""
        discovered = {"Immediate": 1, "Normal": 3, "Very Low": 5}
        client = OpenProjectClient(config)
        result = client.resolve_priority(5, discovered)
        assert result == 5

    def test_fallback_to_normal(self, config: ProjectConfig) -> None:
        """Should fall back to Normal when mapped priority not found."""
        discovered = {"Normal": 3, "High": 2}
        client = OpenProjectClient(config)
        result = client.resolve_priority(1, discovered)
        assert result == 3


class TestGetTeamEmailMapping:
    """Tests for get_team_email_mapping()."""

    def test_resolves_members(self, config_with_team: ProjectConfig) -> None:
        """Should resolve names to user IDs using config and API."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@example.com", login="alice"),
                SimpleNamespace(id=20, email="bob@example.com", login="bob"),
            ]

            client = OpenProjectClient(config_with_team)
            result = client.get_team_email_mapping(["Alice", "Bob"])
            assert result == {"Alice": 10, "Bob": 20}

    def test_skips_unresolved(self, config_with_team: ProjectConfig) -> None:
        """Should skip members whose email is not found in OpenProject."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get_users.return_value = [
                SimpleNamespace(id=10, email="alice@example.com", login="alice"),
            ]

            client = OpenProjectClient(config_with_team)
            result = client.get_team_email_mapping(["Alice", "Bob"])
            assert result == {"Alice": 10}
            assert "Bob" not in result


class TestReadProjectContext:
    """Tests for read_project_context()."""

    def test_returns_context_with_data(self, config: ProjectConfig) -> None:
        """Should return populated OpenProjectReadContext."""
        project_id = 5

        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value

            def mock_get(resource: str, payload=None):
                if "wiki" in resource:
                    raise RuntimeError("Wiki module disabled")
                if "members" in resource:
                    return [SimpleNamespace(id=1, name="Alice")]
                if "versions" in resource:
                    return [
                        SimpleNamespace(id=10, name="Sprint 1"),
                        SimpleNamespace(id=11, name="Milestone: Release 1.0"),
                    ]
                return SimpleNamespace(
                    id=project_id,
                    name="Test Project",
                    description={"raw": "A project for testing"},
                )

            mock_client.get.side_effect = mock_get
            mock_client.get_workpackages_by_project_id.return_value = [
                SimpleNamespace(id=100, subject="Task 1"),
                SimpleNamespace(id=101, subject="Task 2"),
            ]

            client = OpenProjectClient(config)
            context = client.read_project_context(project_id)

            assert isinstance(context, OpenProjectReadContext)
            assert context.project_id == 5
            assert context.project_name == "Test Project"
            assert context.project_description == "A project for testing"
            assert len(context.existing_work_packages) == 2
            assert len(context.existing_versions) == 2
            assert len(context.existing_milestones) == 1
            assert context.existing_milestones[0].get("name") == "Milestone: Release 1.0"
            assert len(context.team_members) == 1

    def test_handles_api_failure(self, config: ProjectConfig) -> None:
        """Should return context with defaults when API fails."""
        with mock.patch(
            "modules.product_owner.openproject.client.ApiClient"
        ) as mock_api:
            mock_client = mock_api.return_value
            mock_client.get.side_effect = RuntimeError("API unreachable")

            client = OpenProjectClient(config)
            context = client.read_project_context(project_id=99)

            assert isinstance(context, OpenProjectReadContext)
            assert context.project_id == 99
            assert context.project_name == ""
            assert context.existing_work_packages == []
            assert context.existing_versions == []
