"""gRPC servicer for the ProductOwner service."""

import json
import logging
import itertools
import grpc
import manager_pb
from modules.product_owner.graphs.project_creation import PROJECT_CREATION
from modules.product_owner.states.project import Document, Asignee
from modules.product_owner.agents.output import generateMarkdown

logger = logging.getLogger(__name__)

_thread_counter = itertools.count()

_NODE_TO_STAGE = {
    "product_owner": "project_info",
    "product_backlog_item": "pbis",
    "dod": "dod",
    "sprint": "sprints",
    "sprint_tasks": "tasks",
    "is_busy": "calendar",
    "create_affine": "document",
}

_STAGE_MESSAGES = {
    "product_owner": "Generating project description and requirements...",
    "product_backlog_item": "Creating product backlog items...",
    "dod": "Defining Definition of Done...",
    "sprint": "Planning sprints...",
    "sprint_tasks": "Breaking down sprint tasks...",
    "is_busy": "Checking calendar availability...",
    "create_affine": "Creating project document...",
}


class ProductOwnerServicer(manager_pb.ProductOwnerServicer):
    """gRPC servicer that runs the PROJECT_CREATION graph and streams results."""

    def CreateProject(self, request, context):
        team = [Asignee(type="Human", name=name) for name in request.team]
        initial_state = Document(
            title=request.idea,
            team=team,
            data=None,
            pbi=None,
            dod=None,
            draft_sprints=None,
            completed_sprints=[],
        )

        thread_id = f"po_{next(_thread_counter)}"
        config = {"configurable": {"thread_id": thread_id}}

        try:
            streamed = False
            print(f"Creating project {request.idea}...")
            for event in PROJECT_CREATION.stream(
                initial_state,
                config,
                stream_mode="updates",
            ):
                streamed = True
                for node_name, output in event.items():
                    stage = _NODE_TO_STAGE.get(node_name, node_name)
                    msg = _STAGE_MESSAGES.get(node_name, f"Running {node_name}...")
                    data_json = (
                        json.dumps(output, default=str) if output is not None else ""
                    )

                    yield manager_pb.ProjectResponse(
                        stage=stage,
                        message=msg,
                        data_json=data_json,
                    )

            if streamed:
                state_snapshot = PROJECT_CREATION.get_state(config)
                doc = (
                    Document.model_validate(state_snapshot.values)
                    if state_snapshot and state_snapshot.values
                    else None
                )
                markdown = generateMarkdown(doc) if doc else ""
                yield manager_pb.ProjectResponse(
                    stage="done",
                    message="Project creation complete",
                    markdown=markdown or "",
                )
        except Exception as e:
            logger.exception("Project creation failed")
            yield manager_pb.ProjectResponse(
                stage="error",
                message=f"Project creation failed: {e}",
            )
