#!/bin/sh
# Smoke differential run of the heartbeat scenario (used by `make test-differential`).
# Usage: smoke.sh <uxas-cpp-binary>
# Reference selection: real Ada (UXAS_ADA_BIN or uxas_ada on PATH) > golden file
# > C++-only smoke (NO parity check; says so loudly).
# Set UXAS_REQUIRE_PARITY=1 to fail (exit 4) instead of falling back to C++-only.
set -u
CPP_BIN=${1:?usage: smoke.sh <uxas-binary>}
HERE=$(cd "$(dirname "$0")" && pwd)
SCENARIO=$HERE/scenarios/heartbeat.json
GOLDEN=${UXAS_GOLDEN:-$HERE/golden/heartbeat.ada.json}
RUN="python3 -E $HERE/run_differential.py $SCENARIO --cpp-bin $CPP_BIN"

ADA_BIN=$(python3 -E "$HERE/run_differential.py" --resolve-bin ada) || ADA_BIN=
if [ -z "$ADA_BIN" ] && [ -n "${UXAS_ADA_BIN:-}" ]; then
    echo "warning: UXAS_ADA_BIN=$UXAS_ADA_BIN not found" >&2
fi

if [ -n "$ADA_BIN" ]; then
    echo "[differential] Ada reference: $ADA_BIN"
    exec $RUN --ada-bin "$ADA_BIN"
elif [ -f "$GOLDEN" ]; then
    echo "[differential] Ada binary unavailable; comparing against golden $GOLDEN"
    exec $RUN --golden "$GOLDEN"
elif [ "${UXAS_REQUIRE_PARITY:-0}" = 1 ]; then
    echo "[differential] UXAS_REQUIRE_PARITY=1 but no Ada binary and no golden $GOLDEN" >&2
    exit 4
else
    echo "[differential] Ada reference unavailable (no UXAS_ADA_BIN/uxas_ada, no golden $GOLDEN): parity NOT checked; running C++-only smoke"
    exec $RUN --cpp-only
fi
