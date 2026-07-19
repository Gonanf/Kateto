name = "continuous-improvement"
description = "Analyze team metrics, identify waste, and implement process improvements using Lean principles"
voice = "Conquest"
auto_advance = True
can_stop = True

phases = [
    {
        "id": "analyze-metrics",
        "name": "Analyze flow metrics and identify waste",
        "instructions": [
            "Gather sprint metrics: cycle time, throughput, WIP, and work item age",
            "Review the cumulative flow diagram for bottlenecks and flow issues",
            "Identify types of waste: defects, overprocessing, waiting, handoffs, unused talent",
            "Survey the team for process friction points and improvement suggestions",
            "Document the top improvement opportunities with supporting data",
        ],
        "deliverables": ["metrics-analysis.md", "improvement-opportunities.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Doktor", "Jane"],
        "checkpoints": [
            "Flow metrics are collected and analyzed",
            "Waste types are identified with specific examples",
            "Improvement opportunities are prioritized with data",
        ],
    },
    {
        "id": "implement-improvements",
        "name": "Implement and track process improvements",
        "instructions": [
            "Define concrete, measurable experiments for the top improvement opportunities",
            "Create action items with clear owners, success criteria, and review dates",
            "Add improvement experiments to the backlog for the next sprint",
            "Communicate the improvement plan to the team and stakeholders",
            "Establish a review cadence to measure if changes are having the desired effect",
        ],
        "deliverables": ["improvement-action-plan.md"],
        "calls_skills": ["backlog"],
        "calls_voices": ["Doktor"],
        "checkpoints": [
            "Improvement experiments have measurable success criteria",
            "Action items have assigned owners and review dates",
            "Improvement plan is communicated to the team",
        ],
    },
]
