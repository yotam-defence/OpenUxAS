#!/bin/sh
# Smoke differential run of the heartbeat scenario (used by `make test-differential`).
# Usage: smoke.sh <uxas-cpp-binary>
# Reference selection: real Ada (UXAS_ADA_BIN or uxas_ada on PATH) > golden file
# > C++-only smoke (NO parity check; says so loudly).
set -u
CPP_BIN=${1:?usage: smoke.sh <uxas-binary>}
HERE=$(cd "$(dirname "$0")" && pwd)
SCENARIO=$HERE/scenarios/heartbeat.json
GOLDEN=${UXAS_GOLDEN:-$HERE/golden/heartbeat.ada.json}
RUN="python3 -E $HERE/run_differential.py $SCENARIO --cpp-bin $CPP_BIN"

ADA_BIN=
if [ -n "${UXAS_ADA_BIN:-}" ]; then
    if [ -x "$UXAS_ADA_BIN" ]; then ADA_BIN=$UXAS_ADA_BIN
    elif command -v "$UXAS_ADA_BIN" >/dev/null 2>&1; then ADA_BIN=$(command -v "$UXAS_ADA_BIN")
    else echo "warning: UXAS_ADA_BIN=$UXAS_ADA_BIN not found" >&2; fi
elif command -v uxas_ada >/dev/null 2>&1; then
    ADA_BIN=$(command -v uxas_ada)
fi

if [ -n "$ADA_BIN" ]; then
    echo "[differential] Ada reference: $ADA_BIN"
    exec $RUN --ada-bin "$ADA_BIN"
elif [ -f "$GOLDEN" ]; then
    echo "[differential] Ada binary unavailable; comparing against golden $GOLDEN"
    exec $RUN --golden "$GOLDEN"
else
    echo "[differential] Ada reference unavailable (no UXAS_ADA_BIN/uxas_ada, no golden $GOLDEN): parity NOT checked; running C++-only smoke"
    exec $RUN --cpp-only
fi
