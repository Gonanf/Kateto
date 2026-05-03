from modules.product_owner.graphs.project_creation import PROJECT_CREATION
import random


def test_project_creation():
    response = PROJECT_CREATION.invoke(
        {
            "title": "Comparando Unity, Godot y UE5",
            "team": [
                {"name": "Chaos", "type": "Human"},
                {"type": "Agent", "name": "Kateto"},
            ],
            "pbi_count": random.randint(5, 10),
        },
        {"configurable": {"thread_id": 1}},
    )
    print(response)
