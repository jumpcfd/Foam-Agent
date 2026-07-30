# config.py
"""Server settings, resolved from the environment.

Nothing here configures a model: this process runs none. What model the harness uses is
the harness's business, and what model the independent audit runs is the command in
foamagent.review's YAML settings.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from foamagent import paths
from foamagent.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Config:
    run_directory: Path = field(default_factory=paths.runs_dir)
    case_dir: str = ""
    max_time_limit: int = 3600  # Max time limit after which the openfoam run will be terminated, in seconds

    # Which fork's conventions to generate for. Empty means "whichever one is installed":
    # environment detection answers it. Setting this overrides the measurement, which is
    # what an ESI user reproducing Foundation output wants and nobody else does.
    openfoam_fork: str = ""

    # OpenFOAM execution runtime:
    # - "native": source $WM_PROJECT_DIR/etc/bashrc in the current machine
    # - "docker": run inside openfoam_image, mounting the case at the same absolute path
    openfoam_runtime: str = "native"
    openfoam_image: str = "openfoam/openfoam10-paraview56"  # pullable from Docker Hub
    openfoam_bashrc: str = "/opt/openfoam10/etc/bashrc"  # bashrc path inside the image

    def __post_init__(self) -> None:
        """Load config overrides from environment variables.

        Priority: env var (if set & non-empty) > default value.
        Always prints what value is used to make runs reproducible.
        """

        def _env_nonempty(key: str) -> str | None:
            v = os.getenv(key)
            if v is None:
                return None
            v = v.strip()
            return v if v else None

        # Integer overrides (time limits)
        raw = _env_nonempty("FOAMAGENT_MAX_TIME_LIMIT")
        if raw is not None:
            try:
                self.max_time_limit = int(raw)
                logger.info(f"<config>max_time_limit={self.max_time_limit} (env:FOAMAGENT_MAX_TIME_LIMIT)</config>")
            except ValueError:
                logger.info(
                    f"<config>max_time_limit={self.max_time_limit} "
                    f"(default; invalid env:FOAMAGENT_MAX_TIME_LIMIT={raw!r})</config>"
                )

        # OpenFOAM execution runtime overrides
        runtime_key = "FOAMAGENT_OPENFOAM_RUNTIME"
        runtime_env = _env_nonempty(runtime_key)
        if runtime_env is not None:
            allowed_runtimes = {"native", "docker"}
            if runtime_env.lower() in allowed_runtimes:
                self.openfoam_runtime = runtime_env.lower()
                logger.info(f"<config>openfoam_runtime={self.openfoam_runtime} (env:{runtime_key})</config>")
            else:
                logger.info(
                    f"<config>openfoam_runtime={self.openfoam_runtime} (default; invalid env:{runtime_key}={runtime_env!r})</config>"
                )
        else:
            logger.info(f"<config>openfoam_runtime={self.openfoam_runtime} (default)</config>")

        image_env = _env_nonempty("FOAMAGENT_OPENFOAM_IMAGE")
        if image_env is not None:
            self.openfoam_image = image_env
            logger.info(f"<config>openfoam_image={self.openfoam_image} (env:FOAMAGENT_OPENFOAM_IMAGE)</config>")

        bashrc_env = _env_nonempty("FOAMAGENT_OPENFOAM_BASHRC")
        if bashrc_env is not None:
            self.openfoam_bashrc = bashrc_env
            logger.info(f"<config>openfoam_bashrc={self.openfoam_bashrc} (env:FOAMAGENT_OPENFOAM_BASHRC)</config>")

        # OpenFOAM Fork Override
        fork_key = "FOAMAGENT_OPENFOAM_FORK"
        fork_env = _env_nonempty(fork_key)
        if fork_env is not None:
            allowed_forks = {"foundation", "esi"}
            if fork_env.lower() in allowed_forks:
                self.openfoam_fork = fork_env.lower()
                logger.info(f"<config>openfoam_fork={self.openfoam_fork} (env:{fork_key})</config>")
            else:
                self.openfoam_fork = ""  # Unrecognised: fall back to what is installed
                logger.info(f"<config>openfoam_fork=(detected; invalid env:{fork_key}={fork_env!r})</config>")
        else:
            logger.info("<config>openfoam_fork=(detected)</config>")
