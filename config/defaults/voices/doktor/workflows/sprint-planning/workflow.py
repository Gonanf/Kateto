name = "sprint-planning"
description = "Plan and organize a sprint from the backlog"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "review-backlog",
        "name": "Review and prioritize backlog",
        "instructions": [
            "Review all items in the product backlog",
            "Prioritize using MoSCoW (Must/Should/Could/Won't)",
            "Identify items ready for the sprint",
        ],
        "deliverables": ["prioritized-backlog.md"],
        "calls_skills": ["backlog"],
        "calls_voices": [],
        "checkpoints": [
            "All items have a priority assigned",
            "Ready items are clearly identified",
        ],
    },
    {
        "id": "define-sprint",
        "name": "Define sprint scope and goal",
        "instructions": [
            "Select items for the sprint based on priority and capacity",
            "Define a clear sprint goal",
            "Estimate effort for selected items in story points",
            "Move selected items from backlog to sprint board",
        ],
        "deliverables": ["sprint-goal.md", "sprint-board.json"],
        "calls_skills": ["backlog", "calendar"],
        "calls_voices": ["Conquest"],
        "checkpoints": [
            "Sprint goal is documented",
            "Items are moved to sprint_board.json",
            "Conquest has acknowledged the sprint plan"
            "The User has acknowledged the sprint plan",
        ],
    },
]
