name = "project-initiation"
description = "Initiate a project: define scope, stakeholders, objectives, and create the project charter"
voice = "Jane"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "define-project",
        "name": "Define project scope and stakeholders",
        "instructions": [
            "Identify all stakeholders: internal (team, management, departments) and external (clients, vendors)",
            "Define the project's purpose, mission, and measurable objectives",
            "Clarify the problem the project is solving and what success looks like",
            "Document the project scope, key deliverables, and constraints (budget, timeline, resources)",
            "Identify required skills, team members, and resources for the project",
        ],
        "deliverables": ["project-scope.md", "stakeholder-registry.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Doktor", "Conquest"],
        "checkpoints": [
            "All stakeholders are identified and documented",
            "Project objectives are measurable and documented",
            "Scope and constraints are clearly defined",
        ],
    },
    {
        "id": "create-charter",
        "name": "Create project charter and get approval",
        "instructions": [
            "Compile the project charter with scope, objectives, budget estimate, and timeline",
            "Define key milestones and their deliverables",
            "Establish the project calendar with key dates and deadlines",
            "Present the charter to decision makers and obtain formal approval",
            "Communicate the approved charter to the team and stakeholders",
        ],
        "deliverables": ["project-charter.md", "project-calendar.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Doktor"],
        "checkpoints": [
            "Project charter is approved by decision makers",
            "Milestones are defined with clear deliverables",
            "Team and stakeholders are informed of the project plan",
        ],
    },
]
