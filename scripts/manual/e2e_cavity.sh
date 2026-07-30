#!/usr/bin/env bash
# End-to-end regression: lid-driven cavity, driven by a real harness session.
#
# This is the acceptance check that the whole path works -- the harness reads the
# catalogue, writes a case, runs OpenFOAM, has it reviewed and reports. It is run by hand,
# because it starts a model session and runs a solver; neither belongs in CI.
#
# What it needs:
#   - an OpenFOAM reachable (sourced, or FOAMAGENT_OPENFOAM_RUNTIME=docker)
#   - `foamagent index build` already run for that installation
#   - the harness CLI on PATH (claude by default; FOAMAGENT_E2E_HARNESS to change it)
#   - time. The cavity solves in seconds; the two reviews and the report are three further
#     model sessions, and the whole thing runs to the better part of an hour. Do not wrap
#     this in a short `timeout`.
#
# Usage:
#   scripts/manual/e2e_cavity.sh [work_dir]
set -euo pipefail

WORK_DIR="${1:-/tmp/foamagent-e2e-cavity}"
HARNESS="${FOAMAGENT_E2E_HARNESS:-claude}"
CASE_NAME="${FOAMAGENT_E2E_CASE:-cavity}"
CASE_DIR="${WORK_DIR}/${CASE_NAME}"

REQUIREMENT="${FOAMAGENT_E2E_REQUIREMENT:-Simulate incompressible lid-driven cavity flow at Re=1000. \
The cavity is a unit square, meshed 20x20 with one cell through the thickness. The top wall \
moves at 1 m/s in x; the other walls are no-slip; front and back are empty. Kinematic \
viscosity is 1e-3 m^2/s. Run to t=10 with a time step of 0.005, writing every 100 steps. \
Put the case in ${CASE_DIR}. Work without asking me anything further: assume what you must \
and record the assumptions in spec.md.}"

if ! command -v "${HARNESS}" >/dev/null 2>&1; then
  echo "The harness CLI '${HARNESS}' is not on PATH. Install it, or set FOAMAGENT_E2E_HARNESS." >&2
  exit 2
fi

echo "[1/4] Preparing ${WORK_DIR}"
mkdir -p "${WORK_DIR}"
cd "${WORK_DIR}"
foamagent install claude-code >/dev/null
echo "      wrote .mcp.json and the skill"

echo "[2/4] Running the harness non-interactively (this takes several minutes)"
# --allowed-tools is deliberately wide here: unlike the review sessions, this one *is* the
# agent under test, so it needs to write files and call every Foam-Agent tool.
"${HARNESS}" -p "${REQUIREMENT}" \
  --allowed-tools "Read,Write,Edit,Glob,Grep,Bash,mcp__foamagent" \
  | tee "${WORK_DIR}/harness.log"

echo "[3/4] Checking the case"
FAILED=0
check() {
  if eval "$2"; then
    echo "      ok   $1"
  else
    echo "      FAIL $1" >&2
    FAILED=1
  fi
}

reviews=$(ls "${CASE_DIR}"/review-[0-9]*.md 2>/dev/null | wc -l)
responses=$(ls "${CASE_DIR}"/response-[0-9]*.md 2>/dev/null | wc -l)

check "the case directory exists"        "[ -d '${CASE_DIR}' ]"
check "spec.md was written"              "[ -s '${CASE_DIR}/spec.md' ]"
check "spec.md quotes the request"       "grep -qi 'Re=1000' '${CASE_DIR}/spec.md'"
check "the solver log ends with End"     "tail -5 '${CASE_DIR}'/log.* 2>/dev/null | grep -q '^End'"
# Two stages, so two documents: one before anything was built, one after it ran. A single
# review means the result stage silently did not happen -- which is exactly the failure the
# 900s default timeout produced on the first run of this script.
check "both stages were reviewed"        "[ '${reviews}' -ge 2 ]"
check "every finding was answered"       "[ '${reviews}' = '${responses}' ]"
check "a report was produced"            "[ -s '${CASE_DIR}/report.md' ]"
check "the report states the limits"     "grep -qiE 'limit|限界' '${CASE_DIR}/report.md'"
check "no review was skipped"            "! ls '${CASE_DIR}'/*not-carried-out* >/dev/null 2>&1"

echo "[4/4] Result"
if [ "${FAILED}" -ne 0 ]; then
  echo "      E2E regression FAILED; see ${WORK_DIR}/harness.log" >&2
  exit 1
fi

echo "      E2E regression passed: ${CASE_DIR}"
echo "      Compare the reported velocity profiles against Ghia et al. (1982) by hand."
