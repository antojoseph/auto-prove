"""Open an automatic challenge from creator input (decision D-22), or migrate a v1 one.

Opening is the only maintainer step. It generates (or accepts) the Lean
specification and the operational policy, replays the must-succeed seed traces,
compiles the Lean model, runs the model/EVM differential on the seeds, obtains
an independent different-family review and freezes version 1. Everything after
that is automatic.
"""
from __future__ import annotations
import copy
from pathlib import Path
from .challenge import (POLICY_VERSION, DEFAULT_THREAT_MODEL, case_material, create, policy_check, run_case)
from .chain import replay as chain_replay, validate_trace
from .core import digest, freeze, read, validate_input, validate_snapshot, write
from . import differential, gate
from .autoloop import parse_json

MAX_POLICY_ATTEMPTS = 3


def seeds_check(seeds, policy):
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 12: raise ValueError('Need 1-12 must-succeed seed traces')
    for seed in seeds:
        if not isinstance(seed, dict) or set(seed) != {'description', 'trace', 'expected_success_actions'}:
            raise ValueError('Invalid must-succeed seed fields')
        validate_trace(seed['trace'], policy['environment'])
        if seed['trace']['attacker_source'].strip(): raise ValueError('Seeds are legitimate usage without attacker contracts')
        actions = seed['expected_success_actions']
        if not isinstance(actions, list) or not actions or any(type(i) is not int or not 0 <= i < len(seed['trace']['actions']) for i in actions):
            raise ValueError('Seed expected_success_actions must index its actions')
    return seeds


def evaluate_open(snapshot, policy, seeds, output, options):
    replay_fn = options.get('replay', chain_replay)
    result = {'failures': [], 'seeds': []}
    try:
        policy_check(snapshot, policy); seeds_check(seeds, policy)
    except ValueError as error:
        result['failures'].append(str(error)); return result
    traces = []
    for i, seed in enumerate(seeds):
        material = case_material('must_succeed', seed['trace'], expected=seed['expected_success_actions'])
        row = run_case(material, snapshot, policy, Path(output) / ('seed-' + str(i + 1)), replay_fn)
        result['seeds'].append({'description': seed['description'], **row})
        if row['status'] != 'passed': result['failures'].append('Seed ' + str(i + 1) + ' failed: ' + str(row.get('reason')))
        replayed = read(Path(output) / ('seed-' + str(i + 1)) / 'replay.json') if (Path(output) / ('seed-' + str(i + 1)) / 'replay.json').exists() else {'status': 'not_run'}
        traces.append(('seed-' + str(i + 1), seed['trace'], replayed))
    if options.get('lean', 'docker') == 'docker':
        result['lean'] = gate.lean_compile(snapshot, Path(output) / 'lean')
        if result['lean']['status'] != 'compiled': result['failures'].append(result['lean']['reason'])
    else:
        result['lean'] = {'status': 'not_run', 'reason': 'Lean compile disabled by configuration'}
    if options.get('differential', 'docker') == 'docker' and policy.get('model_map') is not None:
        result['differential'] = gate.summary(differential.compare(snapshot, policy, traces, Path(output) / 'differential'))
    else:
        result['differential'] = {'status': 'not_run'}
    return result


def open_challenge(input_data, challenge_dir, output, roles, options=None, candidate=None, policy_parts=None,
                   threat_model=None):
    options = options or {}
    data = validate_input(input_data); output = Path(output); output.mkdir(parents=True, exist_ok=False)
    if candidate is None:
        candidate = roles('proposer', {'input': data}, output / 'proposer')
    snapshot = freeze(data, candidate); write(output / 'snapshot.json', snapshot)
    threat_model = threat_model or DEFAULT_THREAT_MODEL
    feedback = None; attempts = []
    for number in range(1, MAX_POLICY_ATTEMPTS + 1):
        folder = output / ('policy-attempt-' + str(number)); folder.mkdir()
        try:
            if policy_parts is not None:
                parts = copy.deepcopy(policy_parts)
            else:
                response = roles('policy_author', {'input': data, 'threat_model': threat_model, 'snapshot': snapshot,
                                                   'retry_feedback': feedback}, folder / 'policy-author')
                parts = {'environment': parse_json(response['environment_json'], 'environment_json', dict),
                         'probes': parse_json(response['probes_json'], 'probes_json', list),
                         'requirements': parse_json(response['requirements_json'], 'requirements_json', list),
                         'seeds': parse_json(response['must_succeed_json'], 'must_succeed_json', list),
                         'model_map': None if response['model_map_json'].strip() == 'null'
                         else parse_json(response['model_map_json'], 'model_map_json', dict)}
            policy = {'version': POLICY_VERSION, 'snapshot_digest': snapshot['digest'], 'environment': parts['environment'],
                      'probes': parts['probes'], 'requirements': parts['requirements'], 'model_map': parts['model_map']}
            evaluation = evaluate_open(snapshot, policy, parts['seeds'], folder / 'checks', options)
        except (ValueError, KeyError, RuntimeError) as error:
            evaluation = {'failures': [str(error)]}; policy = None; parts = None
        attempt = {'number': number, 'failures': evaluation['failures']}
        if not evaluation['failures']:
            candidate_digest = digest({'snapshot': snapshot['digest'], 'policy': digest(policy), 'seeds': parts['seeds']})
            review_payload = {'intent': data['intent'], 'contract_source': data['contract_source'],
                              'approved_assumptions': data.get('approved_assumptions', []), 'threat_model': threat_model,
                              'specification': snapshot['material']['specification'], 'policy': policy,
                              'must_succeed': parts['seeds'], 'checks': evaluation, 'reviewed_candidate_digest': candidate_digest}
            review = roles('open_review', review_payload, folder / 'open-review')
            ok = (isinstance(review, dict) and review.get('reviewed_candidate_digest') == candidate_digest and
                  review.get('verdict') == 'approve' and not review.get('missing_requirements'))
            attempt['review'] = review
            if ok:
                attempts.append(attempt)
                record = {'summary': 'Opened from creator input', 'trigger': {'kind': 'open'}, 'open_checks': evaluation,
                          'open_review': review, 'models': roles.models, 'provider': roles.name, 'attempts': attempts,
                          'credits': []}
                challenge = create(challenge_dir, data['id'], snapshot, policy, record, threat_model, roles.models)
                for seed in parts['seeds']:
                    challenge.add_case(case_material('must_succeed', seed['trace'], expected=seed['expected_success_actions']),
                                       {'challenge_version': 1, 'source': 'seed', 'description': seed['description']})
                challenge.publish()
                write(output / 'open.json', {'status': 'opened', 'attempts': attempts, 'challenge': str(challenge_dir)})
                return challenge
            feedback = {'error': 'Independent open review rejected the policy', 'review': review}
        else:
            feedback = {'error': 'Mechanical open checks failed', 'failures': evaluation['failures']}
        attempts.append(attempt)
        if policy_parts is not None: break
    write(output / 'open.json', {'status': 'rejected', 'attempts': attempts})
    raise ValueError('Challenge could not be opened: ' + '; '.join(attempts[-1]['failures'] or ['review rejected']))


def migrate_v1(v1_dir, seeds, challenge_dir, output, roles, options=None, model_map=None):
    """Convert a creator-reviewed v1 challenge (snapshot + policy + review record) to an automatic one."""
    v1_dir = Path(v1_dir)
    snapshot = validate_snapshot(read(v1_dir / 'snapshot.json'))
    old = read(v1_dir / 'policy.json'); record = read(v1_dir / 'review-record.json')
    if record.get('reviewed_policy_digest') != digest(old): raise ValueError('v1 policy has no matching review record')
    environment = {'deployments': [{'name': 'main', 'contract_name': old['contract_name'], 'constructor_arguments': [],
                                    'account': 0, 'value_wei': '0'}], 'setup': []}
    probes = [dict(p, target='main') if p['kind'] != 'account_balance' else p for p in old['probes']]
    requirements = []
    for r in old['requirements']:
        if r['review_status'] != 'approved': continue
        row = {k: v for k, v in r.items() if k != 'review_status'}
        row['origin'] = {'version': 1, 'source': 'migrated',
                         'rationale': 'Creator-reviewed in v1 policy ' + digest(old)[:16] + ' by ' + record.get('creator', 'creator')}
        requirements.append(row)
    parts = {'environment': environment, 'probes': probes, 'requirements': requirements, 'seeds': seeds, 'model_map': model_map}
    candidate = copy.deepcopy(snapshot['material']['specification'])
    for prop in candidate['properties']: prop['proof'] = 'by sorry'
    return open_challenge(snapshot['material']['input'], challenge_dir, output, roles, options, candidate=candidate, policy_parts=parts)
