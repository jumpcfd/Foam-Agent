#!/bin/bash
# Sources OpenFOAM before anything else runs, and fails loudly if it didn't load --
# `foamagent doctor` and the harness both just read $WM_PROJECT_DIR from the environment,
# they don't source the bashrc themselves.
set -e

set +e
source "$FOAMAGENT_OPENFOAM_BASHRC"
set -e

if [ -z "$WM_PROJECT_DIR" ] || ! command -v blockMesh >/dev/null 2>&1; then
    echo "ERROR: OpenFOAM environment failed to load from $FOAMAGENT_OPENFOAM_BASHRC" >&2
    exit 1
fi

# Only the default CMD (no override) goes interactive -- "bash" is also the interpreter for
# `docker run image bash -c '...'`, which must exec that command, not swallow it.
if [ "$1" = "/bin/bash" ] || [ -z "$1" ]; then
    exec /bin/bash -i
else
    exec "$@"
fi
