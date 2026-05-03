from modules.product_owner.states.project import (
    Document,
    Asignee,
    PBI,
    PBI_Data,
    DocumentData,
    IsBusy,
)
from modules.core.agents import AGENTS
from langgraph.types import Command, interrupt
from i_have_time.calendar import calculate_free_slots, CalendarClient
from i_have_time.auth import get_credentials, build_calendar_service
from datetime import date, timedelta
import random
from typing import Any
from i_have_time.config import load_config


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
    agent = AGENTS["PRODUCT_OWNER"]
    structured_model = agent.model.with_structured_output(PBI_Data)

    if len(state.get("pbi", [])) >= state.get("pbi_count", 5):
        return {"pbi": state["pbi"]} #Command(update={"pbi": new_pbi}, goto="product_backlog_item")

    print("ITEMS:", state.get("pbi", "Nada"))
    # items = state.get("pbi", [])
    # items.append({"data": "amongas"})
    # return Command(update={"pbi": items}, goto="product_backlog_item")
    prompt = f"""
        You are a product owner creating product backlog items for a new project.

        Project title: {state["title"]}
        Project Data: {state["data"]}
        Project Team capacity: {state["team"]}

        Current items: {state.get("pbi", "Empty")}

        Generate coherent backlog items. Items should:
        1. Work together logically to build the complete product
        2. Follow a sensible prioritization order (epics before stories, foundational features first)
        3. Reference related items where applicable
        4. Maintain consistent terminology and vision
        5. Each item must include: type (User Story/Epic/Task), title, description, and content (score, notes, criteries)
        """

    result = structured_model.invoke(prompt)
    new_pbi = state.get("pbi", [])
    new_pbi = new_pbi + [{"data": result}]
    return Command(update={"pbi": new_pbi}, goto="product_backlog_item")


def IsBusyAgent(state: Document):
    if not state.get("pbi"):
        return {}
    config = load_config()
    print(config)
    credentials = get_credentials()
    calendar_service = build_calendar_service(credentials)
    client = CalendarClient(calendar_service)
    updated_pbis: list[dict[str, Any]] = []

    for idx, pbi in enumerate(state["pbi"]):
        is_busy: IsBusy | None = None

        if client:
            target_date = date.today() + timedelta(days=idx * 2)
            busy_slots = client.get_busy_slots(
                target_date,
                tz="UTC",
                cfg=config,  # TODO: pass proper AppConfig with working_hours and buffer_minutes
            )
            is_busy = {
                "effort_days": 3,
                "effort_start": target_date.isoformat(),
                "effort_end": (target_date + timedelta(days=3)).isoformat(),
            }

        updated_pbis.append(
            {
                "data": pbi.get("data"),
                "is_busy": is_busy,
            }
        )

    return {"pbi": updated_pbis}
