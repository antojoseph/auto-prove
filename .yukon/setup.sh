#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python3 experiments/uniswap-v4/setup_runtime.py
bash experiments/uniswap-v4/setup.sh
