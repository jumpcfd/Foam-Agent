# Runs FoamBench_basic end to end inside one isolated container: this image already has
# OpenFOAM (Foundation) built in, so Foam-Agent drives it natively rather than spawning a
# solver container (see FOAMAGENT_OPENFOAM_BASHRC below) -- no docker-in-docker needed.
#
# Pinned to v10, not a newer Foundation release: FoamBench's GT_Files reference cases and
# its fvSolution dictionaries predate the v11+ solver unification (pisoFoam/icoFoam merged
# into incompressibleFluid, which wants a PIMPLE sub-dict the shipped GT_Files don't have).
# Confirmed the mismatch directly -- GT_Files/Allrun FOAM FATAL IO ERRORs on v14, runs clean
# on v10. The evaluator's VTK reader also chokes on v14's newer named-dimensions syntax
# (`dimensions [velocity];`) regardless of which OpenFOAM produced the submission.
#
# Runs as a plain user, not root: an AI harness that notices it's root sometimes reacts by
# adding unasked-for "security" ceremony, and a non-root writer also means files land on a
# host bind mount already owned by the host user instead of root (no `chown` needed after).
# UID/GID default to 1000, the usual first-user id on Linux; override at build time with
# --build-arg UID=$(id -u) --build-arg GID=$(id -g) if that doesn't match.
#
# Build from the repo root so `COPY . .` picks up the whole Foam-Agent tree:
#   docker build -f foambench-basic/Dockerfile -t foambench-basic .
# Run (needs Claude auth -- either an API key or a mounted `~/.claude` login):
#   docker run -it --rm -e ANTHROPIC_API_KEY foambench-basic
FROM openfoam/openfoam10-paraview56:latest

# The base image's own ENTRYPOINT (an interactive banner) is replaced below.
USER root

ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID foambench \
    && useradd -m -u $UID -g $GID -s /bin/bash foambench

# The base OpenFOAM image has no curl; the two installers below need it.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

USER foambench
ENV HOME=/home/foambench
WORKDIR $HOME

RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://astral.sh/uv/install.sh | sh
ENV PATH="$HOME/.local/bin:${PATH}"

# Foam-Agent's "native" runtime already defaults to this exact path; set explicitly so a
# change to that default can't silently point this image at the wrong OpenFOAM.
ENV FOAMAGENT_OPENFOAM_BASHRC=/opt/openfoam10/etc/bashrc

ENV FoamAgent_PATH=$HOME/Foam-Agent
COPY --chown=foambench:foambench . $FoamAgent_PATH
WORKDIR $FoamAgent_PATH
RUN uv sync --frozen --no-dev
ENV PATH="$FoamAgent_PATH/.venv/bin:${PATH}"

# Unpacked once at build time into the layout foambench_run.py and the evaluator expect
# (Dataset/Basic/<case>/{usr_requirement.txt,GT_Files/}).
RUN python -m scripts.bench.foambench_unpack foambench-basic/FoamBench_basic.json \
        --destination $HOME/foambench/Dataset/Basic --split Basic

# `foamagent doctor`/the harness read $WM_PROJECT_DIR from the live environment rather than
# sourcing the bashrc themselves, so every entry into the container has to source it: the
# entrypoint covers `docker run`, and .bashrc covers a plain `docker exec ... bash`.
RUN echo "source $FOAMAGENT_OPENFOAM_BASHRC" >> $HOME/.bashrc

USER root
COPY foambench-basic/entrypoint.sh /usr/local/bin/foambench-entrypoint.sh
RUN chmod +x /usr/local/bin/foambench-entrypoint.sh
USER foambench

# Deterministic given this image's fixed OpenFOAM install, so it's baked in rather than left
# as a step every container has to redo: the harness reads this catalogue before writing
# any case.
RUN bash -c "source $FOAMAGENT_OPENFOAM_BASHRC && foamagent index build"

WORKDIR $HOME/foambench
ENTRYPOINT ["/usr/local/bin/foambench-entrypoint.sh"]
CMD ["/bin/bash"]
