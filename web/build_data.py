#!/usr/bin/env python3
"""Curate credential-free recorded evidence into web/data/site.json.

Reads only committed evidence and selected reproduced runs; emits a static
bundle for the read-only explorer. No secrets, no live replay results beyond
the recorded artifacts. Rerun after new reproduced runs to refresh the bundle.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent/'data/site.json'


def read(path):
    return json.loads((ROOT/path).read_text())


def commit():
    result = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unknown'


def violation_values(assessment):
    return assessment['violations'][0]['values'] if assessment['violations'] else None


def loop_stage(title, status, note=None, values=None):
    return {'title': title, 'status': status, 'note': note, 'values': values}


def main():
    live = 'runs/reproduced-attacks-live-20261005-173839'
    escrow_fixtures = 'general/fixtures/escrow'

    lending_attack = read(f'{live}/attack-existing/attack.json')
    intent_attack = read(f'{live}/attack-intent/attack.json')
    acceptance = read(f'{live}/attack-acceptance/attack.json')
    dedup = read(f'{live}/attack-dedup/attack.json')
    regress_original = read(f'{live}/regress-original/regressions.json')
    regress_patched = read(f'{live}/regress-source-patched/regressions.json')
    runtime_failure = read(f'{live}/attack-runtime-failure/attack.json')

    escrow_policy = read(f'{escrow_fixtures}/draft-policy.json')
    escrow_snapshot = read(f'{escrow_fixtures}/snapshot.json')
    escrow_safe = read(f'{live}/escrow-safe/attack.json')
    escrow_double = read(f'{live}/escrow-attack-reviewed/attack.json')
    escrow_review = read(f'{live}/escrow-review/review-record.json')
    escrow_regres = read(f'{live}/escrow-regressions/regressions.json')

    lending_review = read('runs/reproduced-policy-review/review-record.json')
    revised_review = read('runs/live-revised-policy-review/review-record.json')
    revised_regress = read('runs/live-revised-regressions/regressions.json')
    revised_attack = read('runs/live-revised-attack/attack.json')

    evidence_results = {}
    for name in ('collaterallock', 'borrowcap', 'deposit', 'borrowcheck'):
        evidence_results[name] = read(f'general/evidence/lending-fixed/'
                                      f'observation-{name}.json')
    evidence_results['otherclaim'] = read('general/evidence/lending-fixed/counterexample-evidence.json')
    escrow_counter = read('general/evidence/escrow/counterexample-result.json')

    report_md = (ROOT/'runs/reproduced-verification-2026-10-05/report.md').read_text()

    def frames(attack, requirement='CollateralBacking'):
        checks = attack['all_requirement_checks'].get(requirement, {}).get('checks', [])
        return [{'step': c['step'], 'satisfied': c['satisfied'], 'values': c['values']} for c in checks]

    benchmark = read('benchmark.json')
    rubric = read('.yukon/rubric.json')

    data = {
        'challenge': {
            'name': benchmark['name'],
            'description': benchmark['description'],
            'category': benchmark['category'],
            'direction': benchmark['direction'],
            'status': 'Internal pilot — staged for Yukon; registry import pending',
            'objective': 'Improve a reusable pipeline that receives Solidity source and English intent, generates '
                         'meaningful security specifications, and supplies proofs, checked attacks, or explicit '
                         'unresolved results. The same submission must work across new inputs without a bespoke '
                         'family verifier.',
            'editable_paths': benchmark['editablePaths'],
            'score_composition': '60% AI-assessed meaningful coverage / 40% formally supported coverage. Zero credit '
                                 'for unsupported coverage, unapproved assumptions that bypass an intended threat, '
                                 'vacuity or unrelated tautologies. The numeric score is an internal proxy, never an '
                                 'automatic payout rule.',
            'rubric_cases': [
                {'input': case['input'],
                 'criteria': [{'id': c['id'], 'text': c['text']} for c in case['criteria']]}
                for case in rubric['cases']
            ],
            'rewards': {
                'credit_classes': [
                    {'class': 'Discovery', 'rule': 'First reviewed contribution demonstrating a violation of a maintainer-reviewed requirement (or exact frozen Lean target) on the current version, passing fresh trusted replay.'},
                    {'class': 'Reproduction', 'rule': 'Independent replay of an accepted case from a distinct attribution and model family; never creates a second registry case.'},
                    {'class': 'Repair', 'rule': 'A revision that keeps the original case, passes historical regression, re-reviews changed mappings, and weakens no other protection.'},
                    {'class': 'Interpretation', 'rule': 'A creator-approved clarification resolving an ambiguous protection into a new approved operational requirement.'},
                ],
                'never_earns': ['Copied or semantically equivalent findings (human review, not the dedup hash, decides)',
                               'Multiple accounts attributing the same discovery; Sybil and collusion void the credit',
                               'Attacks on stale digests, submitter-supplied predicates or RPC endpoints',
                               'Pending (unreviewed) requirements or runtime failures reported as violations',
                               'Specification changes that delete the attacked protection instead of fixing the defect'],
                'budget': 'Discovery: one accepted case per requirement per version. Reproduction: two independent attributions per case. Total: twenty credit-bearing contributions per version. No payout is implemented.',
                'note': 'Full rules: REWARDS.md in the repository. Finding acceptance and payout authorization are separate steps.',
            },
            'participation': [
                {'step': 'Run the loop yourself', 'body': 'Clone the internal repo, install the pinned runtimes, and run scripts/verify_attacks.sh: the full eight-stage live loop replays on a disposable local Anvil. No model account needed.'},
                {'step': 'Compose a transaction contribution', 'body': 'Use the composer below to build a transaction-attack-v1 submission: schema-checked in your browser, digests computed client-side. Download it and run the CLI to obtain trusted receipts. This site accepts no submissions — the maintainer registry is CLI-only.'},
                {'step': 'Submit on Yukon', 'body': 'Once imported, solvers submit prompt improvements via the Yukon CLI (editable proposer/reviewer prompts). Transaction contributions follow the interim maintainer-mediated protocol: post the artifact to the version-linked discussion entry; the maintainer replays it and publishes receipts plus the acceptance decision.'},
            ],
            'blockers': 'Hosted Yukon import needs platform authentication and registry coordination. Until then this page stages the challenge: the checking machinery is fully reproducible from the internal repository.',
            'loop': [
                'Creator supplies contract source, English intent and approved assumptions',
                'Agents propose explicit requirements and a formal model',
                'Contributors submit transaction sequences challenging a requirement',
                'Trusted runner replays on a disposable local chain',
                'Creator reviews the operational interpretation before acceptance',
                'Accepted findings persist across revisions as regression cases',
            ],
        },
        'meta': {
            'title': 'Intent-grounded contract specification review',
            'repo': 'antojoseph/auto-prove', 'branch': 'general-intent-pipeline',
            'commit': commit(), 'generated': '2026-10-05',
            'tools': {'python': '3.9.6', 'anvil': '1.7.1', 'cast': '1.7.1',
                      'solc': '0.8.28+commit.7893614a', 'lean_verifier': 'Lean 4.35.0-rc2 (Docker, nanoda + con-ron)'},
            'invariants': {'accepted': False, 'creator_approval': 'pending',
                          'contract_correspondence': 'not_proved'},
            'scope_note': 'Synthetic fixtures and recorded evidence only. This site is a read-only '
                          'explorer: it hosts no checking, accepts no submissions, and proves no security.',
        },
        'verification': {
            'report_md': report_md,
            'stages': [
                loop_stage('Unit suite', '54 tests pass'),
                loop_stage('Existing requirement violation (live replay)', lending_attack['status'],
                           'withdrawal drains collateral at step 4', violation_values(lending_attack['assessment'])),
                loop_stage('Intent-gap attack (live replay)', intent_attack['status'],
                           'BorrowLimit not_demonstrated; CollateralBacking violated'),
                loop_stage('Maintainer acceptance', 'attack_acceptance: ' + acceptance['attack_acceptance'],
                           'registry case a16ab5a5…'),
                loop_stage('Exact-case deduplication', 'attack_acceptance: ' + dedup['attack_acceptance'],
                           'different attribution, same identity: still one case'),
                loop_stage('Original regression', regress_original['cases'][0]['status'],
                           'intentional nonzero exit'),
                loop_stage('Source-patched regression', regress_patched['cases'][0]['status'],
                           'repaired withdrawal behavior, old formal spec preserved'),
                loop_stage('Stale digest rejected', 'rejected before replay'),
                loop_stage('Runtime failure', runtime_failure['status'],
                           'injected compiler failure stays inconclusive, never a successful attack'),
            ],
        },
        'records': {
            'cards': [
                {'label': 'Kernel-checked targets', 'value': '5',
                 'detail': '4 supported model observations + 1 exact-target refutation · Lean 4.35.0-rc2, nanoda + con-ron'},
                {'label': 'Verifier gates', 'value': '7/7',
                 'detail': 'real proof accepted; sorry, target swap, custom axiom, body replacement and meaning change all rejected'},
                {'label': 'Live replay stages', 'value': '8/8',
                 'detail': 'asserted by scripts/verify_attacks.sh on a disposable local Anvil'},
                {'label': 'Contract families', 'value': '2',
                 'detail': 'LendingPool (repaired revision) and MilestoneEscrow; both accepted regression cases survive in the maintainer registry'},
            ],
            'latest': 'Latest accepted finding — MilestoneEscrow double release · Oct 5, 2026 · still replays on the unrepaired snapshot',
            'frontier': '2 families · 5 kernel-checked targets · 2 accepted regression cases',
        },
        'ledger': {
            'lending_frames': {'original': frames(lending_attack), 'repaired': frames(revised_attack)},
            'escrow_frames': {'attack': frames(escrow_double, 'ReleaseWithinDeposit'), 'safe': frames(escrow_safe, 'ReleaseWithinDeposit')},
            'rows': [
                {'author': 'internal-fixture-maintainer', 'authorship': 'repo maintainer · reviewed fixture',
                 'evidence': 'LendingPool CollateralBacking withdrawal violation', 'kind': 'contract_bug',
                 'result': 'demonstrated_spec_requirement_violation', 'kernels': 'anvil 1.7.1 replay',
                 'digest': 'a16ab5a5…', 'recorded': 'Oct 5, 2026'},
                {'author': 'internal-fixture-maintainer', 'authorship': 'repo maintainer · reviewed fixture',
                 'evidence': 'MilestoneEscrow ReleaseWithinDeposit double release', 'kind': 'contract_bug',
                 'result': 'demonstrated_spec_requirement_violation', 'kernels': 'anvil 1.7.1 replay',
                 'digest': escrow_snapshot['digest'][:8] + '…', 'recorded': 'Oct 5, 2026'},
                {'author': 'repo maintainer', 'authorship': 'hand-authored revision proof',
                 'evidence': 'Repaired LendingPool CollateralLock', 'kind': 'model observation',
                 'result': 'supported_model_observation', 'kernels': 'nanoda + con-ron',
                 'digest': read('runs/live-revised-snapshot.json')['digest'][:8] + '…', 'recorded': 'Oct 5, 2026'},
                {'author': 'repo maintainer', 'authorship': 'hand-authored revision proof',
                 'evidence': 'Repaired LendingPool BorrowCap (callback withdrawal)', 'kind': 'model observation',
                 'result': 'supported_model_observation', 'kernels': 'nanoda + con-ron',
                 'digest': read('runs/live-revised-snapshot.json')['digest'][:8] + '…', 'recorded': 'Oct 5, 2026'},
                {'author': 'repo maintainer', 'authorship': 'hand-authored refutation',
                 'evidence': 'OtherClaimAvailability (over arbitrary states)', 'kind': 'exact-target refutation',
                 'result': 'supported_model_counterexample', 'kernels': 'nanoda + con-ron',
                 'digest': read('runs/live-revised-snapshot.json')['digest'][:8] + '…', 'recorded': 'Oct 5, 2026'},
                {'author': 'repo maintainer', 'authorship': 'hand-authored refutation',
                 'evidence': 'MilestoneEscrow ReleasedWithinDeposit', 'kind': 'exact-target refutation',
                 'result': 'supported_model_counterexample', 'kernels': 'nanoda + con-ron',
                 'digest': escrow_snapshot['digest'][:8] + '…', 'recorded': 'Oct 5, 2026'},
            ],
            'note': 'Developer-authored demonstrations and maintainer decisions, not agent discoveries. '
                    'Every entry leaves accepted: false, creator_approval: pending, contract_correspondence: not_proved.',
        },
        'revision': {
            'title': 'Regenerated repaired-source revision (LendingPool)',
            'snapshot_digest': read('runs/live-revised-snapshot.json')['digest'],
            'model_change': 'withdrawAllowed now also requires debt ≤ (collateral - amount)/2, mirroring the source repair; property statements unchanged.',
            'full_verify': 'rejected — four real proofs plus an honest sorry on the open OtherClaimAvailability target',
            'kernel_checked': [
                {'id': 'CollateralLock', 'status': evidence_results['collaterallock']['status'],
                 'note': 'the repaired withdrawal protection'},
                {'id': 'BorrowCap', 'status': evidence_results['borrowcap']['status'],
                 'note': 'callback withdrawal stays capped'},
                {'id': 'DepositCredit', 'status': evidence_results['deposit']['status'],
                 'note': 'deposit credits exactly the deposited amount'},
                {'id': 'BorrowCheckBeforeCall', 'status': evidence_results['borrowcheck']['status'],
                 'note': 'borrow cap holds before the payout call'},
                {'id': 'OtherClaimAvailability', 'status': evidence_results['otherclaim']['status'],
                 'note': 'exact-target refutation: needs a reachability invariant, invalid over arbitrary states'},
            ],
            'regression': revised_regress['cases'][0]['status'],
            'regression_note': 'concrete replay no longer demonstrates the violation; mapping changed, so review is required',
            'final_attack': revised_attack['status'],
            'final_attack_values': revised_attack['all_requirement_checks']['CollateralBacking']['checks'][-1]['values'],
        },
        'escrow': {
            'title': 'Second contract family: MilestoneEscrow',
            'snapshot_digest': escrow_snapshot['digest'],
            'bug': 'the release guard checks only deposited[payer]; it never subtracts already-released amounts, so one deposit can be released twice',
            'safe': {'status': escrow_safe['status'],
                     'checks': {k: v['status'] for k, v in escrow_safe['all_requirement_checks'].items()}},
            'double_release': {'status': escrow_double['status'],
                              'values': violation_values(escrow_double['assessment'])},
            'review': {'creator': escrow_review['creator'],
                       'decisions': [{'id': d['requirement_id'], 'decision': d['decision'],
                                      'reason': d['reason']} for d in escrow_review['decisions']]},
            'regression': escrow_regres['cases'][0]['status'],
            'counterexample': escrow_counter['status'],
            'counterexample_note': 'from a healthy state (deposited 100, released 30), a 100 release leaves released 130 over the 100 deposit',
        },
        'review_flow': {
            'lending': {'creator': lending_review['creator'], 'decisions': lending_review['decisions']},
            'revised': {'creator': revised_review['creator'], 'decisions': revised_review['decisions']},
            'note': 'Recorded internal-fixture reviews by the repo maintainer; they are interpretations for transaction checking only, not production creator approval.',
        },
        'demos': {
            'escrow': {
                'label': 'MilestoneEscrow (recommended first)',
                'snapshot_digest': escrow_snapshot['digest'],
                'intent': escrow_snapshot['material']['input']['intent'],
                'policy': escrow_policy,
                'submission': read(f'{escrow_fixtures}/attack-double-release.json'),
            },
            'lending': {
                'label': 'LendingPool',
                'snapshot_digest': read('general/fixtures/attacks/snapshot.json')['digest'],
                'intent': read('general/fixtures/attacks/snapshot.json')['material']['input']['intent'],
                'policy': read('general/fixtures/attacks/policy.json'),
                'submission': read('general/fixtures/attacks/withdraw-collateral.json'),
            },
        },
        'commands': {
            'verify_loop': 'bash scripts/verify_attacks.sh',
            'attack': 'python3 -m general attack <snapshot> <policy> <submission> --output runs/my-attack',
            'accept': 'python3 -m general accept-attack <snapshot> <policy> <submission> --registry runs/my-registry --category contract_bug --reason "<maintainer reason>" --output runs/my-acceptance',
            'regress': 'python3 -m general regress-attacks <snapshot> --registry runs/my-registry --output runs/my-regressions',
            'propose': 'python3 -m general propose-policy <snapshot> <draft-policy> --output runs/my-proposal',
            'review_policy': 'python3 -m general review-policy <snapshot> runs/my-proposal/proposal.json <decisions> --output runs/my-review',
            'verifier_gates': 'python3 -m general.regressions --output runs/my-gates',
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n')
    print('wrote', OUT, OUT.stat().st_size, 'bytes')


if __name__ == '__main__':
    sys.exit(main())
