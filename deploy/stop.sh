#!/bin/bash
# Stop the stack. Data stays in Docker volumes; deploy/start.sh brings it back.
cd "$(dirname "$0")"
docker compose -f compose.yml down
