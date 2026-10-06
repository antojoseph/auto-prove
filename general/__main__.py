import argparse
import sys
from pathlib import Path
from .core import read, freeze, write, validate_snapshot
from .backend import verify
from .pipeline import run, evidence
from .evm import replay
from .attacks import adjudicate, accept, regress
from .review import propose, creator_review


def main():
    parser = argparse.ArgumentParser(description='General contract + English specification pipeline')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run'); p.add_argument('input'); p.add_argument('--output', required=True)
    p.add_argument('--rounds', type=int, default=2); p.add_argument('--model'); p.add_argument('--timeout', type=int, default=300)
    p.add_argument('--candidate'); p.add_argument('--skip-checks', action='store_true')
    p.add_argument('--evm', action='store_true', help='Replay proposed transactions on a disposable local Anvil chain')
    p.add_argument('--attack-registry', help='Replay maintainer-accepted transaction regressions in every round (requires --evm)')
    p = sub.add_parser('freeze'); p.add_argument('input'); p.add_argument('candidate'); p.add_argument('--output', required=True)
    p = sub.add_parser('verify'); p.add_argument('snapshot'); p.add_argument('solution'); p.add_argument('--output', required=True)
    p = sub.add_parser('evidence'); p.add_argument('snapshot'); p.add_argument('finding'); p.add_argument('--output', required=True)
    p = sub.add_parser('replay'); p.add_argument('input'); p.add_argument('trace'); p.add_argument('--output', required=True)
    for name in ('attack', 'accept-attack'):
        p = sub.add_parser(name); p.add_argument('snapshot'); p.add_argument('policy'); p.add_argument('submission')
        p.add_argument('--output', required=True)
        if name == 'accept-attack':
            p.add_argument('--registry', required=True)
            p.add_argument('--category', required=True, choices=['contract_bug','spec_gap','model_gap'])
            p.add_argument('--reason', required=True)
    p = sub.add_parser('regress-attacks'); p.add_argument('snapshot'); p.add_argument('--registry', required=True)
    p.add_argument('--output', required=True)
    p = sub.add_parser('propose-policy'); p.add_argument('snapshot'); p.add_argument('policy')
    p.add_argument('--output', required=True)
    p = sub.add_parser('review-policy'); p.add_argument('snapshot'); p.add_argument('proposal')
    p.add_argument('decisions'); p.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'run':
            run(read(args.input), args.output, args.rounds, args.model, args.timeout,
                read(args.candidate) if args.candidate else None, args.skip_checks, evm=args.evm,
                attack_registry=args.attack_registry)
        elif args.command == 'freeze': write(args.output, freeze(read(args.input), read(args.candidate)))
        elif args.command == 'verify':
            result = verify(read(args.snapshot), Path(args.solution).read_text(), args.output)
            print(result['status']); return 0 if result['status'] == 'proved' else 1
        elif args.command == 'replay':
            result = replay(read(args.input), read(args.trace), args.output)
            print(result['status']); return 0 if result['status'] == 'replayed' else 1
        elif args.command in ('attack', 'accept-attack'):
            inputs = (read(args.snapshot), read(args.policy), read(args.submission))
            if args.command == 'attack': result = adjudicate(*inputs, args.output)
            else: result = accept(*inputs, args.registry, args.output, args.category, args.reason)
            print(result['status'] + '; attack acceptance: ' + result['attack_acceptance'])
            return 0 if result['assessment']['status'] == 'demonstrated_violation' else 1
        elif args.command == 'regress-attacks':
            result = regress(read(args.snapshot), args.registry, args.output)
            print(result['status']); return 0 if result['status'] == 'passed_replay' else 1
        elif args.command == 'propose-policy':
            propose(read(args.snapshot), read(args.policy), args.output)
            print('operational policy proposed; creator review pending')
        elif args.command == 'review-policy':
            snapshot = read(args.snapshot); packet = read(args.proposal)
            if packet.get('version') != 'policy-proposal-v1': raise ValueError('Not a policy proposal packet')
            record = creator_review(snapshot, packet, read(args.decisions), args.output)
            print('creator review recorded: ' + str(len(record['approved_policy']['requirements'])) + ' approved, '
                  + str(len(record['rejected_requirements'])) + ' rejected; contract approval remains pending')
        else:
            snapshot = validate_snapshot(read(args.snapshot))
            result = evidence(snapshot, read(args.finding), args.output)
            write(Path(args.output)/'evidence.json', result); print(result['status'])
            return 0 if result['status'].startswith('supported_model') else 1
    except (ValueError, KeyError, RuntimeError, OSError) as error:
        if args.command == 'run' and Path(args.output).exists():
            write(Path(args.output)/'failure.json', {'status':'inconclusive','reason':str(error),
                  'accepted':False,'creator_approval':'pending','contract_correspondence':'not_proved'})
        parser.exit(1, 'Error: ' + str(error) + '\n')
    return 0


if __name__ == '__main__': sys.exit(main())
