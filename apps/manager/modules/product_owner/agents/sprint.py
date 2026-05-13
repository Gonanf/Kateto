from modules.product_owner.states.project import (
    Document,
    SprintDraft,
    Sprint,
    SprintList,
    SprintState,
    SprintTasksList,
)
from modules.core.agents import AGENTS
from i_have_time.calendar import Calendar, Event, SprintConfig, fromSliceToHours
from datetime import datetime, timedelta


def SprintAgent(state: Document):
    if not state.pbi or not state.team:
        return {}
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(SprintList)

    prompt = f"""
You are organizing {len(state.pbi)} backlog items into sprints for: {state.title}

PBIs: {state.pbi}
Team: {state.team}

CRITICAL: Generate between 2-4 sprints that organize ALL the PBIs.
Return JSON with key "sprints" containing an array of sprint objects.

Each sprint MUST have:
- "goal": string (a concise sprint goal)
- "description": string (what work will be done in this sprint)
- "duration_weeks": integer (how many weeks the sprint lasts)
"""
    result = structured_model.invoke(prompt)
    sprints = result.sprints

    print(f"Generated {len(sprints)} Sprints")

    return {"draft_sprints": sprints}


def SprintTasksAgent(state: SprintState):
    cal = Calendar()
    today = datetime.today() + timedelta(weeks=state.week)
    free_hours = fromSliceToHours(
        cal.getFreeTime(
            min_time=today,
            max_time=today + timedelta(weeks=state.current.duration_weeks),
        )
    )
    available_hours = int(free_hours * 0.9)

    prompt = f"""
You are a product owner defining the tasks for a sprint.

PROJECT INFO:
- Title: {state.document.title}
- Team: {state.document.team}
- Description: {state.document.data.description if state.document.data else "N/A"}
- Values: {state.document.data.project_values if state.document.data else "N/A"}

PRODUCT BACKLOG ITEMS:
{state.document.pbi}

SPRINT INFO:
- Goal: {state.current.goal}
- Description: {state.current.description}
- Duration: {state.current.duration_weeks} weeks
- Available hours (after overhead buffer): {available_hours}

TASK GENERATION RULES:
1. Generate 2-6 tasks that directly contribute to the sprint goal and cover the relevant PBIs.
2. Each task MUST have these fields:
   - "title": short actionable name (e.g. "Implement login form validation")
   - "description": clear definition of what needs to be done
   - "asignee": object with "type" ("Human" or "Agent") and "name" (use team members from the Team list above)
   - "effort_hours": float (estimated hours to complete)
3. The SUM of all effort_hours MUST NOT exceed {available_hours}.
4. Distribute tasks across team members based on their type (Humans for creative/decision work, Agents for repetitive/automated work).
5. Every task must be clearly derivable from a PBI in the backlog.

Return JSON with key "tasks" containing the array of task objects.
"""

    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(SprintTasksList)
    sprint = structured_model.invoke(prompt)
    return {"completed_sprints": [Sprint(data=state.current, tasks=sprint.tasks)]}


def IsBusyAgent(state: Document):

    calendar = Calendar(max_hours_per_day=4, max_events_per_day=1)
    if not state.completed_sprints:
        return
    acc = 0
    for sprint in state.completed_sprints:
        date = datetime.today().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(weeks=acc)
        sprint_calendar = Calendar().createScrumCeremonies(
            SprintConfig(
                start_date=date,
                end_date=date + timedelta(weeks=sprint.data.duration_weeks),
            )
        )
        acc += sprint.data.duration_weeks
        for task in sprint.tasks:
            calendar.createEvent(
                Event(
                    title=task.title,
                    description=task.description,
                    duration_hours=task.effort_hours,
                )
            )
