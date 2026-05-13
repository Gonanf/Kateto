import datetime
from op_client.cli import projects
from op_client.config import get_openproject_config
from op_client.client import OpenProjectClient, SprintStatus, WorkPackageInfo
from openproject_api_client import WorkPackage
from pydantic import BaseModel
from op_client.models import SprintInfo, ProjectInfo
from i_have_time.calendar import Calendar, fromSliceToHours

class State(BaseModel):
    ## Openproject ##
    project_id: (
        int | None
    )  # Be able to get from any project the todo items in the active sprints
    projects: list[ProjectInfo],
    sprint_name: str | None
    sprint_id: int | None
    sprints: list[SprintInfo]

client = OpenProjectClient(get_openproject_config())


def _GetProjects(id: int | None) -> list[ProjectInfo]:
    if id is None:
        projects = client.list_projects()
        return projects
    else: 
        return [client.get_project(id)]

def _GetSprint(project_id: int,id: int | None, name: str | None) -> list[SprintInfo]:
    if id is None and name is None:
        return list(filter(lambda x: x.status == SprintStatus.ACTIVE,client.list_sprints(project_id)))
    if id is not None:
        return [client.get_sprint(id) ] 
    if name is not None:

        return list(filter(lambda x: x.name == name,client.list_sprints(project_id)))
    return []

def _GetPriority(work: WorkPackageInfo):
    if work.status_name == "Closed":
        return "Low"
    return work.priority_name

def ScheduleAgent(state: State):
    projects = _GetProjects(state.project_id)

    calendar = Calendar()

    free = calendar.getFreeTime(datetime.datetime.today(),datetime.datetime.today().replace(hour=0,minute=0,second=0,microsecond=0))
    hours = fromSliceToHours(free) * 0.7
    todo = []
    for p in projects:
        for s in _GetSprint(p.id,state.sprint_id,state.sprint_name):
            todo = todo + s.work_packages

    todo.sort(key=_GetPriority)




