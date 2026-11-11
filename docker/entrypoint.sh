#!/bin/sh
# Generate synthetic sources on first start, rebuild the database, serve the API.
set -e

triage generate --if-missing --seed "${TRIAGE_SEED:-42}"
triage build
exec triage serve --host 0.0.0.0 --port 8000
