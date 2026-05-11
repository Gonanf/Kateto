import asyncio

from fastmcp import Client
from mdutils import MdUtils

from modules.product_owner.states.project import Document


def generateMarkdown(state: Document):
    if (
        not state.data
        or not state.completed_sprints
        or not state.pbi
        or not state.dod
        or not state.team
    ):
        return

    mdfile = MdUtils(file_name="[SPRINT] " + state.title, title="")
    mdfile.new_header(level=1, title="Feature Overview")
    mdfile.new_header(level=2, title="Description")
    mdfile.new_paragraph(state.data.description)

    mdfile.new_header(level=2, title="Values")
    mdfile.new_checkbox_list(state.data.project_values)

    mdfile.new_header(level=2, title="Dependencies")
    mdfile.new_checkbox_list(state.data.dependencies)

    mdfile.new_header(level=1, title="Team capacity")
    header = ["Name", "Type"]
    data = []
    for d in state.team:
        data.append(d.name)
        data.append(d.type)
    mdfile.new_table(columns=len(header), rows=len(state.team) + 1, text=header + data)

    mdfile.new_header(level=1, title="Product Backlog Items")

    for pbi in state.pbi:
        mdfile.new_header(level=2, title=pbi.title)
        mdfile.new_paragraph(pbi.description)
        mdfile.new_paragraph("Score: " + str(pbi.score) + "/13")
        mdfile.new_paragraph("Priority: " + str(pbi.priority) + "/5")
        criteries = []
        header = ["Given", "When", "Then"]
        for c in pbi.criteries:
            criteries.append(c.given_clause)
            criteries.append(c.when_clause)
            criteries.append(c.then_clause)
        mdfile.new_table(
            columns=len(header), rows=len(pbi.criteries) + 1, text=header + criteries
        )

        mdfile.new_paragraph(text=pbi.notes)

    mdfile.new_header(level=1, title="Phases")
    for index, sprint in enumerate(state.completed_sprints):
        mdfile.new_header(level=2, title=str(index + 1) + ". " + sprint.data.goal)
        mdfile.new_paragraph(text=f"Description: {sprint.data.description}")
        mdfile.new_paragraph(
            text="Duration: " + str(sprint.data.duration_weeks) + " Weeks"
        )
        data = []
        header = ["Title", "Description", "Asignee", "Effort"]
        for t in sprint.tasks:
            data.append(t.title)
            data.append(t.description)
            data.append(t.asignee.name + f"({t.asignee.type})")
            data.append(f"{t.effort_hours} Hours")
        mdfile.new_table(
            columns=len(header), rows=len(sprint.tasks) + 1, text=header + data
        )
        mdfile.new_line()

    mdfile.new_header(level=1, title="Definition of Done")
    for d in state.dod:
        mdfile.new_header(level=2, title=d.category)
        mdfile.new_checkbox_list(items=d.dod_items)

    mdfile.create_md_file()
    return mdfile.get_md_text()


def createAffineDocument(state: Document):
    config = {
        "mcpServers": {"affine": {"command": "bunx", "args": ["affine-mcp-server"]}}
    }

    async def _run():
        async with Client(config) as client:
            await client.call_tool(
                "create_doc_from_markdown",
                {
                    "workspaceId": "eb1e876b-d031-474a-9065-0be79a7e03b2",
                    "title": "[PROJECT] " + state.title,
                    "markdown": generateMarkdown(state),
                },
            )

    asyncio.run(_run())
