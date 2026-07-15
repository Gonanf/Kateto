name = "sprint-retrospective"
description = "Facilitate retrospective to improve team processes"
voice = "Conquest"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "gather-feedback",
        "name": "Gather feedback from the team",
        "instructions": [
            "Ask each voice and user: what went well this sprint",
            "Ask each voice and user: what could be improved",
            "Ask each voice and user: what will we commit to trying next sprint",
            "Document all responses with actionable insights",
        ],
        "deliverables": ["retrospective-feedback.md"],
        "calls_voices": ["Doktor", "Jane"],
        "checkpoints": [
            "All voices have provided feedback on all three prompts",
            "Insights are documented with specific examples",
        ],
    },
    {
        "id": "define-improvements",
        "name": "Define action items for next sprint",
        "instructions": [
            "Identify the top 3 areas for improvement from the feedback",
            "Create concrete, measurable action items for each area",
            "Assign an owner and deadline to each action item",
            "Add action items to the backlog for tracking",
        ],
        "deliverables": ["retrospective-actions.md"],
        "calls_skills": ["backlog"],
        "calls_voices": [],
        "checkpoints": [
            "Action items have clear owners and deadlines",
            "Improvements are tracked in the backlog",
        ],
    },
]
