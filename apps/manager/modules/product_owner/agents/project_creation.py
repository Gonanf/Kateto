from modules.product_owner.states.project import (
    Document,
    Asignee,
    PBI,
    PBI_Data,
    DocumentData,
)
from modules.core.agents import AGENTS
from langgraph.types import Command, interrupt
from i_have_time.calendar import calculate_free_slots, CalendarClient
import random


def ProductOwnerAgent(state: Document):
    if not state.get("title"):
        title = interrupt("Titulos")
        return Command(update={"title": title["title"]}, goto="product_owner")
    if not state.get("team"):
        state["team"] = [Asignee(type="Human", name="Chaos")]
    if not state.get("description"):
        prompt = f"""
        You are a product owner creating a new project.

        Project title: {state["title"]}
        
        And generate the following:
        - A medium length description for this project.
        - A list of project values, having into account the bussinness and learning opportunities
        - A list of dependencies, that are a checklist of things to do before starting the project
        """

        agent = AGENTS["PRODUCT_OWNER"]
        agent.model.with_structured_output(DocumentData)
        state["data"] = agent.invoke({"input": prompt}).content
    return {"title": state["title"], "team": state["team"], "data": state["data"]}


def ProductBacklogItemAgent(state: Document):
    agent = AGENTS["PRODUCT_OWNER"]
    agent.model.with_structured_output(PBI_Data)

    num_items = random.randint(5, 10)
    prompt = f"""
        You are a product owner creating a product backlog item for a new project.

        Project title: {state["title"]}
        Project Data: {state["data"]}
        Project Team capacity: {state["team"]}

Generate exactly {num_items} coherent backlog items. Items should:
1. Work together logically to build the complete product
2. Follow a sensible prioritization order (epics before stories, foundational features first)
3. Reference related items where applicable
4. Maintain consistent terminology and vision
"""

    pbi = PBI(PBI_Data=agent.invoke({"input": prompt}).content)
    return {"pbi": pbi}


def IsBusyAgent(stete: Document):
    CalendarClient.get_busy_slots()
