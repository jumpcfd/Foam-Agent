# config.py
"""Server settings, resolved from the environment and the settings files.

Nothing here configures a model: this process runs none. What model the harness uses is
the harness's business, and what the independent audit runs on is `review.command` in the
same settings file (see foamagent.review.settings).

Every field below is resolved through foamagent.settings, so each one can be set in four
places -- environment variable, project file, user file, default -- and each says which of
them it came from when it is logged.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from foamagent import paths
from foamagent import settings as settings_module
from foamagent.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RUNTIME = "native"
DEFAULT_IMAGE = "openfoam/openfoam10-paraview56"  # pullable from Docker Hub
DEFAULT_BASHRC = "/opt/openfoam10/etc/bashrc"     # bashrc path inside the image
DEFAULT_INDEX_MAX_FILE_KB = 100

RUNTIMES = ("native", "docker")
FORKS = ("foundation", "esi")

# The settings this module reads, as dotted keys, with the environment variable that
# overrides each. `foamagent config show` walks this table, so a setting added here appears
# there without having to be listed in two places.
CONFIG_KEYS = {
    "openfoam.runtime": "FOAMAGENT_OPENFOAM_RUNTIME",
    "openfoam.image": "FOAMAGENT_OPENFOAM_IMAGE",
    "openfoam.bashrc": "FOAMAGENT_OPENFOAM_BASHRC",
    "openfoam.fork": "FOAMAGENT_OPENFOAM_FORK",
    "index.dir": "FOAMAGENT_INDEX_DIR",
    "index.max_file_kb": "FOAMAGENT_INDEX_MAX_FILE_KB",
    "skills.dir": "FOAMAGENT_SKILLS_DIR",
    "paraview.dir": "FOAMAGENT_PARAVIEW_MCP_DIR",
}


@dataclass
class Config:
    run_directory: Path = field(default_factory=paths.runs_dir)
    case_dir: str = ""

    # Which fork's conventions to generate for. Empty means "whichever one is installed":
    # environment detection answers it. Setting this overrides the measurement, which is
    # what an ESI user reproducing Foundation output wants and nobody else does.
    openfoam_fork: str = ""

    # OpenFOAM execution runtime:
    # - "native": source $WM_PROJECT_DIR/etc/bashrc in the current machine
    # - "docker": run inside openfoam_image, mounting the case at the same absolute path
    openfoam_runtime: str = DEFAULT_RUNTIME
    openfoam_image: str = DEFAULT_IMAGE
    openfoam_bashrc: str = DEFAULT_BASHRC

    # Where each field's value came from, kept so that `foamagent config show` and the
    # diagnostics can say "user settings" or "env FOAMAGENT_..." without reading the files
    # a second time.
    sources: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Resolve every field, and log what was used and where it came from.

        A field the caller passed explicitly keeps the value it was given: the settings
        answer "what did the user configure", and are not an override of what a caller
        asked for. Only fields still holding their default are resolved.
        """
        resolved = settings_module.load()

        def apply(attribute: str, setting) -> None:
            setattr(self, attribute, setting.value)
            self.sources[setting.key] = setting.source
            logger.info(f"<config>{attribute}={setting.value} ({setting.source})</config>")

        if self.openfoam_runtime == DEFAULT_RUNTIME:
            apply("openfoam_runtime", resolved.text(
                "openfoam.runtime",
                env=CONFIG_KEYS["openfoam.runtime"],
                default=DEFAULT_RUNTIME,
                choices=RUNTIMES,
                lower=True,
            ))
        if self.openfoam_image == DEFAULT_IMAGE:
            apply("openfoam_image", resolved.text(
                "openfoam.image", env=CONFIG_KEYS["openfoam.image"], default=DEFAULT_IMAGE
            ))
        if self.openfoam_bashrc == DEFAULT_BASHRC:
            apply("openfoam_bashrc", resolved.text(
                "openfoam.bashrc", env=CONFIG_KEYS["openfoam.bashrc"], default=DEFAULT_BASHRC
            ))
        if self.openfoam_fork == "":
            apply("openfoam_fork", resolved.text(
                "openfoam.fork",
                env=CONFIG_KEYS["openfoam.fork"],
                default="",
                choices=FORKS,
                lower=True,
            ))


def describe(resolved: Optional["settings_module.Settings"] = None):
    """Every server setting, resolved, for `foamagent config show`.

    The index directory is reported as the place it actually resolves to rather than as an
    empty default, because "where does the catalogue go" is the question being asked.
    """
    from foamagent.settings import Setting

    resolved = resolved or settings_module.load()
    rows = {
        "openfoam.runtime": resolved.text(
            "openfoam.runtime", env=CONFIG_KEYS["openfoam.runtime"],
            default=DEFAULT_RUNTIME, choices=RUNTIMES, lower=True,
        ),
        "openfoam.image": resolved.text("openfoam.image", env=CONFIG_KEYS["openfoam.image"], default=DEFAULT_IMAGE),
        "openfoam.bashrc": resolved.text("openfoam.bashrc", env=CONFIG_KEYS["openfoam.bashrc"], default=DEFAULT_BASHRC),
        "openfoam.fork": resolved.text(
            "openfoam.fork", env=CONFIG_KEYS["openfoam.fork"],
            default="", choices=FORKS, lower=True,
        ),
    }

    index = index_dir_setting(resolved)
    if index.value is None:
        from foamagent.indexing import index_root

        index = Setting(index.key, index_root(), index.source)
    rows[index.key] = index
    max_file_kb = index_max_file_kb_setting(resolved)
    rows[max_file_kb.key] = max_file_kb

    skills = skills_dir_setting(resolved)
    if skills.value is None:
        skills = Setting(skills.key, "(none)", skills.source)
    rows[skills.key] = skills

    paraview = paraview_dir_setting(resolved)
    if paraview.value is None:
        paraview = Setting(paraview.key, "(none)", paraview.source)
    rows[paraview.key] = paraview

    fork = rows["openfoam.fork"]
    if not fork.value:
        rows["openfoam.fork"] = Setting(fork.key, "(measured)", fork.source)
    return list(rows.values())


def index_dir_setting(resolved: Optional["settings_module.Settings"] = None):
    """Where built libraries are kept. ``None`` means the default cache location."""
    resolved = resolved or settings_module.load()
    return resolved.path("index.dir", env=CONFIG_KEYS["index.dir"], default=None)


def index_max_file_kb_setting(resolved: Optional["settings_module.Settings"] = None):
    """The size above which a tutorial file is recorded but its contents are not kept."""
    resolved = resolved or settings_module.load()
    return resolved.integer(
        "index.max_file_kb",
        env=CONFIG_KEYS["index.max_file_kb"],
        default=DEFAULT_INDEX_MAX_FILE_KB,
    )


def skills_dir_setting(resolved: Optional["settings_module.Settings"] = None):
    """Where user-supplied skills are read from by `foamagent install`. ``None`` means none."""
    resolved = resolved or settings_module.load()
    return resolved.path("skills.dir", env=CONFIG_KEYS["skills.dir"], default=None)


def paraview_dir_setting(resolved: Optional["settings_module.Settings"] = None):
    """The paraview_mcp checkout (github.com/jumpcfd/paraview_mcp) `foamagent install`
    wires in for Worker, Reviewer and Judge alike. ``None`` means none: that server needs
    ParaView itself, which is not this project's business to install, so it is opt-in."""
    resolved = resolved or settings_module.load()
    return resolved.path("paraview.dir", env=CONFIG_KEYS["paraview.dir"], default=None)
