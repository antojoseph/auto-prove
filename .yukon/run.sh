#!/usr/bin/env bash
set -euo pipefail
: "${AUTO_PROVE_MODEL:?Set a fixed model available to the benchmark account}"
rm -f .yukon/score.json
python3 -m general.benchmark --model "$AUTO_PROVE_MODEL" --output ".yukon/runs/$(date -u +%Y%m%d-%H%M%S)"
