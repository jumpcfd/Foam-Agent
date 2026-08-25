"""The project ledger: tasks that outlive a case, and the cases themselves.

A real engagement is research, several cases, a report that merges them, and a change of
plan halfway. The per-case state in `case_state.py` cannot hold that, and the harness's own
todo list dies with the session. So the ledger lives in the project's git repository, one
file per task under `<repo>/.foamagent/tasks/`, and a task is "done" only by the commit
that `finish_task` makes -- which includes the ledger change itself, so the history of the
ledger and the history of the work are one and the same `git log`.

Nothing here reasons. The harness decides what a task is and when it is finished; this
module refuses a completion whose dependencies are open, refuses to commit on main, and
runs git. One file per task rather than one array, so that two worktrees adding tasks on
two branches merge without a conflict.

A case is not recorded in the ledger. A directory is a case because it carries
`.foamagent/state.json` (the file `request_review` writes anyway); the list of cases is a
scan for that marker, so moving a case directory does not leave a stale path behind.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from foamagent.case_state import STATE_DIRNAME, STATE_FILENAME, load_case_state, update_case_state
from foamagent.locking import case_lock
from foamagent.logger import get_logger

logger = get_logger(__name__)

PathLike = Union[str, Path]

TASKS_DIRNAME = f"{STATE_DIRNAME}/tasks"
TASK_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
STATUSES = ("open", "done", "cancelled")
PROTECTED_BRANCHES = ("main", "master")

# Written into a registered case that has no .gitignore of its own. Keeps the run data --
# time directories, the generated mesh, decomposed domains, logs -- out of git while the
# case definition, spec.md, report.md and the review documents stay in. Verified against a
# synthetic case: `0/`, `0.orig/`, `blockMeshDict` in either location, `triSurface/` and
# `postProcessing/` are tracked; `0.5/`, `1e-05/`, `100/`, `polyMesh/points`, `processor*`
# are not. Directory-level exclusion of polyMesh would make blockMeshDict un-reincludable
# (git cannot re-include a file under an excluded directory), hence `/*` plus a negation.
CASE_GITIGNORE = """/[0-9]*/
!/0/
!/0.orig/
/constant/polyMesh/*
!/constant/polyMesh/blockMeshDict
/constant/*/polyMesh/*
/constant/extendedFeatureEdgeMesh/
/processor*/
/dynamicCode/
/VTK/
/log*
/Allrun.out
/Allrun.err
*.log
*.foam
*.OpenFOAM
"""


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def _git(repo: PathLike, *args: str, check: bool = True) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        raise ValueError("git is not installed, and the task ledger lives in git.") from None
    if check and result.returncode != 0:
        raise ValueError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def repo_root(cwd: Optional[PathLike] = None) -> Path:
    """The git repository (or worktree) the server is running in."""
    where = Path(cwd) if cwd is not None else Path.cwd()
    try:
        return Path(_git(where, "rev-parse", "--show-toplevel").strip())
    except ValueError as exc:
        raise ValueError(
            f"{where} is not inside a git repository ({exc}). The task ledger lives in git: "
            "run `git init` in the project directory and start the harness there."
        ) from None


def current_branch(repo: PathLike) -> Optional[str]:
    """The checked-out branch, or None when HEAD is detached. Works before the first commit."""
    return _git(repo, "symbolic-ref", "--short", "HEAD", check=False).strip() or None


def is_worktree(repo: PathLike) -> bool:
    common = _git(repo, "rev-parse", "--git-common-dir", check=False).strip()
    own = _git(repo, "rev-parse", "--git-dir", check=False).strip()
    return bool(common and own and common != own)


def uncommitted(repo: PathLike) -> List[str]:
    """`git status --porcelain`, one entry per changed or untracked path."""
    return [line for line in _git(repo, "status", "--porcelain").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """One file under .foamagent/tasks/. The id is the file name, not a field."""

    id: str
    title: str = ""
    depends_on: List[str] = field(default_factory=list)
    status: str = "open"

    def to_dict(self) -> Dict:
        payload = {"version": TASK_VERSION}
        payload.update({k: v for k, v in asdict(self).items() if k != "id"})
        return payload

    @classmethod
    def from_dict(cls, task_id: str, data: Dict) -> "Task":
        """Tolerant, like CaseState: unknown keys dropped, missing keys defaulted."""
        if not isinstance(data, dict):
            raise ValueError(f"Task {task_id} must be a JSON object, got {type(data).__name__}")
        known = {f.name for f in fields(cls)} - {"id"}
        accepted = {key: value for key, value in data.items() if key in known}
        task = cls(id=task_id, **accepted)
        if task.status not in STATUSES:
            task.status = "open"
        if not isinstance(task.depends_on, list):
            task.depends_on = []
        return task


def tasks_dir(repo: PathLike) -> Path:
    return Path(repo) / TASKS_DIRNAME


def task_path(repo: PathLike, task_id: str) -> Path:
    return tasks_dir(repo) / f"{task_id}.json"


def _read_task(path: Path) -> Optional[Task]:
    try:
        return Task.from_dict(path.stem, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Task file %s is not usable: %s", path, exc)
        return None


def _write_task(repo: PathLike, task: Task) -> None:
    path = task_path(repo, task.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_tasks(repo: PathLike) -> Dict[str, Task]:
    """Every readable task, keyed by id, in id order."""
    directory = tasks_dir(repo)
    if not directory.is_dir():
        return {}
    tasks = (_read_task(path) for path in sorted(directory.glob("*.json")))
    return {task.id: task for task in tasks if task is not None}


def _ready(task: Task, tasks: Dict[str, Task]) -> bool:
    return task.status == "open" and all(
        dep in tasks and tasks[dep].status == "done" for dep in task.depends_on
    )


def _require(repo: PathLike, task_id: str) -> Task:
    if not ID_PATTERN.match(task_id or ""):
        raise ValueError(
            f"Task id {task_id!r} must match {ID_PATTERN.pattern}: lowercase ASCII, digits, "
            "hyphens. Put the readable title in `title`."
        )
    task = _read_task(task_path(repo, task_id)) if task_path(repo, task_id).is_file() else None
    if task is None:
        raise ValueError(f"No task {task_id!r}. `task_list` shows the ones that exist.")
    return task


def add_task(repo: PathLike, task_id: str, title: str, depends_on: Iterable[str] = ()) -> Dict:
    """Create an open task. Not committed: the next finish_task carries the file."""
    if not ID_PATTERN.match(task_id or ""):
        raise ValueError(
            f"Task id {task_id!r} must match {ID_PATTERN.pattern}: lowercase ASCII, digits, "
            "hyphens. Put the readable title in `title`."
        )
    depends_on = list(depends_on)
    with case_lock(repo, blocking=True):
        tasks = load_tasks(repo)
        if task_id in tasks or task_path(repo, task_id).exists():
            raise ValueError(f"Task {task_id!r} already exists ({tasks[task_id].status if task_id in tasks else 'unreadable file'}). Ids are never reused.")
        missing = [dep for dep in depends_on if dep not in tasks]
        if missing:
            raise ValueError(f"depends_on names tasks that do not exist: {', '.join(missing)}")
        task = Task(id=task_id, title=title, depends_on=depends_on)
        _write_task(repo, task)
    warnings = _branch_warning(repo)
    return {"id": task_id, "ready": _ready(task, tasks), "warnings": warnings}


def _branch_warning(repo: PathLike) -> List[str]:
    branch = current_branch(repo)
    if branch is None:
        return ["HEAD is detached; task_done will refuse to commit until a branch is checked out."]
    if branch in PROTECTED_BRANCHES:
        return [
            f"You are on {branch}. task_done refuses to commit there: `git switch -c work/<name>` "
            "(or `git worktree add ../<name> -b work/<name>` for parallel work) first. Merging "
            "into main is the user's call."
        ]
    return []


def _close_task(
    repo: PathLike, task_id: str, status: str, message: str, paths: Iterable[str], *, check_deps: bool
) -> Dict:
    """Mark a task done/cancelled and commit it together with `paths`, or leave nothing behind.

    The ledger file is always in the commit, so the commit is never empty and the ledger
    can never say "done" about something that is not in history. Everything a failed
    `git add`/`git commit` could half-do is undone before the error is re-raised.
    """
    paths = [str(p) for p in paths]
    with case_lock(repo, blocking=True):
        branch = current_branch(repo)
        if branch is None or branch in PROTECTED_BRANCHES:
            raise ValueError(
                f"Refusing to commit on {branch or 'a detached HEAD'}. Work on a branch: "
                "`git switch -c work/<name>`, or `git worktree add ../<name> -b work/<name>` "
                "for parallel work. Merging into main is the user's call."
            )
        tasks = load_tasks(repo)
        task = _require(repo, task_id)
        if task.status != "open":
            raise ValueError(f"Task {task_id!r} is already {task.status}.")
        if check_deps:
            unmet = [
                f"{dep} ({tasks[dep].status if dep in tasks else 'missing'})"
                for dep in task.depends_on
                if not (dep in tasks and tasks[dep].status == "done")
            ]
            if unmet:
                raise ValueError(
                    f"Task {task_id!r} depends on unfinished work: {', '.join(unmet)}. Finish "
                    "those first, or cancel this task and add one without the dependency."
                )

        before = task_path(repo, task_id).read_text(encoding="utf-8")
        task.status = status
        _write_task(repo, task)
        try:
            _git(repo, "add", "--", f"{TASKS_DIRNAME}/{task_id}.json", *paths)
            _git(repo, "commit", "-q", "-m", f"[task {task_id}] {message}")
        except ValueError:
            _git(repo, "reset", "-q", check=False)
            task_path(repo, task_id).write_text(before, encoding="utf-8")
            raise

        tasks[task_id] = task
        return {
            "id": task_id,
            "status": status,
            "commit": _git(repo, "rev-parse", "--short", "HEAD").strip(),
            "files": _git(repo, "show", "--name-only", "--format=", "HEAD").split(),
            "uncommitted": uncommitted(repo),
            "ready": [t.id for t in tasks.values() if _ready(t, tasks)],
        }


def finish_task(repo: PathLike, task_id: str, message: str, paths: Iterable[str]) -> Dict:
    """Done = this commit. Refused while a dependency is not done."""
    paths = list(paths)
    if not paths:
        raise ValueError(
            "task_done needs the paths this task changed (files or directories, relative to "
            "the repository); nothing else is committed. Use task_list's `uncommitted` to see "
            "what is pending."
        )
    return _close_task(repo, task_id, "done", message, paths, check_deps=True)


def cancel_task(repo: PathLike, task_id: str, reason: str, paths: Iterable[str] = ()) -> Dict:
    """A change of plan, recorded as a commit like everything else."""
    return _close_task(repo, task_id, "cancelled", reason, paths, check_deps=False)


# ---------------------------------------------------------------------------
# cases
# ---------------------------------------------------------------------------


def list_cases(repo: PathLike) -> List[Dict]:
    """Every directory under the repository that carries the case marker, tracked or not.

    `git ls-files` rather than a walk: it honours .gitignore, so the time directories a run
    leaves behind are never descended into.
    """
    marker = f"{STATE_DIRNAME}/{STATE_FILENAME}"
    listing = _git(
        repo, "ls-files", "-co", "--exclude-standard", "-z", "--", f":(glob)**/{marker}", check=False
    )
    cases = []
    for entry in sorted(set(filter(None, listing.split("\0")))):
        case_dir = Path(repo) / entry[: -len(marker)].rstrip("/")
        state = load_case_state(case_dir)
        cases.append(
            {
                "path": str(case_dir.relative_to(repo)) if case_dir != Path(repo) else ".",
                "note": state.note if state else "",
                "spec": (case_dir / "spec.md").is_file(),
                "report": (case_dir / "report.md").is_file(),
            }
        )
    return cases


def register_case(repo: PathLike, path: PathLike, note: str = "") -> Dict:
    """Mark a directory as a case, and keep its run data out of git.

    Writes the marker (`.foamagent/state.json`) and, only when the case has no .gitignore of
    its own, CASE_GITIGNORE. Refuses a directory outside the repository: a case that git
    cannot see cannot be committed, and moving it in is the fix.
    """
    repo = Path(repo).resolve()
    case_dir = (repo / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not case_dir.is_dir():
        raise ValueError(f"Case directory does not exist: {case_dir}")
    if repo != case_dir and repo not in case_dir.parents:
        raise ValueError(
            f"{case_dir} is outside the repository {repo}. Move it inside (`mv`, or `git mv` if "
            "tracked) and register it again; cases outside git cannot be committed."
        )
    updates: Dict[str, str] = {}
    if load_case_state(case_dir) is None:
        updates["case_name"] = case_dir.name
    if note:
        updates["note"] = note
    state = update_case_state(case_dir, **updates)

    gitignore = case_dir / ".gitignore"
    wrote_gitignore = not gitignore.exists()
    if wrote_gitignore:
        gitignore.write_text(CASE_GITIGNORE, encoding="utf-8")

    return {
        "path": str(case_dir.relative_to(repo)) if case_dir != repo else ".",
        "note": state.note,
        "gitignore_written": wrote_gitignore,
    }


# ---------------------------------------------------------------------------
# the overview
# ---------------------------------------------------------------------------


def overview(repo: PathLike) -> Dict:
    """Everything a session needs to orient itself: tasks, cases, branch, pending changes."""
    repo = Path(repo)
    tasks = load_tasks(repo)
    cases = list_cases(repo)
    pending = uncommitted(repo)
    warnings = _branch_warning(repo)
    if pending:
        warnings.append(
            f"{len(pending)} uncommitted change(s). A finished task is closed with task_done "
            "(which commits); work in progress can stay open."
        )
    unspecified = [c["path"] for c in cases if not c["spec"]]
    if unspecified:
        warnings.append(f"Case(s) without spec.md: {', '.join(unspecified)}.")
    return {
        "repo": str(repo.resolve()),
        "branch": current_branch(repo),
        "worktree": is_worktree(repo),
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "depends_on": t.depends_on,
                "ready": _ready(t, tasks),
            }
            for t in tasks.values()
        ],
        "cases": cases,
        "uncommitted": pending,
        "warnings": warnings,
    }


def format_overview(view: Dict) -> str:
    """The overview as text, for the hook that puts it in front of the harness."""
    lines = [f"Foam-Agent tasks in {view['repo']} (branch: {view['branch'] or 'detached'}"
             f"{', worktree' if view['worktree'] else ''}):"]
    if not view["tasks"]:
        lines.append("  (no tasks yet: task_add before starting work)")
    for t in view["tasks"]:
        mark = "ready" if t["ready"] else t["status"]
        deps = f"  (after: {', '.join(t['depends_on'])})" if t["depends_on"] and t["status"] == "open" else ""
        lines.append(f"  [{mark:9}] {t['id']}: {t['title']}{deps}")
    if view["cases"]:
        lines.append("cases:")
        for c in view["cases"]:
            flags = f"spec{'✓' if c['spec'] else '✗'} report{'✓' if c['report'] else '✗'}"
            note = f" — {c['note']}" if c["note"] else ""
            lines.append(f"  {c['path']}  {flags}{note}")
    if view["uncommitted"]:
        lines.append(f"uncommitted: {len(view['uncommitted'])} path(s)")
    for warning in view["warnings"]:
        lines.append(f"! {warning}")
    return "\n".join(lines)
