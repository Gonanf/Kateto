name = "project-closure"
description = "Close the project: verify deliverables, collect lessons learned, celebrate, and archive"
voice = "Jane"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "verify-deliverables",
        "name": "Verify deliverables and obtain acceptance",
        "instructions": [
            "Confirm all project tasks are completed, including tasks added during the project",
            "Verify all deliverables meet their acceptance criteria and quality standards",
            "Ensure all resources have been returned and vendor payments are settled",
            "Collect formal acceptance confirmation from stakeholders",
            "Archive project documentation including plans, reports, and deliverables",
        ],
        "deliverables": ["acceptance-confirmation.md", "project-archive.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Doktor", "Conquest"],
        "checkpoints": [
            "All deliverables are verified against acceptance criteria",
            "Formal acceptance is obtained from stakeholders",
            "Project documentation is archived",
        ],
    },
    {
        "id": "retrospect-celebrate",
        "name": "Run project retrospective and celebrate",
        "instructions": [
            "Facilitate a project retrospective: what went well, what could be improved, what to try next",
            "Document lessons learned for future projects",
            "Communicate project results and outcomes to all stakeholders",
            "Recognize individual and team contributions with specific thanks",
            "Celebrate the completion with the team through a closing note or gathering",
        ],
        "deliverables": ["lessons-learned.md", "closing-report.md"],
        "calls_skills": ["orchestrator"],
        "calls_voices": ["Conquest"],
        "checkpoints": [
            "Lessons learned are documented with actionable insights",
            "Team contributions are recognized and celebrated",
            "Stakeholders are informed of project completion",
        ],
    },
]
