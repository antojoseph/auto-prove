"""Automatic negative-case loop: judge -> credit -> minimal repair -> gate -> next version.

Participants submit negative cases (``transaction-contribution-v2``). For each
contribution, strictly one at a time (D-27):

1. bind it to a challenge version: stale submissions are rejected (D-23);
   submissions queued while a version shipped are rebased (D-27);
2. replay it on the current version and evaluate every requirement;
   mechanically detect weakening against earlier versions (D-17);
3. ask the judge (contributor prose quarantined, D-13), validate the judgment
   against the replay, and confirm any new requirement mechanically (D-4);
4. credit it, deduplicated by root-cause key (D-16, D-26);
5. ask the repair author for a minimal patch, run the anti-weakening gate and
   both reviews; adopt the next live version on success (D-3, D-5, D-15), or
   record a pending repair that is retried before later submissions (D-8).

Automatic adoption counts as approval (D-7); contract/model correspondence is
never claimed. No rollback (D-8): mistakes are corrected by later findings.
"""
from __future__ import annotations
import copy
import html
import json
import re
from pathlib import Path
from .attacks import assess, expression
from .challenge import (Challenge, POLICY_VERSION, CONTRIBUTION_VERSION, bind_check, blocked_is_safe, case_material,
                        contribution_check, now, refreeze, requirement_checks, run_case, validate_requirement)
from .chain import replay as chain_replay, validate_probe
from .core import digest, read, text, write
from . import differential, gate

KEY = re.compile(r'[a-z][a-z0-9_]{2,79}')
MAX_REPAIR_ATTEMPTS = 4


class Rejected(ValueError):
    pass


def parse_json(value, label, kind):
    if not isinstance(value, str): raise ValueError(label + ' must be a JSON string')
    try: parsed = json.loads(value)
    except json.JSONDecodeError as error: raise ValueError(label + ' is not valid JSON: ' + str(error)) from None
    if not isinstance(parsed, kind): raise ValueError(label + ' has the wrong JSON type')
    return parsed


# ---------------------------------------------------------------------------
# Evidence for the judge

def weakening_check(challenge, contribution, output, replay_fn):
    ref = contribution['requirement_ref']
    if ref is None: return {'status': 'not_applicable'}
    old_policy = challenge.policy(ref['version'])
    old = next(r for r in old_policy['requirements'] if r['id'] == ref['requirement_id'])
    strip = lambda r: {k: v for k, v in r.items() if k != 'origin'}
    current = challenge.policy(challenge.current)
    still = next((r for r in current['requirements'] if r['id'] == old['id']), None)
    if still is not None and strip(still) == strip(old):
        return {'status': 'requirement_unchanged', 'requirement': old}
    files = challenge.version_files(challenge.current)
    replayed = replay_fn(files['snapshot']['material']['input'], files['policy']['environment'], contribution['trace'],
                         output / 'weakening-replay', old_policy['probes'])
    if replayed['status'] != 'replayed':
        return {'status': 'inconclusive', 'requirement': old, 'reason': replayed.get('reason')}
    check = blocked_is_safe(assess(old, replayed))
    return {'status': 'original_requirement_violated' if check['status'] == 'demonstrated_violation' else 'original_requirement_holds',
            'requirement': old, 'requirement_version': ref['version'], 'current_form': still,
            'probes': old_policy['probes'], 'check': check}


def history(challenge):
    rows = []
    for version in range(2, challenge.current + 1):
        diff = read(challenge.folder(version) / 'diff.json')
        if diff['requirement_changes'] or diff['property_changes']:
            rows.append({'version': version, 'requirement_changes': diff['requirement_changes'],
                         'property_changes': [{'id': c['id'], 'change': c['change']} for c in diff['property_changes']]})
    return rows


def judge_payload(challenge, contribution, replayed, checks, weakening, model_check):
    files = challenge.version_files(challenge.current)
    m = files['snapshot']['material']
    return {'intent': m['input']['intent'], 'approved_assumptions': m['input'].get('approved_assumptions', []),
            'threat_model': challenge.meta['threat_model'], 'challenge_version': challenge.current,
            'next_version': challenge.current + 1,
            'contract_source': m['input']['contract_source'],
            'specification': {'model_body': m['specification']['model_body'],
                              'properties': m['specification']['properties']},
            'policy': files['policy'], 'requirement_history': history(challenge),
            'known_root_causes': challenge.meta.get('root_causes', {}),
            'submission': {'kind': contribution['kind'], 'requirement_ref': contribution['requirement_ref'],
                           'expected_success_actions': contribution['expected_success_actions'],
                           'trace': contribution['trace']},
            'replay': {'status': replayed['status'], 'reason': replayed.get('reason'),
                       'deployments': replayed.get('deployments'),
                       'transactions': [{k: t[k] for k in ('action', 'status', 'gas_used', 'timestamp')} for t in replayed.get('transactions', [])],
                       'frames': [{'step': f['step'], 'values': f['values']} for f in replayed.get('frames', [])]},
            'requirement_checks': {k: {'status': v['status'], 'violations': v.get('violations', [])[:5]} for k, v in checks.items()},
            'weakening_check': weakening, 'model_evm_differential': model_check,
            'untrusted_contributor_claim': contribution['claim']}


# ---------------------------------------------------------------------------
# Judgment validation

def validate_judgment(j, contribution, policy, checks, next_version):
    expected = {'verdict', 'root_cause_key', 'cited_actions', 'violated_requirement_ids', 'new_requirement_json',
                'new_probes_json', 'ambiguity_readings', 'ambiguity_choice', 'out_of_scope', 'reasoning'}
    if not isinstance(j, dict) or set(j) != expected: raise ValueError('Invalid judgment fields')
    verdict = j['verdict']
    if verdict not in ('contract_defect', 'spec_defect', 'both', 'blocked_legitimate', 'unsupported'): raise ValueError('Unknown verdict')
    text(j['reasoning'], 'judge reasoning')
    if type(j['out_of_scope']) is not bool: raise ValueError('Invalid out_of_scope flag')
    if not isinstance(j['ambiguity_readings'], list) or any(not isinstance(x, str) for x in j['ambiguity_readings']):
        raise ValueError('Invalid ambiguity readings')
    if bool(j['ambiguity_readings']) != bool(j['ambiguity_choice']): raise ValueError('Ambiguity readings and choice go together')
    if j['ambiguity_readings'] and len(j['ambiguity_readings']) < 2: raise ValueError('An ambiguity needs at least two readings')
    actions = len(contribution['trace']['actions'])
    if not isinstance(j['cited_actions'], list) or any(type(i) is not int or not 0 <= i < actions for i in j['cited_actions']):
        raise ValueError('Judge cited an action outside the trace')
    ids = {r['id'] for r in policy['requirements']}
    if not isinstance(j['violated_requirement_ids'], list) or not set(j['violated_requirement_ids']) <= ids:
        raise ValueError('Judge cited an unknown requirement')
    if verdict == 'unsupported':
        if j['root_cause_key'] or j['new_requirement_json']: raise ValueError('Unsupported verdicts carry no root cause or requirement')
        return {'judgment': j, 'new_requirement': None, 'new_probes': []}
    if j['out_of_scope']: raise ValueError('Out-of-scope findings must be judged unsupported')
    if not KEY.fullmatch(j['root_cause_key']): raise ValueError('Invalid root cause key')
    if not j['cited_actions']: raise ValueError('A finding must cite demonstrating actions')
    kind = contribution['kind']
    if kind == 'attack' and verdict == 'blocked_legitimate': raise ValueError('An attack submission cannot be judged blocked_legitimate')
    if kind == 'blocked_legitimate' and verdict in ('contract_defect', 'both'):
        raise ValueError('A blocked-legitimate submission is judged blocked_legitimate, spec_defect or unsupported')
    demonstrated = {k for k, v in checks.items() if v['status'] == 'demonstrated_violation'}
    if verdict == 'contract_defect':
        if not j['violated_requirement_ids'] or j['new_requirement_json']:
            raise ValueError('contract_defect cites violated current requirements and drafts none')
        if not set(j['violated_requirement_ids']) <= demonstrated:
            raise ValueError('Judge cited requirements the replay does not violate')
    if verdict == 'spec_defect':
        if not j['violated_requirement_ids'] or not set(j['violated_requirement_ids']) <= demonstrated:
            raise ValueError('spec_defect cites requirements the replay actually flags')
    if verdict == 'both':
        if not j['new_requirement_json']: raise ValueError('both drafts the missing requirement')
        if j['violated_requirement_ids'] and not set(j['violated_requirement_ids']) <= demonstrated:
            raise ValueError('Judge cited requirements the replay does not violate')
    if verdict == 'blocked_legitimate':
        if not set(j['cited_actions']) <= set(contribution['expected_success_actions']):
            raise ValueError('blocked_legitimate cites only actions the submission expects to succeed')
    new_requirement = None; new_probes = []
    if j['new_requirement_json']:
        new_requirement = parse_json(j['new_requirement_json'], 'new_requirement_json', dict)
        new_probes = parse_json(j['new_probes_json'] or '[]', 'new_probes_json', list)
        if new_requirement.get('id') in ids: raise ValueError('New requirement reuses an existing requirement id')
        origin = new_requirement.get('origin')
        if not isinstance(origin, dict) or origin.get('version') != next_version or origin.get('source') != 'judge':
            raise ValueError('New requirement origin must be the judge at the next version')
    elif j['new_probes_json'] not in ('', '[]'): raise ValueError('Probes are only added with a new requirement')
    return {'judgment': j, 'new_requirement': new_requirement, 'new_probes': new_probes}


def confirm_requirement(challenge, accepted, contribution, output, replay_fn):
    """A drafted requirement must be violated by the case and hold on legitimate traces."""
    files = challenge.version_files(challenge.current)
    snapshot, policy = files['snapshot'], copy.deepcopy(files['policy'])
    requirement = accepted['new_requirement']
    policy['probes'] = policy['probes'] + accepted['new_probes']
    names = {d['name'] for d in policy['environment']['deployments']}
    labels = [validate_probe(p, names) for p in policy['probes']]
    if len(labels) != len(set(labels)): raise ValueError('New probes reuse existing labels')
    props = {p['id'] for p in snapshot['material']['specification']['properties']}
    if requirement.get('scope') == 'spec':
        requirement = dict(requirement, scope='intent', property_id='')  # no new Lean target exists yet
    validate_requirement(requirement, set(labels), snapshot['material']['input']['intent'], props)
    replayed = replay_fn(snapshot['material']['input'], policy['environment'], contribution['trace'], output / 'confirm', policy['probes'])
    if replayed['status'] != 'replayed': raise ValueError('Confirmation replay inconclusive')
    if blocked_is_safe(assess(requirement, replayed))['status'] != 'demonstrated_violation':
        raise ValueError('The drafted requirement is not violated by this negative case')
    trial = dict(policy, requirements=policy['requirements'] + [requirement])
    for case in challenge.cases():
        if case['material']['kind'] != 'must_succeed': continue
        row = run_case(case['material'], snapshot, trial, output / 'confirm-legit' / case['id'][:16], replay_fn)
        if row['status'] != 'passed':
            raise ValueError('The drafted requirement forbids a recorded legitimate trace: ' + str(row.get('reason')))
    accepted['new_requirement'] = requirement
    return accepted


# ---------------------------------------------------------------------------
# Repair candidates

def build_candidate(challenge, response, accepted):
    expected = {'contract_source', 'model_body', 'properties_json', 'requirements_json', 'probes_json',
                'environment_json', 'model_map_json', 'removed_or_relaxed', 'change_summary', 'reasoning'}
    if not isinstance(response, dict) or set(response) != expected: raise ValueError('Invalid repair fields')
    text(response['contract_source'], 'contract source'); text(response['change_summary'], 'change summary')
    text(response['reasoning'], 'repair reasoning')
    declared = response['removed_or_relaxed']
    if not isinstance(declared, list) or any(not isinstance(d, dict) or set(d) != {'requirement_id', 'reason'} for d in declared):
        raise ValueError('Invalid removed_or_relaxed declarations')
    files = challenge.version_files(challenge.current)
    properties = parse_json(response['properties_json'], 'properties_json', list)
    requirements = parse_json(response['requirements_json'], 'requirements_json', list)
    probes = parse_json(response['probes_json'], 'probes_json', list)
    environment = parse_json(response['environment_json'], 'environment_json', dict)
    model_map = None if response['model_map_json'].strip() == 'null' else parse_json(response['model_map_json'], 'model_map_json', dict)
    # Existing requirements keep their origin; new ones originate at the next version.
    origins = {r['id']: r['origin'] for r in files['policy']['requirements']}
    for requirement in requirements:
        if not isinstance(requirement, dict): raise ValueError('Invalid requirement')
        if requirement.get('id') in origins: requirement['origin'] = origins[requirement['id']]
        elif not isinstance(requirement.get('origin'), dict) or requirement['origin'].get('version') != challenge.current + 1:
            raise ValueError('New requirements originate at the next version')
    snapshot = refreeze(files['snapshot'], response['contract_source'], response['model_body'], properties)
    policy = {'version': POLICY_VERSION, 'snapshot_digest': snapshot['digest'], 'environment': environment,
              'probes': probes, 'requirements': requirements, 'model_map': model_map}
    return {'snapshot': snapshot, 'policy': policy, 'digest': digest({'snapshot': snapshot['digest'], 'policy': digest(policy)}),
            'removed_or_relaxed': declared, 'change_summary': response['change_summary'], 'reasoning': response['reasoning']}


def repair_payload(challenge, finding, feedback):
    files = challenge.version_files(challenge.current); m = files['snapshot']['material']
    cases = challenge.cases()
    return {'intent': m['input']['intent'], 'approved_assumptions': m['input'].get('approved_assumptions', []),
            'threat_model': challenge.meta['threat_model'], 'next_version': challenge.current + 1,
            'judgment': {k: finding['judgment'][k] for k in ('verdict', 'root_cause_key', 'cited_actions',
                                                            'violated_requirement_ids', 'ambiguity_choice', 'reasoning')},
            'new_requirement': finding.get('new_requirement'), 'new_probes': finding.get('new_probes', []),
            'negative_case': {'trace': finding['contribution']['trace'],
                              'expected_success_actions': finding['contribution']['expected_success_actions'],
                              'replay': finding['replay_summary']},
            'current': {'contract_source': m['input']['contract_source'], 'model_body': m['specification']['model_body'],
                        'properties': m['specification']['properties'], 'policy': files['policy']},
            'must_fail_cases': [{'requirement': c['material']['requirement'], 'trace': c['material']['trace']}
                                for c in cases if c['material']['kind'] == 'must_fail'],
            'must_succeed_cases': [{'trace': c['material']['trace'], 'expected_success_actions': c['material']['expected_success_actions']}
                                   for c in cases if c['material']['kind'] == 'must_succeed'],
            'retry_feedback': feedback}


def repair(challenge, finding, roles, output, options):
    """Bounded attempts; adopt the first candidate that passes the gate and both reviews."""
    attempts = []; feedback = None
    for number in range(1, options.get('repair_attempts', MAX_REPAIR_ATTEMPTS) + 1):
        folder = Path(output) / ('repair-attempt-' + str(number)); folder.mkdir(parents=True)
        attempt = {'number': number}
        try:
            response = roles('repair', repair_payload(challenge, finding, feedback), folder / 'repair-author')
            candidate = build_candidate(challenge, response, finding)
            attempt['candidate_digest'] = candidate['digest']
            result = gate.mechanical(challenge, candidate, finding, folder / 'gate', options)
            attempt['gate'] = {'status': result['status'], 'failures': result['failures']}
            if result['status'] != 'passed':
                feedback = {'error': 'Mechanical gate failed', 'failures': result['failures'],
                            'regressions': result['checks'].get('regressions'), 'trigger': result['checks'].get('trigger')}
            else:
                review = gate.reviews(challenge, candidate, finding, result, roles, folder / 'reviews')
                attempt['reviews'] = {k: {'approved': v['approved'], 'reasons': v['reasons']} for k, v in review.items()}
                if all(v['approved'] for v in review.values()):
                    attempt['status'] = 'adoptable'; attempts.append(attempt)
                    write(folder / 'attempt.json', attempt)
                    return {'status': 'adoptable', 'candidate': candidate, 'gate': result, 'reviews': review, 'attempts': attempts}
                feedback = {'error': 'Independent review rejected the candidate',
                            'reviews': {k: {'verdict': v.get('verdict'), 'reasons': v['reasons'],
                                            'weakening_found': v.get('weakening_found'), 'unrelated_changes': v.get('unrelated_changes'),
                                            'over_restrictive': v.get('over_restrictive')} for k, v in review.items()}}
        except (ValueError, RuntimeError, KeyError) as error:
            feedback = {'error': str(error)}
        attempt['status'] = 'rejected'; attempt['feedback'] = feedback
        attempts.append(attempt); write(folder / 'attempt.json', attempt)
    return {'status': 'failed', 'attempts': attempts}


def adopt(challenge, finding, outcome, roles, credits):
    candidate = outcome['candidate']
    record = {'challenge_version': challenge.current + 1, 'parent_version': challenge.current,
              'summary': candidate['change_summary'],
              'trigger': {'submission_digest': finding['submission_digest'], 'contributor': finding['contribution']['contributor'],
                          'kind': finding['contribution']['kind']},
              'judgment': finding['judgment'], 'new_requirement': finding.get('new_requirement'),
              'removed_or_relaxed': candidate['removed_or_relaxed'], 'repair_reasoning': candidate['reasoning'],
              'gate': {'status': outcome['gate']['status'], 'checks': {k: v for k, v in outcome['gate']['checks'].items() if k != 'diff'}},
              'reviews': {k: {kk: vv for kk, vv in v.items()} for k, v in outcome['reviews'].items()},
              'repair_attempts': len(outcome['attempts']), 'models': roles.models, 'provider': roles.name,
              'credits': credits}
    version = challenge.adopt(candidate['snapshot'], candidate['policy'], record)
    added = []
    for material in regression_materials(finding, candidate['policy']):
        case_id, state = challenge.add_case(material, {'challenge_version': version, 'source': 'submission',
                                                       'submission_digest': finding['submission_digest'],
                                                       'contributor': finding['contribution']['contributor'],
                                                       'contributor_model': finding['contribution']['contributor_model'],
                                                       'root_cause_key': finding['judgment']['root_cause_key']})
        added.append({'case_id': case_id, 'state': state, 'kind': material['kind']})
    causes = challenge.meta.setdefault('root_causes', {})
    if finding['judgment']['root_cause_key'] in causes:
        causes[finding['judgment']['root_cause_key']]['status'] = 'fixed_in_v' + str(version)
    write(challenge.root / 'challenge.json', challenge.meta)
    challenge.publish()
    return version, added


def regression_materials(finding, policy):
    trace = finding['contribution']['trace']; verdict = finding['judgment']['verdict']
    if verdict == 'blocked_legitimate' or finding['contribution']['kind'] == 'blocked_legitimate':
        return [case_material('must_succeed', trace, expected=finding['contribution']['expected_success_actions'])]
    if verdict == 'spec_defect':
        return [case_material('must_succeed', trace, expected=[])]  # flagged behaviour must stay unflagged
    rows = []
    for item in finding.get('violated', []):
        rows.append(case_material('must_fail', trace, item['requirement'], item['probes']))
    if finding.get('new_requirement'):
        adopted = next(r for r in policy['requirements'] if r['id'] == finding['new_requirement']['id'])
        rows.append(case_material('must_fail', trace, adopted, policy['probes']))
    return rows


# ---------------------------------------------------------------------------
# One contribution

def process_contribution(challenge, raw, output, roles, options, submitted_at=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    replay_fn = options.get('replay', chain_replay)
    row = {'submission_digest': digest(raw), 'version_before': challenge.current, 'credits': [], 'time': now()}
    try:
        contribution = contribution_check(challenge, raw)
        row['bind'] = bind_check(challenge, contribution, submitted_at)
    except ValueError as error:
        row.update(outcome='stale' if 'Stale' in str(error) else 'rejected_invalid', reason=str(error))
        return finish(challenge, row, output, raw)
    row.update(contributor=contribution['contributor'], kind=contribution['kind'])
    if contribution['kind'] == 'reproduction':
        return finish(challenge, reproduction(challenge, contribution, row, output, replay_fn), output, raw)

    files = challenge.version_files(challenge.current)
    replayed = replay_fn(files['snapshot']['material']['input'], files['policy']['environment'], contribution['trace'],
                         output / 'replay', files['policy']['probes'])
    if replayed['status'] != 'replayed':
        row.update(outcome='inconclusive', reason=replayed.get('reason'))
        return finish(challenge, row, output, raw)
    checks = requirement_checks(files['policy'], replayed)
    weakening = weakening_check(challenge, contribution, output, replay_fn)
    model_check = {'status': 'not_run'}
    if options.get('differential', 'docker') == 'docker' and files['policy'].get('model_map') is not None:
        model_check = gate.summary(differential.compare(files['snapshot'], files['policy'], [('submission', contribution['trace'], replayed)], output / 'differential'))
    row['evidence'] = {'requirement_checks': {k: v['status'] for k, v in checks.items()},
                       'statuses': [t['status'] for t in replayed['transactions']], 'weakening': weakening['status'],
                       'model_evm_differential': model_check.get('status')}
    payload = judge_payload(challenge, contribution, replayed, checks, weakening, model_check)
    accepted = None
    for attempt in (1, 2):
        judgment = roles('judge', payload, output / ('judge-' + str(attempt)))
        try:
            accepted = validate_judgment(judgment, contribution, files['policy'], checks, challenge.current + 1)
            if accepted['new_requirement']: accepted = confirm_requirement(challenge, accepted, contribution, output / ('confirm-' + str(attempt)), replay_fn)
            break
        except ValueError as error:
            row.setdefault('judge_corrections', []).append(str(error)); accepted = None
            payload = dict(payload, previous_judgment=judgment, correction=str(error))
    if accepted is None:
        row.update(outcome='judge_invalid', reason='Judgment failed validation twice; fail closed')
        return finish(challenge, row, output, raw)
    j = accepted['judgment']; row['judgment'] = j
    if j['verdict'] == 'unsupported':
        row.update(outcome='judged_unsupported', reason=j['reasoning'])
        return finish(challenge, row, output, raw)

    violated = [{'requirement': r, 'probes': files['policy']['probes']} for r in files['policy']['requirements']
                if r['id'] in j['violated_requirement_ids']] if j['verdict'] != 'spec_defect' else []
    if weakening['status'] == 'original_requirement_violated' and j['verdict'] in ('both', 'contract_defect'):
        # The removed/relaxed protection stays a regression with its ORIGINAL predicate and probes.
        violated.append({'requirement': weakening['requirement'], 'probes': weakening['probes']})
    finding = {'contribution': contribution, 'submission_digest': row['submission_digest'], 'judgment': j,
               'new_requirement': accepted['new_requirement'], 'new_probes': accepted['new_probes'],
               'violated': violated, 'weakening': weakening if weakening['status'] == 'original_requirement_violated' else None,
               'replay_summary': payload['replay'], 'requirement_checks': payload['requirement_checks']}
    credits = award(challenge, finding, weakening, row)
    causes = challenge.meta.setdefault('root_causes', {})
    causes.setdefault(j['root_cause_key'], {'description': j['reasoning'][:600], 'first_version': challenge.current, 'status': 'open'})
    write(challenge.root / 'challenge.json', challenge.meta)
    outcome = repair(challenge, finding, roles, output / 'repair', options)
    row['repair'] = {'status': outcome['status'], 'attempts': outcome['attempts']}
    duplicate = not credits
    if outcome['status'] == 'adoptable':
        version, added = adopt(challenge, finding, outcome, roles, credits)
        row.update(outcome='duplicate_repaired' if duplicate else 'accepted_repaired', version_after=version, cases=added)
    else:
        pending = {'submission_digest': row['submission_digest'], 'finding': finding, 'since_version': challenge.current, 'time': now()}
        challenge.meta.setdefault('pending_repairs', []).append(pending)
        write(challenge.root / 'challenge.json', challenge.meta); challenge.publish()
        row.update(outcome='duplicate_repair_pending' if duplicate else 'accepted_repair_pending')
    return finish(challenge, row, output, raw)


def award(challenge, finding, weakening, row):
    """Credit the first accepted case per root cause (D-16) with D-26 weights."""
    j = finding['judgment']; key = 'root:' + j['root_cause_key']
    if key in challenge.credited_keys(): return []
    if j['verdict'] == 'blocked_legitimate' or finding['contribution']['kind'] == 'blocked_legitimate': credit_class = 'legit_action_blocked'
    elif weakening['status'] == 'original_requirement_violated' and j['verdict'] in ('both', 'contract_defect'): credit_class = 'weakening_found'
    else: credit_class = 'new_root_cause'
    entry = challenge.credit({'class': credit_class, 'key': key, 'submission_digest': finding['submission_digest'],
                              'contributor': finding['contribution']['contributor'],
                              'contributor_model': finding['contribution']['contributor_model'],
                              'challenge_version': challenge.current, 'root_cause_key': j['root_cause_key']})
    row['credits'].append(entry)
    return [entry]


def reproduction(challenge, contribution, row, output, replay_fn):
    case = read(challenge.case_path(contribution['reproduces']))
    if case['material']['kind'] != 'must_fail':
        row.update(outcome='reproduction_rejected', reason='Only accepted attacks can be reproduced'); return row
    origin = case['origin']; prior = challenge.reproductions(case['id'])
    fam = lambda model: model.split('/', 1)[0].lower() if '/' in model else model.split()[0].lower()
    if contribution['contributor'] in [origin.get('contributor')] + [p['contributor'] for p in prior]:
        row.update(outcome='reproduction_rejected', reason='Reproduction needs a distinct attribution'); return row
    if fam(contribution['contributor_model']) in [fam(origin.get('contributor_model', ''))] + [fam(p['contributor_model']) for p in prior]:
        row.update(outcome='reproduction_rejected', reason='Reproduction needs a distinct model family'); return row
    if len(prior) >= 2:
        row.update(outcome='reproduction_rejected', reason='Case already has two credited reproductions'); return row
    version = origin['challenge_version'] - 1  # the version on which the attack was demonstrated
    files = challenge.version_files(max(1, version))
    try:
        from .chain import validate_trace
        validate_trace(contribution['trace'], files['policy']['environment'])
    except ValueError as error:
        row.update(outcome='reproduction_rejected', reason=str(error)); return row
    replayed = replay_fn(files['snapshot']['material']['input'], files['policy']['environment'], contribution['trace'],
                         output / 'reproduction', case['material']['probes'])
    status = blocked_is_safe(assess(case['material']['requirement'], replayed))['status'] if replayed['status'] == 'replayed' else 'inconclusive'
    if status != 'demonstrated_violation':
        row.update(outcome='reproduction_rejected', reason='Trace does not reproduce the accepted violation on version ' + str(version)); return row
    entry = challenge.credit({'class': 'reproduction', 'key': 'reproduction:' + case['id'] + ':' + digest(contribution['trace'])[:16],
                              'submission_digest': row['submission_digest'], 'contributor': contribution['contributor'],
                              'contributor_model': contribution['contributor_model'], 'challenge_version': challenge.current,
                              'root_cause_key': origin.get('root_cause_key')})
    row['credits'].append(entry); row['outcome'] = 'reproduction_credited'
    return row


def retry_pending(challenge, roles, output, options):
    """Fix forward (D-8): retry unresolved repairs before newer submissions."""
    rows = []; remaining = []
    replay_fn = options.get('replay', chain_replay)
    for index, pending in enumerate(challenge.meta.get('pending_repairs', [])):
        folder = Path(output) / ('pending-' + str(index + 1)); folder.mkdir(parents=True)
        finding = pending['finding']; files = challenge.version_files(challenge.current)
        replayed = replay_fn(files['snapshot']['material']['input'], files['policy']['environment'],
                             finding['contribution']['trace'], folder / 'recheck', files['policy']['probes'])
        still = replayed['status'] == 'replayed' and any(
            blocked_is_safe(assess(v['requirement'], replayed))['status'] == 'demonstrated_violation'
            for v in finding['violated'] if v['probes'] == files['policy']['probes'])
        if replayed['status'] == 'replayed' and not still and not finding.get('new_requirement') and finding['judgment']['verdict'] == 'contract_defect':
            rows.append({'submission_digest': pending['submission_digest'], 'outcome': 'resolved_by_intervening_version'}); continue
        outcome = repair(challenge, finding, roles, folder / 'repair', options)
        if outcome['status'] == 'adoptable':
            version, added = adopt(challenge, finding, outcome, roles, [])
            rows.append({'submission_digest': pending['submission_digest'], 'outcome': 'pending_repaired', 'version_after': version})
        else:
            remaining.append(pending); rows.append({'submission_digest': pending['submission_digest'], 'outcome': 'still_pending'})
    challenge.meta['pending_repairs'] = remaining
    write(challenge.root / 'challenge.json', challenge.meta)
    return rows


def finish(challenge, row, output, raw):
    row['version_after'] = row.get('version_after', challenge.current)
    event = {k: row.get(k) for k in ('time', 'submission_digest', 'contributor', 'kind', 'outcome', 'version_before', 'version_after')}
    event['credits'] = [c['class'] for c in row['credits']]
    challenge.append('events.jsonl', event)
    challenge.publish()
    write(Path(output) / 'contribution.json', raw); write(Path(output) / 'result.json', row)
    return row


# ---------------------------------------------------------------------------
# Submission

def process(challenge_dir, submission_dir, output, roles, options=None, submitted_at=None):
    options = options or {}
    challenge = Challenge(challenge_dir); output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = submitted_at or now()
    report = {'version': 'auto-loop-v1', 'started_at': started, 'version_before': challenge.current,
              'provider': roles.name, 'models': roles.models, 'pending': retry_pending(challenge, roles, output / 'pending', options),
              'contributions': [], 'formal': None}
    folder = Path(submission_dir) / 'contributions'
    paths = sorted(folder.glob('*.json')) if folder.is_dir() else []
    if len(paths) > 20: raise Rejected('At most 20 contributions per submission')
    for index, path in enumerate(paths):
        if path.stat().st_size > 262144: raise Rejected(path.name + ' exceeds 256 KiB')
        row = process_contribution(Challenge(challenge_dir), read(path), output / ('contribution-' + str(index + 1)),
                                   roles, options, submitted_at=started)
        row['file'] = path.name; report['contributions'].append(row)
    formal = Path(submission_dir) / 'formal.json'
    if formal.exists(): report['formal'] = lean_bonus(Challenge(challenge_dir), read(formal), output / 'formal', options)
    challenge = Challenge(challenge_dir)
    earned = [c for row in report['contributions'] for c in row['credits']] + (report['formal'] or {}).get('credits', [])
    report.update(version_after=challenge.current, score=round(sum(c['weight'] for c in earned), 4),
                  credits=earned, status=challenge.status(), approval='approved_automatically',
                  contract_correspondence='not_proved')
    write(output / 'report.json', report)
    render(output, report)
    return report


def lean_bonus(challenge, finding, output, options):
    """+5 for a kernel-checked refutation of a current frozen Lean target."""
    from .pipeline import evidence
    result = {'credits': []}
    if not isinstance(finding, dict) or set(finding) != {'property_id', 'proof', 'contributor', 'contributor_model'}:
        result['status'] = 'rejected'; result['reason'] = 'formal.json needs property_id, proof, contributor, contributor_model'; return result
    snapshot = challenge.snapshot(challenge.current)
    key = 'lean:' + snapshot['digest'] + ':' + str(finding['property_id'])
    if key in challenge.credited_keys():
        result['status'] = 'duplicate'; return result
    if options.get('lean', 'docker') != 'docker':
        result['status'] = 'not_run'; return result
    check = evidence(snapshot, {'evidence_kind': 'model_counterexample', 'property_id': finding['property_id'],
                                'proof': finding['proof'], 'reasoning': 'Submitted exact-target refutation'}, output)
    result['status'] = check['status']
    if check['status'] == 'supported_model_counterexample':
        result['credits'].append(challenge.credit({'class': 'lean_refutation', 'key': key, 'submission_digest': digest(finding),
                                                   'contributor': finding['contributor'], 'contributor_model': finding['contributor_model'],
                                                   'challenge_version': challenge.current, 'root_cause_key': 'lean_' + finding['property_id']}))
    return result


def render(output, report):
    esc = lambda value: html.escape(str(value))
    rows = []
    for row in report['contributions']:
        rows.append('<tr><td>' + esc(row.get('file')) + '</td><td>' + esc(row.get('kind')) + '</td><td><b>' + esc(row['outcome']) +
                    '</b></td><td>' + esc(row.get('judgment', {}).get('root_cause_key', '')) + '</td><td>' +
                    esc(', '.join(c['class'] + ' ' + str(c['weight']) for c in row['credits'])) + '</td><td>v' +
                    esc(row['version_before']) + ' → v' + esc(row['version_after']) + '</td></tr>')
    page = ('<!doctype html><meta charset="utf-8"><title>spec.prove automatic loop</title><style>body{font:16px system-ui;'
            'max-width:1100px;margin:40px auto;padding:0 24px}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;'
            'padding:8px;text-align:left}pre{white-space:pre-wrap;font:12px monospace}aside{background:#eef4ff;padding:14px}</style>'
            '<h1>Negative case → judge → repair → gate → next version</h1><aside>Approval: <b>approved_automatically</b> '
            '(judge + independent reviewer + mechanical gate). Contract/model correspondence: <b>not proved</b>. '
            'Not a security certificate.</aside><p>Score: <b>' + esc(report['score']) + '</b> · versions v' +
            esc(report['version_before']) + ' → v' + esc(report['version_after']) + '</p><table><tr><th>File</th><th>Kind</th>'
            '<th>Outcome</th><th>Root cause</th><th>Credits</th><th>Version</th></tr>' + ''.join(rows) + '</table>'
            '<details><summary>Full report</summary><pre>' + esc(json.dumps(report, indent=2, ensure_ascii=False)) + '</pre></details>')
    (Path(output) / 'report.html').write_text(page)
