name = "sprint-review"
description = "Review completed sprint items and update the backlog"
voice = "Doktor"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "review-completed",
        "name": "Review completed sprint items",
        "instructions": [
            "Review all items marked Done in the sprint board",
            "Verify completion criteria are met for each item",
            "Identify any items that need rework or further refinement"
        ],
        "deliverables": ["sprint-review-report.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Conquest"],
        "checkpoints": [
            "All Done items are verified against their criteria",
            "Rework items are identified and noted"
        ]
    },
    {
        "id": "update-backlog",
        "name": "Update and reprioritize backlog",
        "instructions": [
            "Move completed items to Done status",
            "Return incomplete items to the backlog with updated estimates",
            "Reprioritize backlog based on sprint outcomes and new priorities",
            "Archive the sprint board for historical reference"
        ],
        "deliverables": ["updated-backlog.json", "sprint-archive.json"],
        "calls_skills": ["backlog"],
        "calls_voices": [],
        "checkpoints": [
            "Backlog reflects current priorities",
            "Sprint is properly closed and archived"
        ]
    }
]
