#!/usr/bin/env bash
# spec.prove automatic negative-case loop.
#
# Hosted (AUTO_PROVE_HOSTED=1 and OPENROUTER_API_KEY present): every submitted
# contribution is replayed, judged, credited and, when accepted, repaired into
# the next live challenge version by the host-funded judge, repair author and an
# independent different-family reviewer behind the mechanical anti-weakening gate.
#
# Local (anything else): mechanical preflight only. No model calls; the score
# file is marked authoritative: false.
#
# Fail closed: the stale score is wiped before any fallible work; a nonzero
# exit never leaves a score file.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

rm -f .yukon/score.json
[[ -x .tools/foundry/bin/anvil ]] || { echo "!! .tools/foundry missing; run .yukon/setup.sh first" >&2; exit 1; }
[[ -x .tools/solc/solc ]] || { echo "!! .tools/solc missing; run .yukon/setup.sh first" >&2; exit 1; }
export PATH="$root/.tools/foundry/bin:$PATH"
export AUTO_PROVE_SOLC="$root/.tools/solc/solc"

challenge="${AUTO_PROVE_CHALLENGE_DIR:-challenge}"
run=".yukon/runs/$(date -u +%Y%m%d-%H%M%S)"
mkdir -p .yukon/runs
if [[ "${AUTO_PROVE_HOSTED:-0}" == "1" && -n "${OPENROUTER_API_KEY:-}" ]]; then
  submitted=()
  [[ -n "${AUTO_PROVE_SUBMITTED_AT:-}" ]] && submitted=(--submitted-at "$AUTO_PROVE_SUBMITTED_AT")
  python3 -m general.auto process --challenge "$challenge" --submission submission \
    --output "$run" --score-path .yukon/score.json --roles openrouter "${submitted[@]+"${submitted[@]}"}"
else
  echo "local preflight: mechanical replay only, no model calls, score not authoritative" >&2
  python3 -m general.auto preflight --challenge "$challenge" --submission submission \
    --output "$run" --score-path .yukon/score.json
fi
echo "score written: .yukon/score.json (evidence: $run)"
