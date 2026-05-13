from modules.product_owner.graphs.project_creation import PROJECT_CREATION
from modules.product_owner.states.project import Document, Asignee
from pydantic import BaseModel
import json


def test_project_creation():
    response = PROJECT_CREATION.invoke(
        Document(
            title="KATETO: making the deep researcher",
            team=[
                Asignee(type="Human", name="Chaos"),
                Asignee(type="Agent", name="Kateto"),
            ],
            description="The Deep researcher is a new agent that will be made to be used with other agents, its role is for creating reports about what the agent wants to know, and the agent will search with the MCPs Duck Duck Go, Context 7, Mempalace, even files of a folder to find information. It will also support 3 modes: Simple (Will search fast, and try the MCPs with most chance to get information), Medium (Will divide the topic into 5 subtopics, search them and then add all into a report), Ultra (Will loop -> make a series of questions -> Search the questions -> Is the original topic resolved? -No-> Make more questions -> Continue). The deep researcher will tell the agent what sources it got it from",
            data=None,
            pbi=None,
            dod=None,
            draft_sprints=None,
            completed_sprints=[],
            openproject_context=None,
        ),
        {"configurable": {"thread_id": 1}},
    )

    def default(o):
        if isinstance(o, BaseModel):
            return o.model_dump()
        return str(o)

    with open("test.json", "w") as file:
        json.dump(response, file, default=default)
    print(response)
