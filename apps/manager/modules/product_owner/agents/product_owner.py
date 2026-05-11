from modules.product_owner.states.project import (
    Document,
    Asignee,
    DocumentData,
    PBI,
    PBIList,
    DOD,
    DODList,
)
from modules.core.agents import AGENTS
from langgraph.types import Command, interrupt


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
    print(f"Generated {len(response.dods)} DODs")
    return {"dod": response.dods}
