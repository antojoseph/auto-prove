#!/usr/bin/env bash
set -euo pipefail
command -v python3 >/dev/null
command -v docker >/dev/null
command -v codex >/dev/null
docker build -t auto-prove-verifier:lean4.35.0-rc2 general/verifier
