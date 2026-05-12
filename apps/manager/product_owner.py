import sys
from modules.product_owner.graphs.project_creation import PROJECT_CREATION
from modules.product_owner.states.project import Document, Asignee
from pydantic import BaseModel
import json


def create_project(title, description, team):
    response = PROJECT_CREATION.invoke(
        Document(
            title=title,
            description=description,
            team=team,
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


if len(sys.argv) > 1:
    create_project(
        sys.argv[1],
        sys.argv[2],
        [
            Asignee(type="Human", name="Gabriel Solotorevsky"),
            Asignee(type="Agent", name="Kateto"),
        ],
    )
else:
    with open("temp.json", "r") as file:
        contents = json.load(file)
        for c in contents:
            create_project(
                c["title"],
                c["description"],
                [Asignee(type=x["type"], name=c["name"]) for x in c["team"]],
            )
