#!/usr/bin/env bash
set -euo pipefail
# Model-free live replay verification of the transaction-contribution loop.
# Requires pinned runtimes: Anvil/Cast 1.7.1 and Solidity 0.8.28 (see README.md
# and GENERAL_PIPELINE.md for installation; AUTO_PROVE_ANVIL/AUTO_PROVE_CAST/
# AUTO_PROVE_SOLC may supply explicit executable paths). No model account, RPC
# endpoint, external chain or real wallet is used. Evidence is written only to
# fresh runs/reproduced-attacks-live-* directories; recorded evidence is not
# modified.
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
python_executable="${ESCROW_PYTHON:-python3}"
export PYTHONPYCACHEPREFIX="$project_root/.tools/pycache"

stamp="$(date -u +%Y%m%d-%H%M%S)"
base="runs/reproduced-attacks-live-$stamp"
fixtures="general/fixtures/attacks"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
expect_status() { # file json_pointer expected
  actual="$("$python_executable" -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d
for part in sys.argv[2].split("."):
    v = v[int(part)] if part.lstrip("-").isdigit() else v[part]
print(v)' "$1" "$2")" || fail "cannot read $2 from $1"
  [[ "$actual" == "$3" ]] || fail "$1 $2 is '$actual', expected '$3'"
}

printf '%s\n' "1/8 unit suite"
"$python_executable" -m unittest test_attacks test_general test_app test_engine

printf '%s\n' "2/8 existing requirement violation (live replay)"
"$python_executable" -m general attack "$fixtures/snapshot.json" "$fixtures/policy.json" \
  "$fixtures/withdraw-collateral.json" --output "$base/attack-existing"
expect_status "$base/attack-existing/attack.json" status demonstrated_spec_requirement_violation
expect_status "$base/attack-existing/attack.json" attack_acceptance pending
expect_status "$base/attack-existing/attack.json" accepted False
expect_status "$base/attack-existing/attack.json" creator_approval pending
expect_status "$base/attack-existing/attack.json" contract_correspondence not_proved
expect_status "$base/attack-existing/attack.json" all_requirement_checks.CollateralBacking.status demonstrated_violation
expect_status "$base/attack-existing/replay/replay.json" status replayed
[[ -s "$base/attack-existing/report.html" ]] || fail "missing existing-attack report"

printf '%s\n' "3/8 incomplete specification versus intent (live replay)"
"$python_executable" -m general attack "$fixtures/weak-snapshot.json" "$fixtures/weak-policy.json" \
  "$fixtures/intent-gap.json" --output "$base/attack-intent"
expect_status "$base/attack-intent/attack.json" status demonstrated_intent_requirement_violation
expect_status "$base/attack-intent/attack.json" all_requirement_checks.BorrowLimit.status not_demonstrated
expect_status "$base/attack-intent/attack.json" all_requirement_checks.CollateralBacking.status demonstrated_violation
expect_status "$base/attack-intent/replay/replay.json" status replayed

printf '%s\n' "4/8 maintainer acceptance and exact-case deduplication (live replay)"
"$python_executable" -m general accept-attack "$fixtures/snapshot.json" "$fixtures/policy.json" \
  "$fixtures/withdraw-collateral.json" --registry "$base/accepted-cases" --category contract_bug \
  --reason 'Internal fixture: reviewed explicit withdrawal requirement and replay evidence.' \
  --output "$base/attack-acceptance"
expect_status "$base/attack-acceptance/attack.json" attack_acceptance accepted
cases="$(ls "$base/accepted-cases" | wc -l | tr -d ' ')"
[[ "$cases" == "1" ]] || fail "registry holds $cases cases, expected 1"
case_id="$(ls "$base/accepted-cases")"
"$python_executable" - "$fixtures/withdraw-collateral.json" "$base/dedup-submission.json" <<'PY'
import json, sys
submission = json.load(open(sys.argv[1]))
submission['contributor'] = 'different-attribution'
submission['reasoning'] = 'Different words; identical trace and requirement.'
json.dump(submission, open(sys.argv[2], 'w'), indent=2)
PY
"$python_executable" -m general accept-attack "$fixtures/snapshot.json" "$fixtures/policy.json" \
  "$base/dedup-submission.json" --registry "$base/accepted-cases" --category contract_bug \
  --reason 'Exact duplicate of the accepted case.' --output "$base/attack-dedup"
expect_status "$base/attack-dedup/attack.json" attack_acceptance duplicate
cases="$(ls "$base/accepted-cases" | wc -l | tr -d ' ')"
[[ "$cases" == "1" ]] || fail "registry holds $cases cases after duplicate, expected 1"

printf '%s\n' "5/8 original and source-patched regressions (live replay)"
set +e
"$python_executable" -m general regress-attacks "$fixtures/snapshot.json" \
  --registry "$base/accepted-cases" --output "$base/regress-original"
original_exit=$?
set -e
expect_status "$base/regress-original/regressions.json" status needs_attention
expect_status "$base/regress-original/regressions.json" cases.0.status still_violates_original_requirement
[[ "$original_exit" -ne 0 ]] || fail "original regression must exit nonzero while a case still violates"
"$python_executable" -m general regress-attacks "$fixtures/fixed-source-snapshot.json" \
  --registry "$base/accepted-cases" --output "$base/regress-source-patched"
expect_status "$base/regress-source-patched/regressions.json" status passed_replay
expect_status "$base/regress-source-patched/regressions.json" cases.0.status passed_replay

printf '%s\n' "6/8 stale snapshot digest rejected before replay"
"$python_executable" - "$fixtures/withdraw-collateral.json" "$base/stale-submission.json" <<'PY'
import json, sys
submission = json.load(open(sys.argv[1]))
submission['snapshot_digest'] = '0' * 64
json.dump(submission, open(sys.argv[2], 'w'), indent=2)
PY
set +e
"$python_executable" -m general attack "$fixtures/snapshot.json" "$fixtures/policy.json" \
  "$base/stale-submission.json" --output "$base/attack-stale" >"$base/stale.log" 2>&1
stale_exit=$?
set -e
[[ "$stale_exit" -ne 0 ]] || fail "stale submission must be rejected"
grep -q "different snapshot" "$base/stale.log" || fail "stale submission rejection reason missing"
[[ ! -d "$base/attack-stale/replay" ]] || fail "stale submission must not start a replay"

printf '%s\n' "7/8 runtime failure stays inconclusive, never a successful attack"
set +e
AUTO_PROVE_SOLC=/usr/bin/false "$python_executable" -m general attack "$fixtures/snapshot.json" \
  "$fixtures/policy.json" "$fixtures/withdraw-collateral.json" \
  --output "$base/attack-runtime-failure" >"$base/runtime-failure.log" 2>&1
runtime_exit=$?
set -e
[[ "$runtime_exit" -ne 0 ]] || fail "runtime failure must not exit as a demonstrated violation"
expect_status "$base/attack-runtime-failure/attack.json" status inconclusive
expect_status "$base/attack-runtime-failure/attack.json" attack_acceptance pending
expect_status "$base/attack-runtime-failure/replay/replay.json" status inconclusive

printf '%s\n' "8/8 second contract family: MilestoneEscrow (safe, failing and clarification cases)"
escrow="general/fixtures/escrow"
set +e
"$python_executable" -m general attack "$escrow/snapshot.json" "$escrow/draft-policy.json" \
  "$escrow/attack-safe.json" --output "$base/escrow-safe" >"$base/escrow-safe.log" 2>&1
safe_exit=$?
set -e
[[ "$safe_exit" -ne 0 ]] || fail "a safe trace must not be reported as a demonstrated violation"
expect_status "$base/escrow-safe/attack.json" status not_demonstrated
"$python_executable" -m general attack "$escrow/snapshot.json" "$escrow/draft-policy.json" \
  "$escrow/attack-double-release.json" --output "$base/escrow-double-release"
expect_status "$base/escrow-double-release/attack.json" status demonstrated_proposed_requirement_violation
set +e
"$python_executable" -m general accept-attack "$escrow/snapshot.json" "$escrow/draft-policy.json" \
  "$escrow/attack-double-release.json" --registry "$base/escrow-cases" --category contract_bug \
  --reason 'must stay blocked' --output "$base/escrow-accept-blocked" >"$base/escrow-blocked.log" 2>&1
blocked_exit=$?
set -e
[[ "$blocked_exit" -ne 0 ]] || fail "acceptance must stay blocked while a requirement is pending review"
grep -q "Review the operational requirement" "$base/escrow-blocked.log" || fail "missing blocked-acceptance reason"
"$python_executable" -m general propose-policy "$escrow/snapshot.json" "$escrow/draft-policy.json" \
  --output "$base/escrow-proposal"
"$python_executable" - "$base/escrow-proposal/proposal.json" "$base/escrow-decisions.json" <<'PY'
import json, sys
packet = json.load(open(sys.argv[1]))
decisions = {'version':'policy-review-v1','snapshot_digest':packet['snapshot_digest'],
 'policy_digest':packet['policy_digest'],'creator':'internal-fixture-maintainer',
 'decisions':[
  {'requirement_id':'ReleaseWithinDeposit','decision':'approved',
   'reason':'Released must stay within deposited at every step; matches the quoted intent.'},
  {'requirement_id':'OtherPayerBacking','decision':'rejected',
   'reason':'The proposed reading does not capture the registered-seller restriction; needs a contract change and creator clarification.'}]}
json.dump(decisions, open(sys.argv[2], 'w'), indent=2)
PY
"$python_executable" -m general review-policy "$escrow/snapshot.json" \
  "$base/escrow-proposal/proposal.json" "$base/escrow-decisions.json" --output "$base/escrow-review"
expect_status "$base/escrow-review/review-record.json" rejected_requirements.0 OtherPayerBacking
"$python_executable" - "$base/escrow-review/reviewed-policy.json" "$escrow/attack-double-release.json" \
  "$base/escrow-reviewed-submission.json" <<'PY'
import json, sys
from general.core import digest
reviewed = json.load(open(sys.argv[1]))
submission = json.load(open(sys.argv[2]))
submission['policy_digest'] = digest(reviewed)
json.dump(submission, open(sys.argv[3], 'w'), indent=2)
PY
"$python_executable" -m general attack "$escrow/snapshot.json" \
  "$base/escrow-review/reviewed-policy.json" "$base/escrow-reviewed-submission.json" \
  --output "$base/escrow-attack-reviewed"
expect_status "$base/escrow-attack-reviewed/attack.json" status demonstrated_spec_requirement_violation
"$python_executable" -m general accept-attack "$escrow/snapshot.json" \
  "$base/escrow-review/reviewed-policy.json" "$base/escrow-reviewed-submission.json" \
  --registry "$base/escrow-cases" --category contract_bug \
  --reason 'Reviewed escrow policy; replayed double-release violation.' \
  --output "$base/escrow-acceptance"
expect_status "$base/escrow-acceptance/attack.json" attack_acceptance accepted
set +e
"$python_executable" -m general regress-attacks "$escrow/snapshot.json" \
  --registry "$base/escrow-cases" --output "$base/escrow-regressions" >"$base/escrow-regress.log" 2>&1
escrow_regress_exit=$?
set -e
[[ "$escrow_regress_exit" -ne 0 ]] || fail "unrepaired escrow regression must exit nonzero"
expect_status "$base/escrow-regressions/regressions.json" cases.0.status still_violates_original_requirement

printf '%s\n' "Live transaction-contribution loop verified: $base"
printf '%s\n' "Acceptance remains maintainer-only; creator approval stays pending; no model/EVM equivalence is proved."
