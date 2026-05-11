"""OpenProject API client wrapper for the Product Owner sync."""
import logging
from typing import Iterable, Optional, cast
from openproject_api_client import ApiClient
from modules.product_owner.openproject.config import ProjectConfig
from modules.product_owner.openproject.models import OpenProjectReadContext, SyncReport

logger = logging.getLogger(__name__)


class OpenProjectClient:
    """Wraps openproject-api-client with Product Owner-specific methods."""

    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.client = ApiClient(config.base_url, config.api_key)
        self._users_cache: dict[str, int] | None = None

    def check_connectivity(self) -> bool:
        """Verify the API key is valid by fetching projects list."""
        try:
            projects = self.client.get_projects()
            return projects is not None
        except Exception as e:
            logger.warning("OpenProject connectivity check failed: %s", e)
            return False

    def discover_project_by_name(self, name: str) -> int | None:
        """Find a project by name (case-insensitive substring match). Returns project ID or None."""
        try:
            projects = self.client.get_projects()
            if not projects:
                return None
            for project in projects:
                pname = project.name or project.identifier or ""
                if name.lower() in pname.lower():
                    return project.id
            return None
        except Exception as e:
            logger.warning("Project discovery failed: %s", e)
            return None

    def discover_types(self, project_id: int) -> dict[str, int]:
        """Discover work package types for a project. Returns {type_name: type_id}."""
        try:
            types = self.client.get_types_by_project_id(project_id)
            result: dict[str, int] = {}
            for t in types:
                tname = t.name
                tid = t.id
                if tname and tid:
                    result[tname] = tid
            return result
        except Exception as e:
            logger.warning("Type discovery failed: %s", e)
            return {}

    def discover_users(self) -> dict[str, int]:
        """Discover all users. Returns {email: user_id}. Results cached."""
        if self._users_cache is not None:
            return self._users_cache
        try:
            users = self.client.get_users()
            result: dict[str, int] = {}
            for user in users:
                email = user.email or user.login or ""
                uid = user.id
                if email and uid:
                    result[email] = uid
            self._users_cache = result
            return result
        except Exception as e:
            logger.warning("User discovery failed: %s", e)
            return {}

    def discover_priorities(self) -> dict[str, int]:
        """Discover available priorities. Returns {priority_name: priority_id}."""
        try:
            priorities = self.client.get_priorities()
            result: dict[str, int] = {}
            for p in priorities:
                pname = p.name
                pid = p.id
                if pname and pid:
                    result[pname] = pid
            return result
        except Exception as e:
            logger.warning("Priority discovery failed: %s", e)
            return {}

    def _extract_id(self, response) -> int | None:
        """Extract entity ID from an API response object."""
        if hasattr(response, "id"):
            return response.id
        return None

    def create_version(self, project_id: int, name: str, description: str,
                       start_date: str | None = None, end_date: str | None = None) -> int | None:
        """Create a version (sprint) in the project. Uses generic POST since create_version() is missing from the library."""
        payload = {
            "name": name,
            "description": {"raw": description},
            "sharing": "none",
            "status": "open",
        }
        if start_date:
            payload["startDate"] = start_date
        if end_date:
            payload["endDate"] = end_date
        try:
            response = self.client.post(f"projects/{project_id}/versions", payload)
            return self._extract_id(response)
        except Exception as e:
            logger.error("Failed to create version '%s': %s", name, e)
            return None

    def create_milestone(self, project_id: int, name: str, description: str,
                         date: str | None = None) -> int | None:
        """Create a milestone as a version with milestone context."""
        payload = {
            "name": f"Milestone: {name}",
            "description": {"raw": description},
            "sharing": "none",
            "status": "open",
        }
        if date:
            payload["endDate"] = date
        try:
            response = self.client.post(f"projects/{project_id}/versions", payload)
            return self._extract_id(response)
        except Exception as e:
            logger.error("Failed to create milestone '%s': %s", name, e)
            return None

    def find_or_create_version(self, project_id: int, name: str, description: str) -> int | None:
        """Find existing version by name, or create if not found (idempotent)."""
        try:
            versions = self.client.get_versions()
            if versions:
                for v in versions:
                    if v.name == name:
                        return v.id
            return self.create_version(project_id, name, description)
        except Exception as e:
            logger.warning("find_or_create_version failed: %s", e)
            return self.create_version(project_id, name, description)

    def create_work_package(self, project_id: int, subject: str, description: str,
                            type_id: int, assignee_id: int | None = None,
                            priority_id: int | None = None, version_id: int | None = None,
                            parent_id: int | None = None,
                            estimated_hours: int | None = None) -> int | None:
        """Create a work package using the library's built-in method."""
        try:
            estimated_time = f"PT{estimated_hours}H" if estimated_hours is not None else None
            wp = self.client.create_workpackage(
                project_id=project_id,
                subject=subject,
                description=description,
                type_id=type_id,
                assignee_id=assignee_id,
                priority_id=priority_id,
                version_id=version_id,
                parent_id=parent_id,
                estimated_time=estimated_time,
            )
            return wp.id if wp else None
        except Exception as e:
            logger.error("Failed to create work package '%s': %s", subject, e)
            return None

    def create_relation(self, from_id: int, to_id: int, relation_type: str,
                        description: str | None = None) -> int | None:
        """Create a relation between two work packages.

        Uses direct POST to /api/v3/work_packages/{from_id}/relations
        since the library's generic 'relations' endpoint is not valid.
        """
        VALID_TYPES = {"precedes", "follows", "blocks", "blocked", "relates", "requires", "required"}
        if relation_type not in VALID_TYPES:
            logger.error("Invalid relation type: %s", relation_type)
            return None
        try:
            body = {
                "type": relation_type,
                "_links": {
                    "to": {"href": f"/api/v3/work_packages/{to_id}"},
                },
            }
            if description is not None:
                body["description"] = description
            response = self.client.post(f"work_packages/{from_id}/relations", body)
            return self._extract_id(response)
        except Exception as e:
            logger.error("Failed to create relation %s->%s: %s", from_id, to_id, e)
            return None

    def user_id_by_email(self, email: str) -> int | None:
        """Find a user ID by email. Uses cached users dict."""
        users = self.discover_users()
        return users.get(email)

    def resolve_type_for_pbi(self, pbi_type: str, discovered_types: dict[str, int]) -> int | None:
        """Map a PBI type string to an OpenProject type ID."""
        # Exact match (case-insensitive)
        for name, tid in discovered_types.items():
            if name.lower() == pbi_type.lower():
                return tid
        # Substring match
        for name, tid in discovered_types.items():
            if pbi_type.lower() in name.lower() or name.lower() in pbi_type.lower():
                return tid
        # Fallback: first available type
        if discovered_types:
            return next(iter(discovered_types.values()))
        return None

    def resolve_priority(self, priority: int, discovered_priorities: dict[str, int]) -> int | None:
        """Map numeric priority (1-5) to OpenProject priority ID."""
        mapping = {
            1: "Immediate",
            2: "High",
            3: "Normal",
            4: "Low",
            5: "Very Low",
        }
        name = mapping.get(priority)
        if name and name in discovered_priorities:
            return discovered_priorities[name]
        # Fallback to Normal
        return discovered_priorities.get("Normal")

    def get_team_email_mapping(self, names: list[str]) -> dict[str, int]:
        """Resolve team member names to user IDs using team_emails config."""
        result: dict[str, int] = {}
        users = self.discover_users()
        for name in names:
            email = self.config.team_emails.get(name)
            if email and email in users:
                result[name] = users[email]
            else:
                logger.warning("Could not resolve team member '%s' to a user ID", name)
        return result

    def read_project_context(self, project_id: int) -> OpenProjectReadContext:
        """Read full project context from OpenProject for informed sprint decisions."""
        context = OpenProjectReadContext(
            project_id=project_id,
            project_name="",
            existing_work_packages=[],
            existing_versions=[],
            existing_milestones=[],
            team_members=[],
        )
        try:
            project = self.client.get(f"projects/{project_id}")
            if project:
                context.project_name = getattr(project, "name", "")
                raw_desc = getattr(project, "description", None)
                if isinstance(raw_desc, dict):
                    context.project_description = raw_desc.get("raw", str(raw_desc))
                elif raw_desc is not None:
                    context.project_description = str(raw_desc)

            wps = self.client.get_workpackages_by_project_id(project_id)
            if wps:
                context.existing_work_packages = [vars(wp) for wp in wps]  # type: ignore[assignment]

            versions_resp = self.client.get(f"projects/{project_id}/versions")
            if versions_resp is not None:
                try:
                    versions_iter = cast(Iterable, versions_resp)
                    versions_list = list(versions_iter)
                    context.existing_versions = [vars(v) for v in versions_list]  # type: ignore[assignment]
                    for v in versions_list:
                        vname = getattr(v, "name", "") or ""
                        if "milestone" in vname.lower():
                            context.existing_milestones.append(vars(v))  # type: ignore[arg-type]
                except TypeError:
                    context.existing_versions = [vars(versions_resp)]  # type: ignore[assignment]

            # wiki may 404 if wiki module disabled
            try:
                wiki = self.client.get(f"projects/{project_id}/wiki")
                if wiki:
                    wiki_text = getattr(wiki, "text", None)
                    if isinstance(wiki_text, dict):
                        context.wiki_content = wiki_text.get("raw", str(wiki_text))
                    elif wiki_text is not None:
                        context.wiki_content = str(wiki_text)
                    else:
                        context.wiki_content = str(wiki)
            except Exception:
                logger.info("Wiki module not available for project %s", project_id)

            try:
                members_resp = self.client.get(f"projects/{project_id}/members")
                if members_resp is not None:
                    try:
                        members_iter = cast(Iterable, members_resp)
                        context.team_members = [vars(m) for m in members_iter]  # type: ignore[assignment]
                    except TypeError:
                        context.team_members = [vars(members_resp)]  # type: ignore[assignment]
            except Exception:
                logger.info("Could not read members for project %s", project_id)

        except Exception as e:
            logger.error("Failed to read project context: %s", e)

        return context
