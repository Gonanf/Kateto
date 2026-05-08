from json import load
from typing import Any, dataclass_transform

from google.auth import credentials
from httpx import _status_codes
from pydantic import BaseModel, Field
import pydantic

from modules.product_owner.states.project import (
    Document,
    Asignee,
    PBI,
    DocumentData,
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
from mdutils import MdUtils


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
    if (
        not state.data
        or not state.phases
        or not state.pbi
        or not state.dod
        or not state.team
    ):
        return

    mdfile = MdUtils("[SPRINT]" + state.title)
    mdfile.new_header(level=1, title="Feature Overview")
    mdfile.new_header(level=2, title="Description")
    mdfile.new_paragraph(state.data.description)

    mdfile.new_header(level=2, title="Values")
    mdfile.new_checkbox_list(state.data.project_values)

    mdfile.new_header(level=2, title="Dependencies")
    mdfile.new_checkbox_list(state.data.dependencies)

    mdfile.new_header(level=1, title="Team capacity")
    header = ["Name", "Type"]
    data = []
    for d in state.team:
        data.append(d.name)
        data.append(d.type)
    mdfile.new_table(columns=len(header), rows=len(state.team), text=header + data)

    mdfile.new_header(level=1, title="Product Backlog Items")

    for pbi in state.pbi:
        mdfile.new_header(level=2, title=pbi.title)
        mdfile.new_paragraph(pbi.description)
        mdfile.new_paragraph("Score: " + str(pbi.score), "/13")
        mdfile.new_paragraph("Priority: " + str(pbi.priority) + "/5")
        criteries = []
        header = ["Given", "When", "Then"]
        for c in pbi.criteries:
            criteries.append(c.given_clause)
            criteries.append(c.when_clause)
            criteries.append(c.then_clause)
        mdfile.new_table(
            columns=len(header), rows=len(pbi.criteries), text=header + criteries
        )

        mdfile.new_paragraph(text=pbi.notes)

    mdfile.new_header(level=1, title="Phases")
    for index, phase in enumerate(state.phases):
        mdfile.new_header(level=2, title=str(index) + ". " + phase.title)
        mdfile.new_paragraph(text="Duration: " + str(phase.duration_days) + " Days")
        data = []
        header = ["Title", "Description", "Asignee", "Effort"]
        for t in phase.tasks:
            data.append(t.title)
            data.append(t.description)
            data.append(t.asignee.name + f"({t.asignee.type})")
            data.append(f"{t.effort_hours} Hours")
        mdfile.new_table(columns=len(header), rows=len(phase.tasks), text=header + data)

    mdfile.new_header(level=1, title="Definition of Done")
    for d in state.dod:
        mdfile.new_header(level=2, title=d.category)
        mdfile.new_checkbox_list(items=d.dod_items)

    return mdfile.get_md_text()


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
            "title": "[PROJECT] " + state.title,
            "markdown": __generateMarkdown(state),
        },
    )
