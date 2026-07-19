name = "backlog-grooming"
description = "Regularly refine and prioritize the backlog using MoSCoW and estimate effort"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "review-prioritize",
        "name": "Review and prioritize backlog items",
        "instructions": [
            "Review all items in the product backlog for relevance and currency",
            "Prioritize items using MoSCoW: Must, Should, Could, Won't for the upcoming cycle",
            "Remove or deprioritize items that are no longer relevant",
            "Identify and resolve any dependencies between backlog items",
            "Ensure each item has a clear description and acceptance criteria",
        ],
        "deliverables": ["prioritized-backlog.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Jane", "Conquest"],
        "checkpoints": [
            "All items have a MoSCoW priority assigned",
            "Dependencies between items are identified and documented",
            "Each item has a clear description and acceptance criteria",
        ],
    },
    {
        "id": "refine-estimate",
        "name": "Refine and estimate backlog items",
        "instructions": [
            "Break down large items (epics) into smaller, actionable tasks",
            "Estimate effort for each actionable item using relative story points",
            "Flag items where estimates have high uncertainty for further discussion",
            "Ensure the backlog is ordered by priority with refined items at the top",
            "Move refined items to Ready status for sprint planning",
        ],
        "deliverables": ["refined-backlog.json"],
        "calls_skills": ["backlog", "planning-poker"],
        "calls_voices": ["Conquest"],
        "checkpoints": [
            "Large items are broken down into actionable tasks",
            "All ready items have effort estimates",
            "Backlog is ordered by priority with refined items at the top",
        ],
    },
]
