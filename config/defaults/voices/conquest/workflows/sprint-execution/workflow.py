name = "sprint-execution"
description = "Monitor sprint progress, track velocity, remove blockers, and keep the team focused"
voice = "Conquest"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "monitor-progress",
        "name": "Monitor sprint progress and team velocity",
        "instructions": [
            "Review the sprint board for current status of all in-progress items",
            "Track sprint progress against the sprint goal and planned velocity",
            "Update burndown chart with completed vs remaining work",
            "Identify items that are falling behind schedule",
            "Communicate progress metrics to the team and Jane",
        ],
        "deliverables": ["sprint-progress-report.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Doktor", "Jane"],
        "checkpoints": [
            "Sprint progress is tracked against the sprint goal",
            "Falling-behind items are identified with supporting context",
            "Progress metrics are communicated to the team",
        ],
    },
    {
        "id": "resolve-blockers",
        "name": "Remove impediments and keep work flowing",
        "instructions": [
            "Identify blockers and impediments from the sprint board and team input",
            "Categorize blockers by type: technical, resource, process, or external",
            "Work with the team to find solutions or workarounds for each blocker",
            "Escalate blockers that need Jane or stakeholder involvement",
            "Update the sprint board with resolution status for each blocked item",
            "Ensure WIP limits are respected to maintain flow",
        ],
        "deliverables": ["blocker-log.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Doktor", "Jane"],
        "checkpoints": [
            "All blockers are documented with resolution status",
            "Escalated blockers have clear ownership",
            "WIP limits are respected across all board columns",
        ],
    },
]
