name = "resource-planning"
description = "Plan team capacity, budget, and resource allocation for the project or sprint"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "assess-capacity",
        "name": "Assess team capacity and availability",
        "instructions": [
            "Review team members' availability including holidays, time off, and existing commitments",
            "Calculate available capacity in person-hours or story points per sprint",
            "Identify skill gaps between required skills and available team expertise",
            "Evaluate external constraints like vendor lead times and third-party dependencies",
            "Document any resource constraints that could impact delivery timelines",
        ],
        "deliverables": ["capacity-plan.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Jane", "Conquest"],
        "checkpoints": [
            "Team availability is documented with known time off",
            "Skill gaps are identified with proposed mitigations",
            "External constraints and dependencies are documented",
        ],
    },
    {
        "id": "plan-budget",
        "name": "Plan and track project budget",
        "instructions": [
            "Estimate costs for team resources, tools, infrastructure, and external services",
            "Identify budget constraints and allocate spending across project phases",
            "Set up budget tracking with planned vs actual spending",
            "Flag potential budget overruns and recommend adjustments",
            "Optimize resource allocation to stay within budget while meeting scope",
        ],
        "deliverables": ["budget-plan.md"],
        "calls_skills": ["backlog", "risk-analysis"],
        "calls_voices": ["Jane"],
        "checkpoints": [
            "Budget is allocated across project phases with estimates",
            "Budget tracking is set up with planned vs actual comparison",
            "Potential overruns are identified with adjustment recommendations",
        ],
    },
]
