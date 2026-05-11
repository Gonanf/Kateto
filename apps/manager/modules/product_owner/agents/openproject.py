"""LangGraph nodes for reading/syncing OpenProject context.

These nodes are designed to be inserted into the project creation graph:
- ``ReadOpenProjectContext`` reads current state from OpenProject before generation.
- ``SyncToOpenProject`` writes generated project data back to OpenProject (replaces create_affine).
"""
import logging

from modules.product_owner.states.project import Document
from modules.product_owner.openproject.config import get_openproject_config
from modules.product_owner.openproject.client import OpenProjectClient
from modules.product_owner.openproject.models import OpenProjectReadContext, SyncReport

logger = logging.getLogger(__name__)


def ReadOpenProjectContext(state: Document) -> dict:
    """Read current project context from OpenProject before sprint planning.

    Non-fatal: If OpenProject is unreachable or no matching project exists,
    returns empty context. The agent can still work without OpenProject data.

    Returns:
        dict with key ``openproject_context`` — an ``OpenProjectReadContext``
        instance or ``None``.
    """
    if not state.title:
        return {"openproject_context": None}

    try:
        config = get_openproject_config()
        client = OpenProjectClient(config)

        if not client.check_connectivity():
            logger.warning("OpenProject unreachable — will work without context")
            return {"openproject_context": None}

        project_id = client.discover_project_by_name(state.title)
        if project_id is None:
            logger.info(
                "No existing project found for '%s' — will create from scratch",
                state.title,
            )
            return {"openproject_context": None}

        context = client.read_project_context(project_id)
        logger.info(
            "Read OpenProject context: project=%s, WPs=%d, versions=%d, milestones=%d",
            context.project_name,
            len(context.existing_work_packages),
            len(context.existing_versions),
            len(context.existing_milestones),
        )
        return {"openproject_context": context}

    except Exception as e:
        logger.warning("Failed to read OpenProject context: %s", e)
        return {"openproject_context": None}


def SyncToOpenProject(state: Document) -> dict:
    """Synchronize all generated project data to OpenProject.

    Creates:
    - versions (from ``draft_sprints``)
    - work packages (from ``pbi``)
    - child work packages (from ``completed_sprints[*].tasks``)
    - predecessor/successor relations between sequential PBIs

    Error handling:
    - **Fail-fast** on connectivity/auth — returns immediately with error in report
    - **Log-and-continue** for individual entity failures — other entities still succeed

    Returns:
        dict with key ``sync_report`` — a ``SyncReport`` instance.
    """
    report = SyncReport()

    # 1. Connectivity check (fail-fast)
    try:
        config = get_openproject_config()
        client = OpenProjectClient(config)
    except ValueError as e:
        report.errors.append(str(e))
        return {"sync_report": report}

    if not client.check_connectivity():
        report.errors.append(
            "Cannot connect to OpenProject — check OPENPROJECT_API_KEY and OPENPROJECT_URL"
        )
        return {"sync_report": report}

    # 2. Project discovery
    project_id = client.discover_project_by_name(state.title)
    if project_id is None:
        report.errors.append(f"No project found matching '{state.title}'")
        return {"sync_report": report}

    # 3. Discover types + priorities
    discovered_types = client.discover_types(project_id)
    discovered_priorities = client.discover_priorities()

    if not discovered_types:
        report.errors.append("No work package types discovered")
        return {"sync_report": report}

    # 4. Resolve team (only Human-type team members)
    human_team = [m.name for m in (state.team or []) if m.type == "Human"]
    team_mapping = client.get_team_email_mapping(human_team)

    # 5. Create versions (sprints)
    version_ids: list[int] = []
    for sprint in state.draft_sprints or []:
        vid = client.find_or_create_version(
            project_id=project_id,
            name=sprint.goal,
            description=sprint.description,
        )
        if vid:
            version_ids.append(vid)
            report.versions_created.append(vid)
        else:
            report.errors.append(f"Failed to create version: {sprint.goal}")

    # 6. Milestones — deferred (the agent does not generate milestone data yet)

    # 7. Create work packages from PBIs
    pbi_wp_ids: dict[str, int] = {}
    for pbi in state.pbi or []:
        type_id = client.resolve_type_for_pbi(pbi.type, discovered_types)
        assignee_id = None  # PBIs are not assigned directly
        priority_id = client.resolve_priority(pbi.priority, discovered_priorities)

        wp_id = client.create_work_package(
            project_id=project_id,
            subject=f"[{pbi.type}] {pbi.title}",
            description=pbi.description,
            type_id=type_id or next(iter(discovered_types.values())),
            assignee_id=assignee_id,
            priority_id=priority_id,
            version_id=version_ids[0] if version_ids else None,
        )
        if wp_id:
            pbi_wp_ids[pbi.title] = wp_id
            report.work_packages_created.append(wp_id)
        else:
            report.errors.append(f"Failed to create WP for PBI: {pbi.title}")

    # 8. Create child work packages from sprint tasks
    for sprint in state.completed_sprints or []:
        for task in sprint.tasks:
            # Find parent PBI WP via title similarity
            parent_id: int | None = None
            for pbi in state.pbi or []:
                if pbi.title.lower() in task.title.lower() or task.title.lower() in pbi.title.lower():
                    parent_id = pbi_wp_ids.get(pbi.title)
                    break

            type_id = client.resolve_type_for_pbi("Task", discovered_types)
            assignee_id = (
                team_mapping.get(task.asignee.name)
                if task.asignee.type == "Human"
                else None
            )

            wp_id = client.create_work_package(
                project_id=project_id,
                subject=task.title,
                description=task.description,
                type_id=type_id or next(iter(discovered_types.values())),
                assignee_id=assignee_id,
                parent_id=parent_id,
            )
            if wp_id:
                report.work_packages_created.append(wp_id)
            else:
                report.errors.append(f"Failed to create task WP: {task.title}")

    # 9. Create relations between sequential work packages
    wp_ids_list = list(pbi_wp_ids.values())
    for i in range(len(wp_ids_list) - 1):
        rel_id = client.create_relation(
            from_id=wp_ids_list[i],
            to_id=wp_ids_list[i + 1],
            relation_type="precedes",
            description="Sequential dependency from sprint ordering",
        )
        if rel_id:
            report.relations_created.append(
                (wp_ids_list[i], wp_ids_list[i + 1], "precedes")
            )

    logger.info(
        "Sync complete: %d versions, %d work packages, %d relations, %d errors",
        len(report.versions_created),
        len(report.work_packages_created),
        len(report.relations_created),
        len(report.errors),
    )
    return {"sync_report": report}
