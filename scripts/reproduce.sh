#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
python_executable="${ESCROW_PYTHON:-python3}"
forge_executable="${ESCROW_FORGE:-forge}"
export PYTHONPYCACHEPREFIX="$project_root/.tools/pycache"

"$python_executable" -m unittest -v
"$python_executable" app.py demo --output runs/reproduced-demo
"$python_executable" app.py evaluate \
  runs/validated-live-loop/round-1/candidate.json \
  runs/validated-live-loop/round-1/review.json \
  --output runs/reproduced-live-round-1
"$python_executable" app.py evaluate \
  runs/validated-live-loop/round-2/candidate.json \
  runs/validated-live-loop/round-2/review.json \
  --output runs/reproduced-live-round-2

"$python_executable" - <<'PY'
import json
from pathlib import Path
first=json.loads(Path('runs/reproduced-live-round-1/evaluation.json').read_text())
last=json.loads(Path('runs/reproduced-live-round-2/evaluation.json').read_text())
assert first['validated_findings']==1 and first['unsupported_findings']==0
assert first['lean']['kernel_checked']
assert last['validated_findings']==0 and last['unsupported_findings']==0
assert not last['bounded_check']['witnesses']
assert last['lean']['reference_equivalence_proved']
assert last['human_approval']=='pending' and not last['accepted']
print('Recorded live-loop evidence reproduced; creator approval remains pending.')
PY

"$python_executable" generate_solidity_replays.py
if [[ -n "${ESCROW_SOLC:-}" ]]; then
  "$forge_executable" test --root contracts --use "$ESCROW_SOLC" --offline
else
  "$forge_executable" test --root contracts
fi
printf '%s\n' 'Reproduction complete. Open runs/reproduced-demo/report.html to inspect all nine cases.'
