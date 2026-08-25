"""The project ledger as MCP tools. Logic in foamagent.tasks; this is the surface.

Five tools, all against the git repository the server was started in: task_list to orient,
task_add to name a piece of work, task_done to close it -- which is the only way anything
becomes done, because done is the commit it makes -- task_cancel for a change of plan, and
case_register to mark a directory as a case. Full profile only: the review never sees these.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from foamagent import tasks


class TaskListResponse(BaseModel):
    repo: str = Field(description="The git repository (or worktree) this ledger belongs to")
    branch: Optional[str] = Field(description="Checked-out branch; None when detached")
    worktree: bool
    tasks: List[Dict] = Field(description="id, title, status (open/done/cancelled), depends_on, ready")
    cases: List[Dict] = Field(description="Every case directory in the repository: path, note, spec, report")
    uncommitted: List[str] = Field(description="`git status --porcelain`: what no task_done has committed yet")
    warnings: List[str] = Field(default_factory=list)


async def task_list(ctx=None) -> TaskListResponse:
    """Where the project stands: tasks, which are ready, the cases, what is uncommitted.

    Call it when a session starts and whenever you are unsure what to do next. A task is
    ready when it is open and everything it depends on is done.
    """
    return TaskListResponse(**tasks.overview(tasks.repo_root()))


class TaskAddRequest(BaseModel):
    id: str = Field(description="Short ASCII slug, e.g. duct-v2-run: lowercase, digits, hyphens. Becomes the file name and the commit tag")
    title: str = Field(description="What the task is, in any language")
    depends_on: List[str] = Field(default_factory=list, description="Ids of tasks that must be done first")


class TaskAddResponse(BaseModel):
    id: str
    ready: bool
    warnings: List[str] = Field(default_factory=list)


async def task_add(request: TaskAddRequest, ctx=None) -> TaskAddResponse:
    """Name a piece of work before starting it. Not committed until a task_done carries it."""
    return TaskAddResponse(**tasks.add_task(tasks.repo_root(), request.id, request.title, request.depends_on))


class TaskDoneRequest(BaseModel):
    id: str
    message: str = Field(description="Commit message body; the tool prefixes `[task <id>]`")
    paths: List[str] = Field(description="Files or directories this task changed, relative to the repository. Only these are committed")


class TaskCloseResponse(BaseModel):
    id: str
    status: str
    commit: str = Field(description="Short hash of the commit that closed the task")
    files: List[str] = Field(description="What that commit contains")
    uncommitted: List[str] = Field(description="Changes still not committed after this -- forgotten paths show up here")
    ready: List[str] = Field(description="Tasks that are now ready to start")


async def task_done(request: TaskDoneRequest, ctx=None) -> TaskCloseResponse:
    """Finish a task: commits `paths` and the ledger together. Done exists only as this commit.

    Refused while a dependency is not done, and refused on main -- work on a branch and
    leave merging to the user. Do not `git commit` yourself; this is the one place it happens.
    """
    return TaskCloseResponse(
        **tasks.finish_task(tasks.repo_root(), request.id, request.message, request.paths)
    )


class TaskCancelRequest(BaseModel):
    id: str
    reason: str = Field(description="Why the plan changed; becomes the commit message")
    paths: List[str] = Field(default_factory=list, description="Anything to commit along with the cancellation")


async def task_cancel(request: TaskCancelRequest, ctx=None) -> TaskCloseResponse:
    """Drop a task that will not be done. A change of plan is history too, so it commits."""
    return TaskCloseResponse(
        **tasks.cancel_task(tasks.repo_root(), request.id, request.reason, request.paths)
    )


class CaseRegisterRequest(BaseModel):
    path: str = Field(description="The case directory, inside the repository")
    note: str = Field(default="", description="What this case is, or what superseded it; shown by task_list")


class CaseRegisterResponse(BaseModel):
    path: str
    note: str
    gitignore_written: bool = Field(description="True when the tool wrote the case .gitignore that keeps run data out of git")


async def case_register(request: CaseRegisterRequest, ctx=None) -> CaseRegisterResponse:
    """Mark a directory as a case, as soon as you create it.

    The mark is `.foamagent/state.json` in the directory itself, so it survives moves. The
    tool also writes a .gitignore (unless one exists) so that time directories, meshes and
    logs never reach git; the case definition, spec.md and report.md do. Include the case in
    the `paths` of the task_done that finishes it.
    """
    return CaseRegisterResponse(**tasks.register_case(tasks.repo_root(), request.path, request.note))


TOOLS = (
    ("task_list", task_list),
    ("task_add", task_add),
    ("task_done", task_done),
    ("task_cancel", task_cancel),
    ("case_register", case_register),
)


def register(mcp) -> None:
    for name, function in TOOLS:
        mcp.tool(name=name)(function)


__all__ = [name for name, _ in TOOLS] + ["TOOLS", "register"]
