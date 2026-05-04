from unittest.mock import Mock, patch


def test_phases_agent_structure():
    from modules.product_owner.states.project import (
        Phase, PhaseTask, Phases, Asignee
    )
    
    phase_task: PhaseTask = {
        "title": "Test Task",
        "description": "Test Description",
        "asignee": {"type": "Human", "name": "Test"},
        "effort_hours": 4.0,
        "is_busy": None,
    }
    
    phase: Phase = {
        "title": "Phase 1",
        "duration_days": 10,
        "tasks": [phase_task],
    }
    
    phases: Phases = {
        "phases": [phase],
    }
    
    assert phase_task["title"] == "Test Task"
    assert phase["tasks"][0]["effort_hours"] == 4.0
    assert len(phases["phases"]) == 1
    print("Phases structure test passed!")


def test_graph_structure():
    from modules.product_owner.graphs.project_creation import PROJECT_CREATION
    
    expected_nodes = ['product_owner', 'product_backlog_item', 'dod', 'phases', 'is_busy']
    actual_nodes = list(PROJECT_CREATION.nodes.keys())
    
    for node in expected_nodes:
        assert node in actual_nodes, f"Node {node} not found in graph"
    
    print("Graph structure test passed!")


def test_is_busy_agent_with_phases():
    from modules.product_owner.agents.project_creation import IsBusyAgent
    
    test_state = {
        "phases": [
            {
                "title": "Phase 1",
                "duration_days": 10,
                "tasks": [
                    {
                        "title": "Task 1",
                        "description": "Do something",
                        "asignee": {"type": "Human", "name": "Tester"},
                        "effort_hours": 8.0,
                    }
                ],
            }
        ],
    }
    
    with patch('modules.product_owner.agents.project_creation.CalendarClient') as mock_client:
        mock_instance = Mock()
        mock_instance.get_busy_slots.return_value = []
        mock_client.return_value = mock_instance
        
        result = IsBusyAgent(test_state)
        
        assert "phases" in result
        assert len(result["phases"]) == 1
        assert "tasks" in result["phases"][0]
        assert "is_busy" in result["phases"][0]["tasks"][0]
        print("IsBusyAgent phases processing test passed!")


if __name__ == "__main__":
    test_phases_agent_structure()
    test_graph_structure()
    test_is_busy_agent_with_phases()
    print("\nAll tests passed!")
