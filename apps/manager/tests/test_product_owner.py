from modules.product_owner.graphs.project_creation import PROJECT_CREATION
from modules.product_owner.states.project import Document, Asignee
from pydantic import BaseModel
import json


def test_project_creation():
    response = PROJECT_CREATION.invoke(
        Document(
            title="Comparando Unity, Godot y UE5",
            team=[
                Asignee(type="Human", name="Chaos"),
                Asignee(type="Agent", name="Kateto"),
            ],
            data=None,
            pbi=None,
            dod=None,
            draft_sprints=None,
            completed_sprints=[],
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
