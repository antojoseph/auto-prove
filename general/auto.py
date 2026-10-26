"""CLI for the automatic challenge loop.

  open       maintainer: open a challenge from contract + intent (D-22)
  migrate    maintainer: convert a creator-reviewed v1 challenge
  process    host: judge, credit, repair and version every submitted contribution
  preflight  participant: mechanical replay only; no model calls, not authoritative
  status     quiet-period metric, pending repairs, cases and credits

``--roles openrouter`` uses host-funded OpenRouter models (needs
OPENROUTER_API_KEY). ``--roles FILE.json`` replays labelled recorded responses
without inference; use it for tests and reproducible demonstrations.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from .autoloop import process, Rejected
from .challenge import Challenge, contribution_check, bind_check, requirement_checks
from .chain import replay as chain_replay
from .core import digest, read, write
from .models import provider
from .opening import open_challenge, migrate_v1


def options_from(args):
    return {'lean': 'skip' if getattr(args, 'no_lean', False) else 'docker',
            'differential': 'skip' if getattr(args, 'no_differential', False) else 'docker',
            'repair_attempts': getattr(args, 'repair_attempts', 4)}


def preflight(challenge_dir, submission_dir, output, score_path=None):
    """What the mechanical evidence shows; the judge has not run. Not authoritative."""
    challenge = Challenge(challenge_dir); output = Path(output); output.mkdir(parents=True, exist_ok=False)
    files = challenge.version_files(challenge.current); rows = []
    for path in sorted((Path(submission_dir) / 'contributions').glob('*.json')):
        row = {'file': path.name}
        try:
            contribution = contribution_check(challenge, read(path)); bind_check(challenge, contribution)
            replayed = chain_replay(files['snapshot']['material']['input'], files['policy']['environment'],
                                    contribution['trace'], output / path.stem, files['policy']['probes'])
            row['replay'] = replayed['status']
            if replayed['status'] == 'replayed':
                checks = requirement_checks(files['policy'], replayed)
                row['requirement_checks'] = {k: v['status'] for k, v in checks.items()}
                row['transaction_statuses'] = [t['status'] for t in replayed['transactions']]
                row['frames'] = [f['values'] for f in replayed['frames']]
            else: row['reason'] = replayed.get('reason')
        except ValueError as error:
            row['rejected'] = str(error)
        rows.append(row)
    result = {'score': 0, 'authoritative': False, 'challenge_version': challenge.current,
              'meaning': 'preflight: mechanical replay only; the hosted judge decides findings, credit and repairs',
              'contributions': rows}
    write(output / 'preflight.json', result)
    if score_path: write(score_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    common = lambda p: (p.add_argument('--roles', required=True), p.add_argument('--no-lean', action='store_true'),
                        p.add_argument('--no-differential', action='store_true'),
                        p.add_argument('--repair-attempts', type=int, default=4))
    p = sub.add_parser('open'); p.add_argument('input'); p.add_argument('--challenge', required=True)
    p.add_argument('--output', required=True); p.add_argument('--candidate'); p.add_argument('--policy-parts'); common(p)
    p = sub.add_parser('migrate'); p.add_argument('v1'); p.add_argument('--seeds', required=True)
    p.add_argument('--model-map'); p.add_argument('--challenge', required=True); p.add_argument('--output', required=True); common(p)
    p = sub.add_parser('process'); p.add_argument('--challenge', required=True); p.add_argument('--submission', required=True)
    p.add_argument('--output', required=True); p.add_argument('--score-path'); p.add_argument('--submitted-at'); common(p)
    p = sub.add_parser('preflight'); p.add_argument('--challenge', required=True); p.add_argument('--submission', required=True)
    p.add_argument('--output', required=True); p.add_argument('--score-path')
    p = sub.add_parser('status'); p.add_argument('--challenge', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'status':
            print(json.dumps(Challenge(args.challenge).status(), indent=2)); return 0
        if args.command == 'preflight':
            result = preflight(args.challenge, args.submission, args.output, args.score_path)
            print(json.dumps(result['contributions'], indent=2)); return 0
        roles = provider(args.roles)
        if args.command == 'open':
            parts = read(args.policy_parts) if args.policy_parts else None
            challenge = open_challenge(read(args.input), args.challenge, args.output, roles, options_from(args),
                                       read(args.candidate) if args.candidate else None, parts)
            print('opened ' + challenge.meta['id'] + ' v' + str(challenge.current)); return 0
        if args.command == 'migrate':
            challenge = migrate_v1(args.v1, read(args.seeds), args.challenge, args.output, roles, options_from(args),
                                   read(args.model_map) if args.model_map else None)
            print('migrated ' + challenge.meta['id'] + ' v' + str(challenge.current)); return 0
        report = process(args.challenge, args.submission, args.output, roles, options_from(args), args.submitted_at)
        # Yukon promotes strictly higher scores, so the authoritative score is the challenge's cumulative
        # credit after this run: a submission that earns nothing ties; any credited finding raises it.
        total = round(sum(e['weight'] for e in Challenge(args.challenge).ledger()), 4)
        score = {'score': total, 'authoritative': True,
                 'metrics': {'submission_credit': report['score'], 'cumulative_credit': total,
                             'version_before': report['version_before'], 'version_after': report['version_after'],
                             'credits': report['credits'],
                             'outcomes': [{'file': r.get('file'), 'outcome': r['outcome']} for r in report['contributions']],
                             'formal': report['formal'], 'quiet_period': report['status']['quiet_period'],
                             'approval': 'approved_automatically', 'contract_correspondence': 'not_proved',
                             'meaning': 'credit-weighted score for this submission; not a security certificate'}}
        if args.score_path: write(args.score_path, score)
        print('score ' + str(total) + ' (this submission earned ' + str(report['score']) + '); challenge v' + str(report['version_before']) + ' -> v' + str(report['version_after']))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, Rejected) as error:
        parser.exit(1, 'rejected: ' + str(error) + '\n')


if __name__ == '__main__': sys.exit(main())
