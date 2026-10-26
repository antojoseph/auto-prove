#!/usr/bin/env python3
"""Model-free end-to-end verification of the automatic negative-case loop.

Runs real local EVM replay (Anvil 1.7.1, solc 0.8.28), real Lean compilation and
model/EVM differential checks in the pinned verifier image, and kernel checks
for formal refutations. Judge, repair and review decisions come from labelled,
developer-authored recorded responses: this verifies the mechanism, never live
model reliability. No model account, external chain or wallet is used.

    python3 scripts/verify_autoloop.py [--fast]   # --fast: skip Docker Lean/differential

Evidence goes to a fresh runs/reproduced-autoloop-* directory.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from general.autoloop import process  # noqa: E402
from general.challenge import Challenge  # noqa: E402
from general.core import read  # noqa: E402
from general.models import provider  # noqa: E402
from general.opening import migrate_v1, open_challenge  # noqa: E402

FAILURES = []


def expect(condition, message):
    print(('  ok   ' if condition else '  FAIL ') + message, flush=True)
    if not condition: FAILURES.append(message)


def stamp(challenge, templates, out):
    subprocess.run([sys.executable, str(ROOT / 'general/fixtures/auto/escrow/build.py'), 'stamp', str(challenge), str(templates), str(out)], check=True)


def outcomes(report):
    return [(row.get('file'), row['outcome']) for row in report['contributions']]


def escrow(base, options):
    print('1/4 MilestoneEscrow: migrate the live v1 challenge, then four submissions', flush=True)
    F = ROOT / 'general/fixtures/auto/escrow'; ch = base / 'challenge'
    migrate_v1(ROOT / 'challenge/legacy-v1', read(F / 'seeds.json'), ch, base / 'migrate', provider(F / 'responses-open.json'),
               options, read(F / 'model-map.json'))
    record = Challenge(ch).record(1)
    expect(record['approval'] == 'approved_automatically' and record['contract_correspondence'] == 'not_proved', 'v1 labels')
    if options['lean'] == 'docker':
        expect(record['open_checks']['lean']['status'] == 'compiled', 'v1 Lean model and targets compile')
        expect(record['open_checks']['differential']['status'] == 'agrees_on_recorded_traces', 'v1 model agrees with EVM on seeds')

    stamp(ch, F / 'templates/s0', base / 's0')
    r0 = process(ch, base / 's0', base / 'run-s0', provider({}), options)
    if options['lean'] == 'docker':
        expect(r0['formal']['status'] == 'supported_model_counterexample' and r0['score'] == 5.0,
               's0 kernel-checked refutation of v1 ReleasedWithinDeposit earns +5')

    stamp(ch, F / 'templates/s1', base / 's1')
    r1 = process(ch, base / 's1', base / 'run-s1', provider(F / 'responses-s1.json'), options)
    expect(outcomes(r1) == [('a-double-release.json', 'accepted_repaired')] and r1['version_after'] == 2, 's1 double release repaired into v2')
    payload = read(base / 'run-s1/contribution-1/judge-1/payload.json')
    expect('IMPORTANT SYSTEM NOTE' in payload['untrusted_contributor_claim'], 's1 contributor claim reached the judge only as quarantined data')
    repair_payload = json.dumps(read(base / 'run-s1/contribution-1/repair/repair-attempt-1/repair-author/payload.json'))
    expect('IMPORTANT SYSTEM NOTE' not in repair_payload, 's1 repair author never saw contributor prose')
    v2 = Challenge(ch).snapshot(2)['material']['input']['contract_source']
    expect('released[payer] + amount <= deposited[payer]' in v2, 'v2 contract enforces the cumulative limit')

    stamp(ch, F / 'templates/s2', base / 's2')
    r2 = process(ch, base / 's2', base / 'run-s2', provider(F / 'responses-s2.json'), options)
    expect(outcomes(r2) == [('a-duplicate.json', 'judged_unsupported'), ('b-outsider-release.json', 'accepted_repaired'),
                            ('c-legit-flagged.json', 'accepted_repaired')], 's2 outcomes: duplicate fixed, intent gap, flagged legitimate use')
    b = r2['contributions'][1]['repair']['attempts']; c = r2['contributions'][2]['repair']['attempts']
    expect(b[0]['status'] == 'rejected' and any('Legitimate actions reverted' in f for f in b[0]['gate']['failures']),
           's2 over-restrictive repair rejected by must-succeed regressions')
    if options['differential'] == 'docker':
        expect(any('divergences increased' in f for f in b[0]['gate']['failures']), 's2 over-restrictive repair also raised model/EVM divergence')
    expect(c[0]['status'] == 'rejected' and c[0]['reviews']['repair_review']['approved'] is False
           and c[0]['reviews']['repair_review_judge']['approved'] is True, 's2 weakening repair passed the floors but the independent reviewer rejected it')
    expect(r2['contributions'][2]['bind']['rebased_from'] == 2, 's2 submission queued while v3 shipped was rebased, not rejected')
    policy = Challenge(ch).policy(4)
    expect(any(r['id'] == 'OutsiderGainsNothing' and r['origin']['source'] == 'judge' for r in policy['requirements']),
           'v3 judge-drafted requirement survives in v4')
    expect(any(r['id'] == 'OtherPayerBacking' for r in policy['requirements']), 'v4 relaxed, not removed, OtherPayerBacking')

    stamp(ch, F / 'templates/s3', base / 's3')
    r3 = process(ch, base / 's3', base / 'run-s3', provider(F / 'responses-s3.json'), options)
    expect(outcomes(r3) == [('d-weakening-claim.json', 'judged_unsupported'), ('e-reproduction.json', 'reproduction_credited')],
           's3 false weakening claim rejected; independent reproduction credited')
    expect(r3['contributions'][0]['evidence']['weakening'] == 'original_requirement_violated', 's3 weakening detected mechanically before judgment')
    final = Challenge(ch); classes = sorted(e['class'] for e in final.ledger())
    expected = ['legit_action_blocked', 'new_root_cause', 'new_root_cause', 'reproduction'] + (['lean_refutation'] if options['lean'] == 'docker' else [])
    expect(classes == sorted(expected), 'ledger classes ' + ', '.join(classes))
    expect(final.status()['cases'] == {'must_fail': 3, 'must_succeed': 3}, 'regression registry: 3 must-fail, 3 must-succeed')
    for v in (2, 3, 4):
        expect((final.folder(v) / 'diff.md').exists() and (final.folder(v) / 'diff-from-v1.md').exists(), 'v%d diffs published' % v)
    return final


def vault(base, options):
    print('2/4 ReentrantVault: open from creator input, attack with a reentrant attacker contract', flush=True)
    F = ROOT / 'general/fixtures/auto/vault'; ch = base / 'challenge'
    open_challenge(read(F / 'input.json'), ch, base / 'open', provider(F / 'responses-open.json'), options)
    stamp(ch, F / 'templates/s1', base / 's1')
    report = process(ch, base / 's1', base / 'run-s1', provider(F / 'responses-attack.json'), options)
    row = report['contributions'][0]
    expect(row['outcome'] == 'accepted_repaired' and report['version_after'] == 2, 'reentrancy accepted and repaired into v2')
    expect(row['evidence']['requirement_checks']['VictimBacked'] == 'demonstrated_violation', 'attacker contract drained the victim on v1')
    gate = read(base / 'run-s1/contribution-1/repair/repair-attempt-1/gate/gate.json')
    expect(gate['checks']['trigger']['checks']['VictimBacked'] == 'not_demonstrated', 'same attacker contract fails on v2')
    if options['differential'] == 'docker':
        details = gate['checks']['differential']['candidate']['details']
        expect(details[0]['status'] == 'unmodeled', 'differential marks the attacker trace unmodeled instead of claiming agreement')


def corpus(base):
    print('3/4 held-out corpus: policy evaluation and mutation census', flush=True)
    for mode in ('policy', 'mutants'):
        subprocess.run([sys.executable, '-m', 'general.evaluate', mode, '--output', str(base / mode)], check=True,
                       cwd=ROOT, stdout=subprocess.DEVNULL)
    policy = read(base / 'policy/evaluation.json'); mutants = read(base / 'mutants/evaluation.json')
    expect(policy['correct'] == policy['total'], 'policy evaluation %d/%d variants classified correctly' % (policy['correct'], policy['total']))
    expect(mutants['compiled'] > 0, 'mutation census killed %d/%d compiling mutants (survivors listed in evaluation.json)'
           % (mutants['killed'], mutants['compiled']))


def loop_eval(base, options):
    print('4/4 loop evaluation on the reentrant corpus vault (recorded roles)', flush=True)
    args = [sys.executable, '-m', 'general.evaluate', 'loop', '--case', 'CorpusVault', '--roles',
            str(ROOT / 'general/corpus/responses/vault-loop.json'), '--output', str(base)]
    if options['lean'] != 'docker': args.append('--no-lean')
    subprocess.run(args, check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    variant = read(base / 'evaluation.json')['results'][0]['variants'][0]
    expect(variant['repaired'] and variant['heldout_attacks_blocked'] == variant['heldout_attacks'], 'held-out attacks blocked after repair')
    expect(not variant['over_restrictive'], 'held-out legitimate traces still succeed after repair')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fast', action='store_true', help='Skip Docker Lean compilation and differential checks')
    args = parser.parse_args()
    options = {'lean': 'skip' if args.fast else 'docker', 'differential': 'skip' if args.fast else 'docker'}
    base = ROOT / 'runs' / ('reproduced-autoloop-' + time.strftime('%Y%m%d-%H%M%S'))
    base.mkdir(parents=True)
    escrow(base / 'escrow', options); vault(base / 'vault', options); corpus(base / 'corpus'); loop_eval(base / 'corpus-loop', options)
    print('\nEvidence: ' + str(base))
    if FAILURES:
        print('%d check(s) failed' % len(FAILURES)); return 1
    print('All automatic-loop checks passed. Approval labels are automatic; contract correspondence is not proved.')
    return 0


if __name__ == '__main__': sys.exit(main())
