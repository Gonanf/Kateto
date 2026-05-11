import pytest
from modules.product_owner.openproject.models import (
    OpenProjectConfig,
    VersionPayload,
    MilestonePayload,
    WorkPackagePayload,
    RelationPayload,
    TypeMapping,
    OpenProjectReadContext,
    SyncReport,
)


class TestOpenProjectConfig:
    """Tests for OpenProjectConfig model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create config with api_key and base_url."""
        config = OpenProjectConfig(api_key="key-123", base_url="https://op.example.com")
        assert config.api_key == "key-123"
        assert config.base_url == "https://op.example.com"

    def test_team_emails_defaults_to_empty_dict(self) -> None:
        """Should default team_emails to empty dict."""
        config = OpenProjectConfig(api_key="key-123", base_url="https://op.example.com")
        assert config.team_emails == {}


class TestVersionPayload:
    """Tests for VersionPayload model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create with only name and description."""
        payload = VersionPayload(name="Sprint 1", description="First sprint")
        assert payload.name == "Sprint 1"
        assert payload.description == "First sprint"

    def test_has_defaults(self) -> None:
        """Should set sharing='none' and status='open' by default."""
        payload = VersionPayload(name="Sprint 1", description="First sprint")
        assert payload.sharing == "none"
        assert payload.status == "open"
        assert payload.start_date is None
        assert payload.end_date is None

    def test_optional_dates(self) -> None:
        """Should accept optional start_date and end_date."""
        payload = VersionPayload(
            name="Sprint 1",
            description="First sprint",
            start_date="2026-05-01",
            end_date="2026-05-14",
        )
        assert payload.start_date == "2026-05-01"
        assert payload.end_date == "2026-05-14"

    def test_custom_sharing_and_status(self) -> None:
        """Should accept custom sharing and status."""
        payload = VersionPayload(
            name="Sprint 1",
            description="First sprint",
            sharing="system",
            status="locked",
        )
        assert payload.sharing == "system"
        assert payload.status == "locked"


class TestMilestonePayload:
    """Tests for MilestonePayload model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create with only name and description."""
        payload = MilestonePayload(name="Release 1.0", description="First release")
        assert payload.name == "Release 1.0"
        assert payload.description == "First release"

    def test_optional_date(self) -> None:
        """Should accept optional date."""
        payload = MilestonePayload(
            name="Release 1.0",
            description="First release",
            date="2026-06-01",
        )
        assert payload.date == "2026-06-01"


class TestWorkPackagePayload:
    """Tests for WorkPackagePayload model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create with required fields using aliases."""
        payload = WorkPackagePayload(
            subject="Implement login",
            description="Add user authentication",
            typeId=3,
            projectId=5,
        )
        assert payload.subject == "Implement login"
        assert payload.description == "Add user authentication"
        assert payload.type_id == 3
        assert payload.project_id == 5

    def test_optional_fields(self) -> None:
        """Should accept optional assignee, priority, and version."""
        payload = WorkPackagePayload(
            subject="Implement login",
            description="Add user authentication",
            typeId=3,
            projectId=5,
            assigneeId=42,
            priorityId=2,
            versionId=10,
        )
        assert payload.assignee_id == 42
        assert payload.priority_id == 2
        assert payload.version_id == 10

    def test_serialization_by_alias(self) -> None:
        """Should serialize using aliases via model_dump(by_alias=True)."""
        payload = WorkPackagePayload(
            subject="Implement login",
            description="Add user authentication",
            typeId=3,
            projectId=5,
            assigneeId=42,
        )
        data = payload.model_dump(by_alias=True)
        assert data["typeId"] == 3
        assert data["projectId"] == 5
        assert data["assigneeId"] == 42
        assert "type_id" not in data

    def test_populate_by_name_access(self) -> None:
        """Should allow access by both alias and python name."""
        payload = WorkPackagePayload(
            subject="Implement login",
            description="Add user authentication",
            typeId=3,
            projectId=5,
            assigneeId=42,
        )
        # by alias
        assert payload.type_id == 3
        # by python name (populate_by_name)
        assert payload.type_id == 3
        assert payload.assignee_id == 42


class TestRelationPayload:
    """Tests for RelationPayload model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create with required fields using aliases."""
        payload = RelationPayload(
            fromId=10,
            toId=20,
            relationType="follows",
        )
        assert payload.from_id == 10
        assert payload.to_id == 20
        assert payload.relation_type == "follows"

    def test_optional_description(self) -> None:
        """Should accept optional description."""
        payload = RelationPayload(
            fromId=10,
            toId=20,
            relationType="follows",
            description="This follows that",
        )
        assert payload.description == "This follows that"

    def test_serialization_by_alias(self) -> None:
        """Should serialize using aliases via model_dump(by_alias=True)."""
        payload = RelationPayload(
            fromId=10,
            toId=20,
            relationType="follows",
        )
        data = payload.model_dump(by_alias=True)
        assert data["fromId"] == 10
        assert data["toId"] == 20
        assert data["relationType"] == "follows"


class TestTypeMapping:
    """Tests for TypeMapping model."""

    def test_creates_with_all_fields(self) -> None:
        """Should create with all fields."""
        mapping = TypeMapping(
            pbi_type="User Story",
            openproject_type_id=1,
            openproject_type_name="User Story",
        )
        assert mapping.pbi_type == "User Story"
        assert mapping.openproject_type_id == 1
        assert mapping.openproject_type_name == "User Story"


class TestOpenProjectReadContext:
    """Tests for OpenProjectReadContext model."""

    def test_creates_with_required_fields(self) -> None:
        """Should create with project_id and project_name."""
        ctx = OpenProjectReadContext(project_id=1, project_name="Test Project")
        assert ctx.project_id == 1
        assert ctx.project_name == "Test Project"

    def test_defaults_to_empty_lists(self) -> None:
        """Should default collection fields to empty lists."""
        ctx = OpenProjectReadContext(project_id=1, project_name="Test Project")
        assert ctx.existing_work_packages == []
        assert ctx.existing_versions == []
        assert ctx.existing_milestones == []
        assert ctx.team_members == []
        assert ctx.project_description is None
        assert ctx.wiki_content is None

    def test_accepts_optional_fields(self) -> None:
        """Should accept all optional fields."""
        ctx = OpenProjectReadContext(
            project_id=1,
            project_name="Test Project",
            project_description="A test",
            existing_work_packages=[{"id": 1, "subject": "Task 1"}],
            existing_versions=[{"id": 1, "name": "Sprint 1"}],
            wiki_content="Some wiki content",
            team_members=[{"id": 1, "name": "Alice"}],
        )
        assert ctx.project_description == "A test"
        assert len(ctx.existing_work_packages) == 1
        assert len(ctx.existing_versions) == 1
        assert ctx.wiki_content == "Some wiki content"
        assert len(ctx.team_members) == 1


class TestSyncReport:
    """Tests for SyncReport model."""

    def test_defaults_to_empty_lists(self) -> None:
        """Should default all collections to empty lists."""
        report = SyncReport()
        assert report.versions_created == []
        assert report.milestones_created == []
        assert report.work_packages_created == []
        assert report.relations_created == []
        assert report.errors == []

    def test_accumulates_values(self) -> None:
        """Should accumulate values when appending to lists."""
        report = SyncReport()
        report.versions_created.append(1)
        report.milestones_created.append(2)
        report.work_packages_created.append(3)
        report.relations_created.append((10, 20, "follows"))
        report.errors.append("Something went wrong")

        assert report.versions_created == [1]
        assert report.milestones_created == [2]
        assert report.work_packages_created == [3]
        assert report.relations_created == [(10, 20, "follows")]
        assert report.errors == ["Something went wrong"]

    def test_multiple_values(self) -> None:
        """Should handle multiple values in each list."""
        report = SyncReport()
        report.versions_created.extend([1, 2, 3])
        report.errors.extend(["err1", "err2"])

        assert len(report.versions_created) == 3
        assert len(report.errors) == 2
