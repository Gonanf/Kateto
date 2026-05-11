"""
Bulk-create all TODO-derived work packages across OpenProject projects.
Usage: uv run python -m scripts.bulk_create_work_packages
"""
import logging
import sys
from modules.product_owner.openproject.config import get_openproject_config
from modules.product_owner.openproject.client import OpenProjectClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────
ASSIGNEE_ID = 4  # Gabriel Solotorevsky

# Type mapping
TYPE_BUG = 7
TYPE_FEATURE = 4
TYPE_EPIC = 5
TYPE_TASK = 1
TYPE_SUMMARY = 3

# Priority mapping
PRIORITY_LOW = 7
PRIORITY_NORMAL = 8
PRIORITY_HIGH = 9
PRIORITY_IMMEDIATE = 10

# ── Data ─────────────────────────────────────────────────

# project_id -> (summary_subject, summary_description)
PROJECT_SUMMARIES: dict[int, tuple[str, str]] = {
    3: ("KATETO - Infrastructure & Cross-cutting",
        "Master work package tracking all infrastructure and cross-cutting TODO items for the KATETO platform."),
    10: ("Manager - Product Owner & Tools",
         "Master work package tracking all Manager and Product Owner TODO items."),
    14: ("Orchestator - ASR, Discord & Noctalia",
         "Master work package tracking all Orchestator TODO items."),
    13: ("Classifier - Model Experiments",
         "Master work package tracking all Classifier TODO items."),
    16: ("TTS - Engine Experiments",
         "Master work package tracking all TTS TODO items."),
    12: ("Spin The Wheel - UI & Integration",
         "Master work package tracking all Spin The Wheel TODO items."),
    15: ("Frontend - Agent Display & Avatar",
         "Master work package tracking all Frontend TODO items."),
}

# Each child: (subject, description, type_id, priority_id, estimated_hours)
CHILDREN: dict[int, list[tuple[str, str, int, int, int]]] = {
    3: [  # KATETO (id=3) — 13 items
        ("Fix Flash Attention 2 with ROCm setup",
         "Flash Attention 2 has compatibility issues with ROCm 7.2 on AMD GPU. Needs investigation and patching to work with the current torch ROCm setup.",
         TYPE_BUG, PRIORITY_HIGH, 12),
        ("Core: Allow MCPs (mempalace, Context7, DDG, i_have_time, affine, cronometer)",
         "Enable MCP tool integration for the core agent system: MemPalace memory, Context7 docs, DuckDuckGo search, i-have-time calendar, AFFiNE docs, and cronometer.",
         TYPE_FEATURE, PRIORITY_HIGH, 20),
        ("Core: Node in graph to call Product Owner",
         "Add a LangGraph node that routes to the Product Owner agent for task scheduling decisions when needed during execution.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("Core: Talker/Dreamer -> cronometer",
         "Connect Talker and Dreamer agents to cronometer for time-aware execution planning and hour assignment.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("Deep Researcher: New agent for deep research",
         "Create a dedicated Deep Researcher agent that performs thorough multi-source research (DuckDuckGo, MemPalace, Context7) before generating responses.",
         TYPE_EPIC, PRIORITY_HIGH, 32),
        ("Core: Integrate Deep Researcher",
         "Wire the new Deep Researcher agent into the core LangGraph as a callable sub-agent.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("Core: Send Discord messages",
         "Implement Discord message sending capability for core agent notifications, alerts, and reminders.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
        ("Core: Multi-speaker conversations",
         "Enable multi-speaker conversation support in the core agent for group discussions and meetings.",
         TYPE_FEATURE, PRIORITY_HIGH, 32),
        ("Core: Vision tool for screen/window",
         "Add vision capability to capture, analyze, and understand screen/window content using a custom model.",
         TYPE_FEATURE, PRIORITY_HIGH, 32),
        ("XAVIER: Philosophical conversational agent",
         "Create XAVIER agent specialized in philosophical dialogue, moodboards, brainstorming, and LaTeX document generation.",
         TYPE_EPIC, PRIORITY_LOW, 32),
        ("Automation: Search TODOs -> OpenProject with AI descriptions",
         "Automate scanning all TODO.md files across the monorepo and creating detailed OpenProject work packages with AI-generated descriptions.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
        ("Core: OBS replay via websockets",
         "Integrate OBS Studio replay buffer control via websockets for clip capture (last N seconds).",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
        ("Is Busy: Discord reminders, cancel/reschedule",
         "When the agent is busy, send Discord reminders and handle cancel/reschedule workflows.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
    ],
    10: [  # Manager (id=10) — 6 items
        ("PO: Complete Is Busy incremental scheduling",
         "Complete the Is Busy incremental scheduling feature for the Product Owner agent including work hours, personal events, and event updates.",
         TYPE_FEATURE, PRIORITY_HIGH, 20),
        ("PO: CRUD operations (GetProject/GetSprint/GetTODO etc.)",
         "Implement full CRUD operations for Product Owner: GetProject, GetSprint, GetTODO, CompleteItem, RescheduleItem, CreateItem, SetItem, AssignInvestedHours.",
         TYPE_FEATURE, PRIORITY_HIGH, 32),
        ("PO: Noctalia topbar plugin",
         "Build a Noctalia plugin with a topbar for Product Owner status display and context modification.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("PO: MCPs (mempalace, Context7, DuckDuckGo, affine)",
         "Enable MCP tools for Product Owner agent: MemPalace memory, Context7 documentation, DuckDuckGo search, AFFiNE workspace.",
         TYPE_FEATURE, PRIORITY_HIGH, 20),
        ("PO: Integrate Deep Researcher as first step",
         "Make Deep Researcher the first step in the Product Owner workflow for informed sprint/project decisions.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("PO: Workflow for UML, SRR, ERD, Use cases",
         "Create Product Owner workflow that generates UML diagrams, SRR documents, ERDs, and use case specifications.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
    ],
    14: [  # Orchestator (id=14) — 4 items
        ("Replace realtimestt with custom ASR (granite speech)",
         "Replace faster-whisper RealtimeSTT with a custom ASR solution using granite speech model for better performance and control.",
         TYPE_FEATURE, PRIORITY_HIGH, 32),
        ("Multi-speaker Discord calls",
         "Support multi-speaker Discord voice calls in the orchestrator for group conversation routing.",
         TYPE_FEATURE, PRIORITY_HIGH, 32),
        ("Noctalia plugin: halt routing",
         "Add Noctalia plugin to halt audio routing when triggered (privacy/pause mode).",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("Noctalia plugin: work mode with screenshots",
         "Add Noctalia plugin for work mode that periodically captures screenshots for context awareness.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
    ],
    13: [  # Classifier (id=13) — 1 item
        ("Experiment with lightweight Bonsai 1.7B model",
         "Test and benchmark the lightweight Bonsai 1.7B model as an alternative to the current BERT-based classifier for intent detection.",
         TYPE_TASK, PRIORITY_NORMAL, 12),
    ],
    16: [  # TTS (id=16) — 1 item
        ("Experiment with different TTS engine",
         "Evaluate alternative TTS engines (XTTS, Bark, CosyVoice, etc.) for quality and latency improvements over the current Coqui TTS.",
         TYPE_TASK, PRIORITY_NORMAL, 12),
    ],
    12: [  # Spin The Wheel (id=12) — 9 items
        ("Add configuration tab with gRPC CreateProject parameters",
         "Add a configuration tab in Spin The Wheel UI that exposes gRPC CreateProject parameters (idea, team, description, disponibility).",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
        ("Fix: Product Owner progress not displaying",
         "Bug fix: Product Owner progress indicator is not showing in the Spin The Wheel UI during project creation.",
         TYPE_BUG, PRIORITY_HIGH, 12),
        ("Add filters (Games, New Projects, Projects)",
         "Add category filters to Spin The Wheel item panel: Games, New Projects, Projects.",
         TYPE_FEATURE, PRIORITY_LOW, 12),
        ("Make wheel bigger",
         "Increase the spin wheel diameter for better visual impact in OBS streaming.",
         TYPE_TASK, PRIORITY_LOW, 4),
        ("Add background image + OBS integration",
         "Add customizable background image support to Spin The Wheel and OBS streaming integration.",
         TYPE_FEATURE, PRIORITY_LOW, 12),
        ("Add confetti animation",
         "Add confetti animation effect when the wheel lands on a selected item.",
         TYPE_TASK, PRIORITY_LOW, 4),
        ("Remove reset button",
         "Remove the reset button from the Spin The Wheel UI (or replace with a more intuitive action).",
         TYPE_TASK, PRIORITY_LOW, 4),
        ("Additional context for winning item",
         "When a wheel item is selected, show more details: description, links, time estimate, etc.",
         TYPE_FEATURE, PRIORITY_NORMAL, 12),
        ("Connect to Product Owner to pick tasks",
         "Integrate Spin The Wheel with the Product Owner agent to dynamically pick tasks and projects.",
         TYPE_FEATURE, PRIORITY_HIGH, 20),
    ],
    15: [  # Frontend (id=15) — 2 items
        ("Divide into windows for agent display/avatar/context",
         "Split the Godot frontend into multiple windows: agent status, avatar display, context panel, and prompt input.",
         TYPE_FEATURE, PRIORITY_NORMAL, 32),
        ("Make an avatar for Kateto",
         "Design and implement a visual character avatar for the Kateto agent companion.",
         TYPE_FEATURE, PRIORITY_NORMAL, 20),
    ],
}

# The indices correspond to each child's position (0-based) in CHILDREN[project_id]
# Format: (from_project_id, from_child_index, to_project_id, to_child_index)
# "precedes" means from_item must be completed before to_item
PRECEDES: list[tuple[int, int, int, int]] = [
    # === Intra-project: KATETO ===
    (3, 1, 3, 4),   # MCPs (idx 1) -> Deep Researcher (idx 4) — needs MCP tools first
    (3, 1, 3, 6),   # MCPs (idx 1) -> Discord (idx 6) — needs MCP framework
    (3, 4, 3, 5),   # Deep Researcher (idx 4) -> Integrate (idx 5) — create before integrating
    (3, 6, 3, 7),   # Discord (idx 6) -> Multi-speaker (idx 7) — needs Discord first
    (3, 6, 3, 12),  # Discord (idx 6) -> Is Busy reminders (idx 12) — needs Discord first
    (3, 2, 3, 3),   # Node in graph (idx 2) -> Talker/Dreamer cronometer (idx 3) — needs the node first
    # === Intra-project: Manager ===
    (10, 1, 10, 5), # PO CRUD (idx 1) -> UML workflow (idx 5) — needs CRUD first
    # === Intra-project: Orchestator ===
    (14, 0, 14, 1), # Custom ASR (idx 0) -> Multi-speaker (idx 1) — needs ASR first
    (14, 2, 14, 3), # Noctalia halt (idx 2) -> Noctalia work mode (idx 3) — halt before work mode
    # === Intra-project: Spin The Wheel ===
    (12, 1, 12, 0), # Fix progress (idx 1) -> Config tab (idx 0) — fix before config tab
    (12, 0, 12, 8), # Config tab (idx 0) -> Connect to PO (idx 8) — needs config first
    # === Intra-project: Frontend ===
    (15, 0, 15, 1), # Windows (idx 0) -> Avatar (idx 1) — windows layout before avatar
    # === Cross-project ===
    (3, 5, 10, 4),  # Integrate Deep Researcher (KATETO idx 5) -> PO Integrate Deep Researcher (Manager idx 4)
    (3, 0, 10, 0),  # ROCm fix (KATETO idx 0) -> PO Is Busy (Manager idx 0) — needs GPU compute
    (3, 0, 14, 0),  # ROCm fix (KATETO idx 0) -> Custom ASR (Orchestator idx 0) — needs GPU compute
    (12, 8, 10, 1), # Connect to PO (Spin Wheel idx 8) -> PO CRUD (Manager idx 1) — needs the API
]


def create_all(client: OpenProjectClient, dry_run: bool = False) -> dict:
    """Create all work packages and relations. Returns a summary dict."""
    summary = {
        "summaries": {},
        "children": {},
        "relations": [],
    }

    if not client.check_connectivity():
        raise ConnectionError("Cannot connect to OpenProject")

    # Step 1: Create summary tasks
    logger.info("Step 1: Creating %d summary tasks...", len(PROJECT_SUMMARIES))
    for pid, (subject, desc) in PROJECT_SUMMARIES.items():
        if dry_run:
            summary["summaries"][pid] = f"DRY_RUN_{pid}"
            logger.info("  [DRY] Would create summary: %s", subject)
            continue
        wp_id = client.create_work_package(
            project_id=pid,
            subject=subject,
            description=desc,
            type_id=TYPE_SUMMARY,
            assignee_id=None,  # Assignee set after creation — API user may lack permissions
            priority_id=PRIORITY_NORMAL,
        )
        if wp_id:
            summary["summaries"][pid] = wp_id
            logger.info("  Created summary #%d: %s (WP %d)", pid, subject, wp_id)
        else:
            logger.error("  FAILED to create summary for project %d: %s", pid, subject)

    if not summary["summaries"]:
        raise RuntimeError("No summary tasks were created — aborting")

    # Step 2: Create child work packages
    logger.info("Step 2: Creating child work packages...")
    for pid, children in CHILDREN.items():
        summary_id = summary["summaries"].get(pid)
        if not summary_id:
            logger.warning("  No summary for project %d — skipping children", pid)
            continue
        summary["children"][pid] = []
        for idx, (subject, desc, type_id, priority_id, hours) in enumerate(children):
            if dry_run:
                summary["children"][pid].append(f"DRY_RUN_{pid}_{idx}")
                logger.info("  [DRY] Would create: %s", subject)
                continue
            wp_id = client.create_work_package(
                project_id=pid,
                subject=subject,
                description=desc,
                type_id=type_id,
                assignee_id=None,
                priority_id=priority_id,
                estimated_hours=hours,
                parent_id=summary_id,
            )
            if wp_id:
                summary["children"][pid].append(wp_id)
                logger.info("  Created WP #%d in project %d: %s", wp_id, pid, subject[:60])
            else:
                summary["children"][pid].append(None)
                logger.error("  FAILED: %s", subject[:60])

    # Step 3: Create relations
    logger.info("Step 3: Creating %d precedes relations...", len(PRECEDES))
    for from_pid, from_idx, to_pid, to_idx in PRECEDES:
        from_list = summary["children"].get(from_pid, [])
        to_list = summary["children"].get(to_pid, [])
        from_id = from_list[from_idx] if from_idx < len(from_list) else None
        to_id = to_list[to_idx] if to_idx < len(to_list) else None

        if from_id is None or to_id is None:
            logger.warning("  SKIP relation %d.%d -> %d.%d (missing WPs)",
                          from_pid, from_idx, to_pid, to_idx)
            continue

        if dry_run:
            summary["relations"].append((from_id, to_id, "precedes"))
            logger.info("  [DRY] Would create relation: %s -> %s", from_id, to_id)
            continue

        rel_id = client.create_relation(
            from_id=from_id,
            to_id=to_id,
            relation_type="precedes",
            description="Task dependency: predecessor item must be completed first.",
        )
        if rel_id:
            summary["relations"].append((from_id, to_id, "precedes"))
            logger.info("  Created relation: WP %d precedes WP %d", from_id, to_id)
        else:
            logger.error("  FAILED relation: %d -> %d", from_id, to_id)

    return summary


def print_report(summary: dict) -> None:
    """Print a summary report of what was created."""
    total_children = sum(len(ids) for ids in summary["children"].values())
    total_relations = len(summary["relations"])
    print("\n" + "=" * 60)
    print("CREATION REPORT")
    print("=" * 60)
    print(f"  Summary tasks: {len(summary['summaries'])}")
    print(f"  Child WPs:     {total_children}")
    print(f"  Relations:     {total_relations}")
    print()
    for pid, sid in summary["summaries"].items():
        children = summary["children"].get(pid, [])
        valid = sum(1 for c in children if c is not None)
        failed = sum(1 for c in children if c is None)
        print(f"  Project {pid}: Summary=WP#{sid}, Children={valid}/{len(children)}" +
              (f" ({failed} failed)" if failed else ""))
    print("=" * 60)


def main() -> None:
    try:
        config = get_openproject_config()
        client = OpenProjectClient(config)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)

    result = create_all(client)
    print_report(result)

    total_children = sum(len(ids) for ids in result["children"].values())
    total_relations = len(result["relations"])
    if total_children == 0:
        logger.error("No work packages were created!")
        sys.exit(1)
    else:
        logger.info("Successfully created all work packages.")


if __name__ == "__main__":
    main()
