name = "daily-standup"
description = "Facilitate the daily standup ceremony"
voice = "Conquest"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "check-progress",
        "name": "Check progress and identify blockers",
        "instructions": [
            "Review sprint board for current status of all items",
            "Ask each voice and user: what was completed yesterday",
            "Ask each voice and user: what will be worked on today",
            "Identify and document any blockers or impediments",
        ],
        "deliverables": ["standup-notes.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Doktor", "Jane"],
        "checkpoints": [
            "All blockers are documented",
            "Progress against sprint goal is recorded",
        ],
    },
    {
        "id": "update-tracking",
        "name": "Update sprint tracking",
        "instructions": [
            "Update sprint board with any status changes from the standup",
            "Flag blocked items with context in the backlog",
            "Share a standup summary with the team",
        ],
        "deliverables": ["standup-summary.md"],
        "calls_skills": ["backlog"],
        "calls_voices": [],
        "checkpoints": [
            "Sprint board reflects current status",
            "Blockers are flagged in the backlog",
        ],
    },
]
