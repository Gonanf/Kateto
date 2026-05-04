from typing import Annotated, Any, TypedDict

from i_have_time.models import TimeSlot
from pydantic import BaseModel, Field

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
from i_have_time.calendar import calculate_free_slots, CalendarClient
from i_have_time.auth import get_credentials, build_calendar_service
from datetime import date, timedelta
import random
from i_have_time.config import load_config


class DODList(BaseModel):
    dods: list[DOD] = Field(min_length=5, max_length=6)


class PBIList(BaseModel):
    pbis: list[PBI] = Field(min_length=5, max_length=10)


class Phases(BaseModel):
    phases: list[Phase] = Field(min_length=2, max_length=4)


def ProductOwnerAgent(state: Document):
    if not state.get("title"):
        title = interrupt("Titulos")
        return Command(update={"title": title["title"]}, goto="product_owner")
    if not state.get("team"):
        state["team"] = [Asignee(type="Human", name="Chaos")]
    if not state.get("data"):
        prompt = f"""
        You are a product owner creating a new project.

        Project title: {state["title"]}

        And generate the following:
        - A medium length description for this project.
        - A list of project values, having into account the business and learning opportunities
        - A list of dependencies, that are a checklist of things to do before starting the project
        """

        agent = AGENTS["PRODUCT_OWNER"]
        structured_model = agent.model.with_structured_output(DocumentData)
        response = structured_model.invoke(prompt)
        return {"title": state["title"], "team": state["team"], "data": response}
    return {"title": state["title"], "team": state["team"], "data": state["data"]}


def ProductBacklogItemAgent(state: Document):
    if not state.get("data") or not state.get("title"):
        return {}
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(PBIList)

    prompt = f"""
You are a product owner creating product backlog items for: {state["title"]}

Project Data: {state["data"]}
Team: {state["team"]}

Generate between 5-10 items.
Each item MUST have: type (User Story/Epic/Task/Bug), title, description, score, priority, notes, criteries.
"""
    result = structured_model.invoke(prompt)
    items = result.pbis
    print(items)
    return {"pbi": items}


def PhasesAgent(state: Document):
    if not state.get("pbi") or not state.get("team"):
        return {}
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(Phases)

    prompt = f"""
You are organizing {len(state.get("pbi", []))} backlog items into project phases for: {state["title"]}

PBIs: {state["pbi"]}
Team: {state["team"]}

CRITICAL: Generate exactly 2-4 phases that organize ALL the PBIs.
Return JSON with key "phases" containing an array of phases.

Each phase MUST have: title, duration_days (int), tasks (list of PhaseTask).
Each PhaseTask MUST have: title, description, asignee (from team), effort_hours (float).
"""
    result = structured_model.invoke(prompt)
    phases = result.phases

    return {"phases": phases}


def DODAgent(state: Document):
    if not state.get("data") or not state.get("pbi"):
        return {}

    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(DODList)

    prompt = f"""
You are a product owner defining the Definition of Done (DoD) for a new project.

Project title: {state["title"]}
Project Data: {state["data"]}
Product Backlog Items: {state["pbi"]}

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
    return {"dod": response.dods}


def IsBusyAgent(state: Document):
    config = load_config()
    credentials = get_credentials()
    calendar_service = build_calendar_service(credentials)
    client = CalendarClient(calendar_service)

    result: dict[str, Any] = {}
    if state.get("phases"):
        updated_phases: list[Phase] = []
        task_idx = 0
        for phase in state["phases"]:
            updated_tasks: list[PhaseTask] = []
            for task in phase.get("tasks", []):
                is_busy: IsBusy | None = None
                if client:
                    target_date = date.today() + timedelta(days=task_idx * 2)
                    busy_slots = client.get_busy_slots_range(
                        target_date,
                        target_date + timedelta(days=phase["duration_days"]),
                        tz="UTC",
                        cfg=config,
                    )
                    if len(busy_slots) == 0:
                        print("No space left for", task)
                    slot = {"day": target_date, "slot": TimeSlot}
                    for k, v in busy_slots.items():
                        slot["day"] = k
                        slot["slot"] = calculate_free_slots(
                            v,
                            config.working_hours,
                            k,
                            config.default_timezone,
                            task.get("effort_hours", 4) * 60,
                        )
                        if len(slot["slot"]) > 0:
                            break

                    is_busy = {
                        "effort_days": max(1, int(task.get("effort_hours", 4) / 8)),
                        "effort_start": slot["slot"][0].start,
                        "effort_end": (slot["slot"][0].end).isoformat(),
                    }
                    task_idx += 1
                updated_tasks.append(
                    {
                        "title": task.get("title"),
                        "description": task.get("description"),
                        "asignee": task.get("asignee"),
                        "effort_hours": task.get("effort_hours"),
                        "is_busy": is_busy,
                    }
                )
            updated_phases.append(
                {
                    "title": phase.get("title"),
                    "duration_days": phase.get("duration_days"),
                    "tasks": updated_tasks,
                }
            )
        result["phases"] = updated_phases

    return result
