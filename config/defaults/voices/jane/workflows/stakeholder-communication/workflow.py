name = "stakeholder-communication"
description = "Manage stakeholder communication, status reporting, and escalation throughout the project"
voice = "Jane"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "plan-communication",
        "name": "Establish communication plan and channels",
        "instructions": [
            "Map stakeholders to their information needs, preferred channels, and frequency",
            "Define the communication cadence: daily standups, weekly status, milestone reviews",
            "Establish escalation paths for risks, blockers, and changes",
            "Set up documentation repositories and collaboration tools for the team",
            "Document who needs what information, when, and through which channel",
        ],
        "deliverables": ["communication-plan.md", "escalation-paths.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Doktor", "Conquest"],
        "checkpoints": [
            "All stakeholders have a documented communication channel and frequency",
            "Escalation paths are defined for risks and blockers",
        ],
    },
    {
        "id": "report-status",
        "name": "Report project status and manage stakeholder engagement",
        "instructions": [
            "Gather progress updates from each voice on their assigned workstreams",
            "Compile a status report covering completed milestones, current work, and next steps",
            "Identify and communicate any risks, issues, or changes to the plan",
            "Escalate critical issues through the defined escalation paths",
            "Ensure stakeholders remain informed and engaged throughout the project",
        ],
        "deliverables": ["status-report.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Doktor", "Conquest"],
        "checkpoints": [
            "Status report covers all active workstreams",
            "Risks and issues are communicated with proposed mitigations",
        ],
    },
]
