"""Fail-closed Yukon contribution benchmark (spec.prove).

The frozen snapshot and reviewed policy come from maintainer-owned challenge/
files, never from the submission. Contributions are data: bounded JSON traces
replayed on a disposable local Anvil, plus an optional exact-target Lean
refutation kernel-checked in the isolated Docker verifier. A score.json is
written only when every check succeeds; any rejection exits nonzero with no
score file. The score is evidence credit for the internal pilot, not a
security certificate or a payout rule.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from .attacks import case_material, policy_check, submission_check, adjudicate
from .core import digest, read, validate_snapshot, write
from .pipeline import evidence

FORMAL_FIELDS = {'property_id', 'proof'}


def reject(reason):
    raise SystemExit('rejected: ' + reason)


def main():
    parser = argparse.ArgumentParser(description='Score transaction contributions against the frozen challenge version')
    parser.add_argument('--challenge', default='challenge')
    parser.add_argument('--submission', default='submission')
    parser.add_argument('--output', required=True)
    parser.add_argument('--score-path', default='.yukon/score.json')
    args = parser.parse_args()
    try:
        score(Path(args.challenge), Path(args.submission), Path(args.output), Path(args.score_path))
    except ValueError as error:
        reject(str(error))


def score(challenge, submission, output, score_path):
    output.mkdir(parents=True, exist_ok=False)
    snapshot = validate_snapshot(read(challenge/'snapshot.json'))
    policy = policy_check(snapshot, read(challenge/'policy.json'))
    policy_digest = digest(policy)
    record = read(challenge/'review-record.json')
    if record.get('reviewed_policy_digest') != policy_digest:
        reject('challenge policy has no matching creator review record')
    if not record.get('usable_for_transaction_checking', False):
        reject('challenge policy is not approved for transaction checking')

    folder = submission/'contributions'
    paths = sorted(folder.glob('*.json')) if folder.is_dir() else []
    if not 1 <= len(paths) <= 20:
        reject('need 1-20 contribution files under ' + str(folder))

    pairs = set(); rows = []
    for index, path in enumerate(paths):
        contribution = read(path)
        submission_check(snapshot, policy, contribution)
        requirement = next(r for r in policy['requirements'] if r['id'] == contribution['requirement_id'])
        if requirement['review_status'] != 'approved':
            reject(path.name + ' attacks a requirement pending creator review')
        report = adjudicate(snapshot, policy, contribution, output/('contribution-'+str(index+1)))
        if report['replay']['status'] != 'replayed':
            reject(path.name + ' replay was inconclusive: ' + str(report['replay'].get('reason', 'no reason recorded')))
        if report['assessment']['status'] != 'demonstrated_violation':
            reject(path.name + ' does not demonstrate the named requirement violation')
        case_id = digest(case_material(snapshot, policy, contribution))
        for row in policy['requirements']:
            if row['review_status'] != 'approved': continue
            if report['all_requirement_checks'][row['id']]['status'] == 'demonstrated_violation':
                pairs.add(row['id'] + ':' + case_id)
        rows.append({'file': path.name, 'status': report['status'], 'case_id': case_id,
                     'requirement_checks': {key: value['status']
                                            for key, value in report['all_requirement_checks'].items()}})

    refuted = []; formal_path = submission/'formal.json'
    if formal_path.exists():
        finding = read(formal_path)
        if not isinstance(finding, dict) or set(finding) != FORMAL_FIELDS:
            reject('formal.json needs exactly property_id and proof')
        check = evidence(snapshot, {'evidence_kind': 'model_counterexample',
                                    'property_id': finding['property_id'], 'proof': finding['proof'],
                                    'reasoning': 'Submitted formal evidence: exact frozen-target refutation claimed.'},
                         output/'formal-evidence')
        if check['status'] != 'supported_model_counterexample':
            reject('formal evidence was not kernel-checked: ' + str(check.get('reason', check['status'])))
        refuted.append({'property_id': finding['property_id'], 'status': check['status'],
                        'kernels': check.get('independent_kernels', [])})

    score = len(pairs) + 5 * len(refuted)
    result = {'score': score, 'metrics': {
        'challenge': {'snapshot_digest': snapshot['digest'], 'policy_digest': policy_digest,
                      'review_record': 'challenge/review-record.json'},
        'contributions': rows, 'distinct_requirement_case_pairs': sorted(pairs),
        'kernel_checked_refutations': refuted,
        'grading': 'score = distinct demonstrated requirement/case pairs + 5 per kernel-checked exact-target refutation; fail-closed',
        'accepted': False, 'creator_approval': 'pending', 'contract_correspondence': 'not_proved',
        'meaning': 'evidence credit for the internal pilot; not a security certificate or a payout rule'}}
    write(score_path, result)
    write(output/'score.json', result)
    print('score ' + str(score))
    return result


if __name__ == '__main__':
    main()
