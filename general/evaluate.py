"""Evaluation on a held-out corpus (backlog I-19).

``policy``   model-free. For every source variant, replay the corpus seeds and
             attacks against the trusted policy: unsafe variants must be
             detected by some attack; safe variants must pass every seed and
             attack (no false alarm).
``mutants``  model-free mutation census of each safe variant: delete a require,
             flip a comparison, swap += / -=, delete an assignment, or move an
             external call above the state updates. A compiling mutant is
             KILLED when an attack violates a requirement or a seed fails.
             Survivors are either equivalent mutants or gaps in the policy.
``loop``     runs the automatic loop on each unsafe variant (opened with the
             corpus policy), submits the corpus attacks, then replays the
             HELD-OUT seeds and attacks on the final version: held-out attacks
             must fail (the fix generalises) and held-out seeds must succeed
             (no over-restriction). With ``--roles openrouter`` this measures
             live judge/repair behaviour and token use; with recorded responses
             it only exercises the mechanism.

Corpus ground truth is developer-authored. Scores are measurements on this
corpus, not security guarantees.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
import sys
from pathlib import Path
from .attacks import assess
from .challenge import (POLICY_VERSION, Challenge, blocked_is_safe, case_material, requirement_checks, run_case)
from .chain import compile_source, replay as chain_replay
from .core import digest, read, write
from .opening import open_challenge

CANDIDATE_GAPS = ['Corpus evaluation uses a minimal placeholder Lean model; formal targets are not evaluated here.']


def placeholder_candidate(case):
    return {'status': 'supported', 'summary': 'Corpus evaluation placeholder specification', 'threat_model': [],
            'model_body': 'def corpusPlaceholder (n : Nat) : Nat := n',
            'properties': [{'id': 'Placeholder', 'requirement': 'Corpus placeholder', 'intent_basis': 'Evaluation harness only',
                            'statement': '∀ n : Nat, corpusPlaceholder n = n', 'explanation': 'Not a security property',
                            'proof': 'by intro n; rfl'}],
            'assumptions': [], 'unresolved_questions': [], 'execution_gaps': CANDIDATE_GAPS}


def snapshot_for(case, source):
    from .core import freeze
    data = dict(copy.deepcopy(case['input']), contract_source=source)
    return freeze(data, placeholder_candidate(case))


def policy_for(case, snapshot):
    return {'version': POLICY_VERSION, 'snapshot_digest': snapshot['digest'], 'environment': case['environment'],
            'probes': case['probes'], 'requirements': case['requirements'], 'model_map': None}


def judge_variant(case, source, output, heldout=False, replay_fn=chain_replay):
    """Replay attacks and seeds on one source. Returns detection evidence."""
    snapshot = snapshot_for(case, source); policy = policy_for(case, snapshot)
    attacks = case['attacks'] + (case['heldout_attacks'] if heldout else [])
    seeds = case['seeds'] + (case['heldout_seeds'] if heldout else [])
    rows = {'attacks': [], 'seeds': []}
    for i, attack in enumerate(attacks):
        replayed = replay_fn(snapshot['material']['input'], policy['environment'], attack['trace'], Path(output) / ('attack-' + str(i)), policy['probes'])
        if replayed['status'] != 'replayed':
            rows['attacks'].append({'name': attack['name'], 'status': 'inconclusive', 'reason': replayed.get('reason')}); continue
        checks = requirement_checks(policy, replayed)
        violated = sorted(k for k, v in checks.items() if v['status'] == 'demonstrated_violation')
        rows['attacks'].append({'name': attack['name'], 'status': 'violation' if violated else 'no_violation', 'violated': violated})
    for i, seed in enumerate(seeds):
        row = run_case(case_material('must_succeed', seed['trace'], expected=seed['expected_success_actions']), snapshot, policy,
                       Path(output) / ('seed-' + str(i)), replay_fn)
        rows['seeds'].append({'description': seed['description'], 'status': row['status'], 'reason': row.get('reason')})
    rows['detected'] = any(a['status'] == 'violation' for a in rows['attacks'])
    rows['seed_failures'] = sum(s['status'] != 'passed' for s in rows['seeds'])
    rows['inconclusive'] = sum(a['status'] == 'inconclusive' for a in rows['attacks'])
    return rows


def evaluate_policy(case, output):
    report = {'case': case['input']['id'], 'variants': []}
    for variant in case['variants']:
        rows = judge_variant(case, variant['source'], Path(output) / variant['name'], heldout=True)
        if variant['safe']: correct = not rows['detected'] and not rows['seed_failures'] and not rows['inconclusive']
        else: correct = rows['detected'] and not rows['inconclusive']
        report['variants'].append({'name': variant['name'], 'safe': variant['safe'], 'correct': correct, **rows})
    report['correct'] = sum(v['correct'] for v in report['variants']); report['total'] = len(report['variants'])
    return report


# ---------------------------------------------------------------------------
# Mutation census

RELATIONS = [('<=', '<'), ('>=', '>'), (' < ', ' <= '), (' > ', ' >= '), ('==', '!='), ('!=', '==')]
ASSIGNMENT = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_\[\].]*\s*(\+=|-=|=)\s*[^=].*;\s*$')


def mutants(source):
    lines = source.splitlines(True); out = []
    body = False
    for i, line in enumerate(lines):
        if 'function ' in line: body = True
        if not body: continue
        stripped = line.strip()
        if stripped.startswith('require(') or ' require(' in line:
            out.append(('delete-require', i, ''.join(lines[:i] + lines[i + 1:])))
            for old, new in RELATIONS:
                if old in line:
                    out.append(('flip ' + old.strip() + '→' + new.strip(), i, ''.join(lines[:i] + [line.replace(old, new, 1)] + lines[i + 1:])))
        if ASSIGNMENT.match(line) and 'uint256 ' not in line and 'bool ' not in line and '.call' not in line:
            out.append(('delete-assignment', i, ''.join(lines[:i] + lines[i + 1:])))
            for old, new in (('+=', '-='), ('-=', '+=')):
                if old in line: out.append(('swap ' + old + '→' + new, i, ''.join(lines[:i] + [line.replace(old, new, 1)] + lines[i + 1:])))
        if '.call{' in line and i + 1 < len(lines):
            # Move the external call (and an immediately following require(ok)) above preceding state updates.
            j = i
            while j > 0 and ASSIGNMENT.match(lines[j - 1]) and 'uint256 ' not in lines[j - 1]: j -= 1
            if j < i:
                block = [line] + ([lines[i + 1]] if 'require(ok)' in lines[i + 1] else [])
                rest = lines[:j] + block + lines[j:i] + lines[i + len(block):]
                out.append(('call-before-effects', i, ''.join(rest)))
    unique = {};
    for kind, line, text in out:
        if text != source: unique.setdefault(digest(text), (kind, line, text))
    return list(unique.values())


def census(case, output):
    safe = next(v for v in case['variants'] if v['safe'])
    rows = []
    for k, (kind, line, text) in enumerate(mutants(safe['source'])):
        try: compile_source(text)
        except ValueError: rows.append({'operator': kind, 'line': line + 1, 'status': 'does_not_compile'}); continue
        result = judge_variant(case, text, Path(output) / ('mutant-' + str(k)), heldout=True)
        killed = result['detected'] or result['seed_failures'] > 0
        rows.append({'operator': kind, 'line': line + 1, 'mutated_line': safe['source'].splitlines()[line].strip(),
                     'status': 'killed' if killed else 'survived',
                     'killed_by': ([a['name'] for a in result['attacks'] if a['status'] == 'violation'] +
                                   [s['description'] for s in result['seeds'] if s['status'] != 'passed'])})
    compiled = [r for r in rows if r['status'] != 'does_not_compile']
    killed = [r for r in compiled if r['status'] == 'killed']
    return {'case': case['input']['id'], 'mutants': rows, 'compiled': len(compiled), 'killed': len(killed),
            'kill_rate': round(len(killed) / len(compiled), 3) if compiled else None,
            'survivors': [r for r in compiled if r['status'] == 'survived'],
            'meaning': 'survivors are equivalent mutants or behaviours the policy/attacks/seeds do not observe'}


# ---------------------------------------------------------------------------
# Loop evaluation

def to_contribution(challenge, attack, contributor='corpus-evaluator', model='corpus/ground-truth'):
    files = challenge.version_files(challenge.current)
    return {'version': 'transaction-contribution-v2', 'challenge_version': challenge.current,
            'snapshot_digest': files['snapshot']['digest'], 'policy_digest': digest(files['policy']),
            'contributor': contributor, 'contributor_model': model, 'kind': 'attack', 'requirement_ref': None,
            'claim': 'Corpus attack ' + attack['name'], 'expected_success_actions': [], 'reproduces': '', 'trace': attack['trace']}


def evaluate_loop(case, output, roles, options):
    from .autoloop import process
    output = Path(output); report = {'case': case['input']['id'], 'variants': []}
    for variant in case['variants']:
        if variant['safe']: continue
        folder = output / variant['name']
        data = dict(copy.deepcopy(case['input']), contract_source=variant['source'])
        parts = {'environment': case['environment'], 'probes': case['probes'], 'requirements': case['requirements'],
                 'seeds': case['seeds'], 'model_map': None}
        try:
            challenge = open_challenge(data, folder / 'challenge', folder / 'open', roles, options,
                                       candidate=placeholder_candidate(case), policy_parts=parts)
        except ValueError as error:
            report['variants'].append({'name': variant['name'], 'status': 'open_failed', 'reason': str(error)}); continue
        outcomes = []
        for i, attack in enumerate(case['attacks']):
            submission = folder / ('submission-' + str(i)) / 'contributions'; submission.mkdir(parents=True)
            write(submission / 'attack.json', to_contribution(Challenge(folder / 'challenge'), attack))
            result = process(folder / 'challenge', submission.parent, folder / ('run-' + str(i)), roles, options)
            outcomes += [r['outcome'] for r in result['contributions']]
        challenge = Challenge(folder / 'challenge'); final = challenge.version_files(challenge.current)
        source = final['snapshot']['material']['input']['contract_source']
        heldout = judge_variant(dict(case, attacks=[], seeds=[]), source, folder / 'heldout', heldout=True)
        report['variants'].append({
            'name': variant['name'], 'final_version': challenge.current, 'outcomes': outcomes,
            'repaired': challenge.current > 1,
            'heldout_attacks_blocked': sum(a['status'] == 'no_violation' for a in heldout['attacks']),
            'heldout_attacks': len(heldout['attacks']),
            'heldout_seeds_passed': sum(s['status'] == 'passed' for s in heldout['seeds']), 'heldout_seeds': len(heldout['seeds']),
            'over_restrictive': heldout['seed_failures'] > 0, 'usage': usage(folder)})
    return report


def usage(folder):
    total = {'prompt_tokens': 0, 'completion_tokens': 0, 'calls': 0}
    for path in Path(folder).rglob('provenance.json'):
        value = read(path).get('usage') or {}
        total['calls'] += 1
        for key in ('prompt_tokens', 'completion_tokens'): total[key] += int(value.get(key, 0) or 0)
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['policy', 'mutants', 'loop'])
    parser.add_argument('--corpus', default=str(Path(__file__).resolve().parent / 'corpus'))
    parser.add_argument('--case', action='append', help='Case id (default: all)')
    parser.add_argument('--output', required=True)
    parser.add_argument('--roles', help='Required for loop mode: "openrouter" or a recorded-responses file')
    parser.add_argument('--no-lean', action='store_true')
    args = parser.parse_args()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    cases = [read(p) for p in sorted(Path(args.corpus).glob('*.json')) if not args.case or p.stem in args.case]
    results = []
    for case in cases:
        folder = output / case['input']['id']
        if args.mode == 'policy': results.append(evaluate_policy(case, folder))
        elif args.mode == 'mutants': results.append(census(case, folder))
        else:
            from .models import provider
            if not args.roles: parser.error('loop mode needs --roles')
            results.append(evaluate_loop(case, folder, provider(args.roles), {'lean': 'skip' if args.no_lean else 'docker',
                                                                             'differential': 'skip'}))
    summary = {'mode': args.mode, 'results': results}
    if args.mode == 'policy':
        summary['correct'] = sum(r['correct'] for r in results); summary['total'] = sum(r['total'] for r in results)
    if args.mode == 'mutants':
        compiled = sum(r['compiled'] for r in results); killed = sum(r['killed'] for r in results)
        summary.update(compiled=compiled, killed=killed, kill_rate=round(killed / compiled, 3) if compiled else None)
    write(output / 'evaluation.json', summary)
    printable = {k: v for k, v in summary.items() if k != 'results'}
    if args.mode == 'mutants':
        printable['survivors'] = [{'case': r['case'], **{k: s[k] for k in ('operator', 'line', 'mutated_line')}}
                                  for r in results for s in r['survivors']]
    if args.mode == 'policy':
        printable['variants'] = [{'case': r['case'], 'name': v['name'], 'safe': v['safe'], 'correct': v['correct']}
                                 for r in results for v in r['variants']]
    if args.mode == 'loop': printable['results'] = results
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__': sys.exit(main())
