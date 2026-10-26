#!/usr/bin/env bash
# Model-free verification of the automatic negative-case loop. Needs Anvil/Cast
# 1.7.1, Solidity 0.8.28 (AUTO_PROVE_SOLC) and Docker with the pinned verifier
# image (docker build -t auto-prove-verifier:lean4.35.0-rc2 general/verifier).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPYCACHEPREFIX="$PWD/.tools/pycache"
python3 -m unittest test_autoloop test_attacks test_contribution_benchmark test_general test_app test_engine
python3 scripts/verify_autoloop.py "$@"
