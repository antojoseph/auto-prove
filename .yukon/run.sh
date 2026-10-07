#!/usr/bin/env bash
# Fail-closed benchmark runner for spec.prove:
#   1. Wipe the stale score BEFORE any fallible work, so a failed run can
#      never expose an older result.
#   2. Re-derive the pinned runtimes installed by setup.sh (environment
#      variables do not persist between Yukon commands).
#   3. Run the trusted verifier. It replays every submitted contribution on a
#      disposable local Anvil and kernel-checks optional formal evidence in
#      the isolated Docker verifier. Nonzero exit always means: no score file.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

rm -f .yukon/score.json
[[ -x .tools/foundry/bin/anvil ]] || { echo "!! .tools/foundry missing; run .yukon/setup.sh first" >&2; exit 1; }
[[ -x .tools/solc/solc ]] || { echo "!! .tools/solc missing; run .yukon/setup.sh first" >&2; exit 1; }

export PATH="$root/.tools/foundry/bin:$PATH"
export AUTO_PROVE_SOLC="$root/.tools/solc/solc"

run=".yukon/runs/$(date -u +%Y%m%d-%H%M%S)"
python3 -m general.contribution_benchmark \
  --challenge challenge --submission submission \
  --output "$run" --score-path .yukon/score.json
echo "score written: .yukon/score.json (evidence: $run)"
