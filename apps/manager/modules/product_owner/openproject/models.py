from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class OpenProjectConfig(BaseModel):
    """Configuration for OpenProject connection."""

    api_key: str
    base_url: str
    team_emails: dict[str, str] = Field(default_factory=dict)


class VersionPayload(BaseModel):
    """Payload for creating an OpenProject version (sprint)."""

    name: str
    description: str
    sharing: str = "none"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: str = "open"


class MilestonePayload(BaseModel):
    """Payload for creating a milestone version."""

    name: str
    description: str
    date: Optional[str] = None


class WorkPackagePayload(BaseModel):
    """Payload for creating a work package."""

    subject: str
    description: str
    type_id: int = Field(alias="typeId")
    project_id: int = Field(alias="projectId")
    assignee_id: Optional[int] = Field(default=None, alias="assigneeId")
    priority_id: Optional[int] = Field(default=None, alias="priorityId")
    version_id: Optional[int] = Field(default=None, alias="versionId")

    model_config = ConfigDict(populate_by_name=True)


class RelationPayload(BaseModel):
    """Payload for creating a work package relation."""

    from_id: int = Field(alias="fromId")
    to_id: int = Field(alias="toId")
    relation_type: str = Field(alias="relationType")
    description: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class TypeMapping(BaseModel):
    """Mapping between PBI types and OpenProject types."""

    pbi_type: str
    openproject_type_id: int
    openproject_type_name: str


class OpenProjectReadContext(BaseModel):
    """Context read from OpenProject for informed sprint decisions."""

    project_id: int
    project_name: str
    project_description: Optional[str] = None
    existing_work_packages: list[dict] = Field(default_factory=list)
    existing_versions: list[dict] = Field(default_factory=list)
    existing_milestones: list[dict] = Field(default_factory=list)
    wiki_content: Optional[str] = None
    team_members: list[dict] = Field(default_factory=list)


class SyncReport(BaseModel):
    """Report of a sync operation to OpenProject."""

    versions_created: list[int] = Field(default_factory=list)
    milestones_created: list[int] = Field(default_factory=list)
    work_packages_created: list[int] = Field(default_factory=list)
    relations_created: list[tuple[int, int, str]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
