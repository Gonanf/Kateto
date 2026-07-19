name = "risk-management"
description = "Identify, analyze, and plan mitigations for project risks using the DMAIC approach"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "identify-risks",
        "name": "Identify and assess project risks",
        "instructions": [
            "Review the project scope, backlog, and calendar for potential risks",
            "Identify risks across categories: technical, resource, schedule, budget, and external dependencies",
            "Assess each risk by likelihood (Low/Medium/High) and potential impact",
            "Document assumptions that could become risks if they prove false",
            "Review historical data from past projects for recurring risk patterns",
        ],
        "deliverables": ["risk-register.md"],
        "calls_skills": ["risk-analysis"],
        "calls_voices": ["Jane", "Conquest"],
        "checkpoints": [
            "All identified risks have likelihood and impact assessed",
            "Assumptions are documented and visible",
            "Historical patterns are considered",
        ],
    },
    {
        "id": "plan-mitigations",
        "name": "Plan mitigations and assign ownership",
        "instructions": [
            "For each high-priority risk, define a concrete mitigation strategy",
            "Assign a risk owner responsible for monitoring and executing the mitigation",
            "Add risk response tasks to the backlog with clear deadlines",
            "Establish triggers that will escalate risks to Jane and stakeholders",
            "Define a regular risk review cadence to reassess and update the register",
        ],
        "deliverables": ["risk-mitigation-plan.md"],
        "calls_skills": ["risk-analysis", "backlog"],
        "calls_voices": ["Jane"],
        "checkpoints": [
            "High-priority risks have documented mitigation plans",
            "Risk owners are assigned for each mitigation",
            "Risk response tasks are added to the backlog",
            "Escalation triggers are defined",
        ],
    },
]
