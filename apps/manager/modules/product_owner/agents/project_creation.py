from json import load
from typing import Any

from google.auth import credentials
from pydantic import BaseModel, Field
import pydantic

from modules.product_owner.states.project import (
    Document,
    Asignee,
    PBI,
    DocumentData,
    IsBusy,
    Phase,
    PhaseTask,
    DOD,
)
from modules.core.agents import AGENTS
from langgraph.types import Command, interrupt
from i_have_time.calendar import Calendar, Event
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from fastmcp import Client


class DODList(BaseModel):
    dods: list[DOD] = Field(min_length=5, max_length=6)


class PBIList(BaseModel):
    pbis: list[PBI] = Field(min_length=5, max_length=10)


class PhasesModel(BaseModel):
    phases: list[Phase] = Field(min_length=2, max_length=4)


def ProductOwnerAgent(state: Document):
    if not state.title:
        title = interrupt("Titulos")
        return Command(update={"title": title["title"]}, goto="product_owner")
    if not state.team:
        state.team = [Asignee(type="Human", name="Chaos")]
    if not state.data:
        prompt = f"""
        You are a product owner creating a new project.

        Project title: {state.title}

        Return JSON with:
        - "description": 2-3 sentence project description
        - "project_values": array of 3-5 strings (business/learning value)
        - "dependencies": array of 3-5 strings (prerequisites)
        """

        agent = AGENTS["PRODUCT_OWNER"]
        structured_model = agent.model.with_structured_output(DocumentData)

        for attempt in range(3):
            try:
                response = structured_model.invoke(prompt)
                return {"title": state.title, "team": state.team, "data": response}
            except Exception as e:
                print(f"ProductOwnerAgent attempt {attempt + 1} failed: {e}")
                if attempt == 2:
                    raise

    return {"title": state.title, "team": state.team, "data": state.data}


def ProductBacklogItemAgent(state: Document):
    if not state.data or not state.title:
        return {}
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(PBIList)

    base_prompt = f"""
You are a product owner creating product backlog items for: {state.title}

Project Data: {state.data}
Team: {state.team}

Generate between 5 to 10 items (no more, no less).

Return JSON with key "pbis" containing an array of exactly 5-10 PBI objects.
Each PBI object MUST have:
- "type": one of "User Story", "Epic", "Task", "Bug"
- "title": string
- "description": string
- "score": integer (1-13)
- "priority": integer (1-5, 1 is highest)
- "notes": string
- "criteries": array of EXACTLY 1-3 objects, each with:
  - "given_clause": string
  - "when_clause": string
  - "then_clause": string

Example PBI:
{{
  "type": "User Story",
  "title": "As a user, I want to...",
  "description": "Detailed description",
  "score": 5,
  "priority": 1,
  "notes": "Additional notes",
  "criteries": [
    {{
      "given_clause": "Given the user is logged in",
      "when_clause": "When they click the button",
      "then_clause": "Then the action should happen"
    }}
  ]
}}


"""

    result = structured_model.invoke(base_prompt)
    items = result.pbis
    print(f"Generated {len(items)} PBIs")
    return {"pbi": items}


def PhasesAgent(state: Document):
    if not state.pbi or not state.team:
        return {}
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(PhasesModel)

    prompt = f"""
You are organizing {len(state.pbi)} backlog items into project phases for: {state.title}

PBIs: {state.pbi}
Team: {state.team}

CRITICAL: Generate between 2-4 phases that organize ALL the PBIs.
Return JSON with key "phases" containing an array of phases.

Each phase MUST have: title, duration_days (int), tasks (list of PhaseTask).
Each PhaseTask MUST have: title, description, asignee (from team), effort_hours (float).
"""
    result = structured_model.invoke(prompt)
    phases = result.phases

    print(f"Generated {len(phases)} Phases")

    return {"phases": phases}


def DODAgent(state: Document):
    if not state.data or not state.pbi:
        return {}

    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(DODList)

    prompt = f"""
You are a product owner defining the Definition of Done (DoD) for a new project.

Project title: {state.title}
Project Data: {state.data}
Product Backlog Items: {state.pbi}

Generate a comprehensive Definition of Done that covers multiple categories.
For each category, provide a list of concrete, verifiable checklist items.

Categories to cover (use exactly these strings):
- "Code Quality": Code review, style guides, linting, static analysis
- "Testing": Unit tests, integration tests, test coverage thresholds
- "Documentation": API docs, inline comments, README updates
- "Deployment": Build passes, deployment scripts, environment configs
- "Performance": Performance benchmarks, load testing, optimization checks

Return a list of DOD entries, each with a category and a list of dod_items.
"""

    response = structured_model.invoke(prompt)
    print(f"Generated {len(response.dods)} Phases")
    return {"dod": response.dods}


# def __IsBusyAgent(state: Document):
#
#     # Initing I Have Time
#     config = load_config()
#     credentials = get_credentials()
#     calendar_service = build_calendar_service(credentials)
#     client = CalendarClient(calendar_service)
#
#     result: dict[str, Any] = {}
#     current_day = date.today()
#     if state.phases:
#         updated_phases: list[Phase] = []
#
#         # Time slots already claimed by tasks in this phase
#         booked_slots: dict[date, list[TimeSlot]] = {}
#
#         # Get every slot of time that we cannot assign
#         project_end_min = date.today() + timedelta(
#             days=sum(x.duration_days for x in state.phases)
#         )
#         base_busy = client.get_busy_slots_range(
#             date.today(),
#             project_end_min,
#             tz=config.default_timezone,
#             cfg=config,
#         )
#
#         for phase in state.phases:
#             updated_tasks: list[PhaseTask] = []
#             for task in phase.tasks:
#                 is_busy: IsBusy | None = None
#
#                 effort_hours = task.effort_hours
#                 effort_minutes = effort_hours * 60
#
#                 busy_merged: dict[date, list[TimeSlot]] = {}
#                 phase_end_date = current_day + timedelta(days=phase.duration_days)
#
#                 # Between the day where the task is soppoused to start and the day where it ends
#                 for day in base_busy:
#                     if day < current_day:
#                         continue
#                     if day > phase_end_date:
#                         continue
#                     # We get every busy (Existing events and claimed by tasks) time slots
#                     day_busy = list(base_busy.get(day, []))
#                     day_busy.extend(booked_slots.get(day, []))
#                     busy_merged[day] = day_busy
#
#                 all_free_slots: list[TimeSlot] = []
#                 for day, busy in busy_merged.items():
#                     free = calculate_free_slots(
#                         busy,
#                         config.working_hours,
#                         day,
#                         config.default_timezone,
#                     )
#                     all_free_slots.extend(free)
#                 all_free_slots.sort(key=lambda s: s.start)
#
#                 remaining_minutes = effort_minutes
#                 scheduled_segments: list[dict] = []
#                 for slot in all_free_slots:
#                     if remaining_minutes <= 0:
#                         break
#                     slot_duration = (slot.end - slot.start).total_seconds() / 60
#                     take = min(remaining_minutes, slot_duration)
#
#                     target_tz = ZoneInfo(config.default_timezone)
#                     event_start = slot.start.astimezone(target_tz)
#                     event_end = (slot.start + timedelta(minutes=take)).astimezone(
#                         target_tz
#                     )
#
#                     tag = config.tag_name or "[KATETO]"
#                     event = EventDetails(
#                         title=f"{task.title} {tag}",
#                         description=task.description,
#                         start=event_start,
#                         end=event_end,
#                         timezone=config.default_timezone,
#                         location="",
#                         attendees=[],
#                     )
#
#                     event_id = None
#                     try:
#                         resp = client.create_event(event)
#                         event_id = resp.get("id")
#                     except Exception as e:
#                         print(
#                             f"Failed to create calendar event for '{task.title}': {e}"
#                         )
#
#                     seg_start = slot.start
#                     seg_end = slot.start + timedelta(minutes=take)
#                     booked_slots.setdefault(seg_start.date(), []).append(
#                         TimeSlot(start=seg_start, end=seg_end)
#                     )
#
#                     scheduled_segments.append(
#                         {
#                             "start": seg_start.isoformat(),
#                             "end": event_end.isoformat(),
#                             "take_minutes": take,
#                             "event_id": event_id,
#                         }
#                     )
#                     remaining_minutes -= take
#
#                 total_parts = len(scheduled_segments)
#                 if total_parts > 0:
#                     final_slots = []
#                     for idx, seg in enumerate(scheduled_segments):
#                         part_num = idx + 1
#                         task_title = task.title
#                         if total_parts > 1:
#                             task_title = f"{task_title} [{part_num}/{total_parts}]"
#
#                         final_slots.append(
#                             {
#                                 "part_number": part_num,
#                                 "part_total": total_parts,
#                                 "start": seg["start"],
#                                 "end": seg["end"],
#                                 "event_id": seg["event_id"],
#                             }
#                         )
#
#                     is_busy = IsBusy(
#                         effort_days=max(1, int(effort_hours / 8)),
#                         effort_start=final_slots[0]["start"],
#                         effort_end=final_slots[-1]["end"],
#                         scheduled_slots=final_slots,
#                     )
#                 else:
#                     print(f"No free slots available for task: {task.title}")
#
#             updated_tasks.append(
#                 PhaseTask(
#                     title=task.title,
#                     description=task.description,
#                     asignee=task.asignee,
#                     effort_hours=task.effort_hours,
#                     is_busy=is_busy,
#                 )
#             )
#         updated_phases.append(
#             Phase(
#                 title=phase.title,
#                 duration_days=phase.duration_days,
#                 tasks=updated_tasks,
#             )
#         )
#     result["phases"] = updated_phases
#
#     return result


def IsBusyAgent(state: Document):
    calendar = Calendar()
    if not state.phases:
        return
    for phases in state.phases:
        for task in phases.tasks:
            calendar.createEvent(
                Event(
                    title=task.title,
                    description=task.description,
                    duration_hours=task.effort_hours,
                )
            )


def __generateMarkdown(state: Document):
    pass


# function create_doc_from_markdown(workspaceId?: string, title?: string, markdown: string, strict?: boolean, parentDocId?: string);
async def createAffineDocument(state: Document):
    config = {
        "mcpServers": {"affine": {"command": "bunx", "args": ["affine-mcp-server"]}}
    }

    client = Client(config)
    await client.call_tool(
        "create_doc_from_markdown",
        {
            "workspaceId": "eb1e876b-d031-474a-9065-0be79a7e03b2",
            "title": "[PROJECT]" + state.title,
            "markdown": "",
        },
    )
