"""Versioned transaction contributions and maintainer-owned regression cases.

The snapshot, policy and registry are TRUSTED runner inputs, never submission
files. All expressions are bounded JSON data; no agent code or eval is used.
Operational predicates are reviewed interpretations, not Lean/EVM equivalence.
"""
from __future__ import annotations
import copy
import html
import json
from pathlib import Path
from .core import digest, identifier, text, validate_snapshot, write, read
from .evm import replay, validate_trace

VERSION = 'transaction-attack-v1'
HEX = set('0123456789abcdef')


def hash_value(value):
    if not isinstance(value, str) or len(value) != 64 or set(value) - HEX:
        raise ValueError('Invalid digest')
    return value


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Invalid ' + label + ' fields')


def expression(expr, labels, depth=0, budget=None):
    budget = [128] if budget is None else budget
    budget[0] -= 1
    if depth > 8 or budget[0] < 0: raise ValueError('Predicate exceeds bounded expression budget')
    if type(expr) in (int, bool):
        if type(expr) is int and abs(expr) >= 2**256: raise ValueError('Oversized predicate integer')
        return
    if isinstance(expr, str):
        if len(expr) > 200: raise ValueError('Oversized predicate string')
        return
    if not isinstance(expr, dict): raise ValueError('Invalid predicate expression')
    if set(expr) == {'ref'}:
        if expr['ref'] not in labels: raise ValueError('Unknown probe reference')
        return
    fields(expr, 'op args', 'expression')
    op, args = expr['op'], expr['args']
    if op not in ('eq', 'ne', 'lt', 'le', 'gt', 'ge', 'add', 'sub', 'mul', 'and', 'or', 'not'):
        raise ValueError('Unknown predicate operator')
    if not isinstance(args, list) or len(args) != (1 if op == 'not' else 2):
        raise ValueError('Invalid predicate arity')
    for arg in args: expression(arg, labels, depth+1, budget)


def evaluate(expr, values):
    if not isinstance(expr, dict): return expr
    if 'ref' in expr: return values[expr['ref']]
    op = expr['op']; args = [evaluate(e, values) for e in expr['args']]
    if op in ('and', 'or', 'not'):
        if any(type(v) is not bool for v in args): raise ValueError('Logical predicate requires booleans')
        if op == 'not': return not args[0]
        return (args[0] and args[1]) if op == 'and' else (args[0] or args[1])
    if op in ('eq', 'ne'):
        if type(args[0]) is not type(args[1]): raise ValueError('Predicate compares incompatible types')
        return args[0] == args[1] if op == 'eq' else args[0] != args[1]
    if any(type(v) is not int for v in args): raise ValueError('Arithmetic predicate requires integers')
    a, b = args
    return {'lt':lambda:a < b, 'le':lambda:a <= b, 'gt':lambda:a > b, 'ge':lambda:a >= b,
            'add':lambda:a+b, 'sub':lambda:a-b, 'mul':lambda:a*b}[op]()


def requirement_check(requirement, probes):
    fields(requirement, 'id scope property_id requirement intent_quote review_status step_scope predicate', 'requirement')
    identifier(requirement['id']); text(requirement['requirement'], 'English requirement')
    text(requirement['intent_quote'], 'intent quotation')
    if requirement['scope'] not in ('spec', 'intent'): raise ValueError('Invalid requirement scope')
    if requirement['review_status'] not in ('pending', 'approved'): raise ValueError('Invalid requirement review status')
    scope = requirement['step_scope']
    if not isinstance(scope, str): raise ValueError('Invalid predicate step scope')
    if scope not in ('each', 'final'):
        if not scope.startswith('after:'): raise ValueError('Invalid predicate step scope')
        validate_trace({'contract_name':'Check', 'constructor_arguments':[], 'observations':[],
                        'actions':[{'account':0, 'function':scope[6:], 'arguments':[], 'value_wei':'0'}]})
        if not scope[6:]: raise ValueError('Predicate action selector needs a function')
    if requirement['scope'] == 'spec': identifier(requirement['property_id'])
    elif requirement['property_id'] != '': raise ValueError('An intent requirement must not claim a Lean target')
    expression(requirement['predicate'], {p['label'] for p in probes})


def policy_check(snapshot, policy):
    validate_snapshot(snapshot)
    fields(policy, 'version snapshot_digest contract_name probes requirements', 'attack policy')
    if policy['version'] != VERSION or policy['snapshot_digest'] != snapshot['digest']:
        raise ValueError('Attack policy addresses a different snapshot')
    identifier(policy['contract_name'])
    probes = policy['probes']
    if not isinstance(probes, list) or not 1 <= len(probes) <= 20: raise ValueError('Need 1-20 trusted probes')
    labels = []
    for probe in probes:
        if not isinstance(probe, dict): raise ValueError('Invalid probe')
        if probe.get('kind') == 'balance': fields(probe, 'kind label', 'balance probe')
        elif probe.get('kind') == 'view':
            fields(probe, 'kind label function arguments', 'view probe')
            # Reuse the bounded ABI data validator without executing anything.
            validate_trace({'contract_name':policy['contract_name'], 'constructor_arguments':[],
                            'actions':[{'account':0, 'function':'', 'arguments':[], 'value_wei':'0'}],
                            'observations':[{k:probe[k] for k in ('label','function','arguments')}]})
        else: raise ValueError('Invalid probe kind')
        labels.append(identifier(probe['label']))
    if len(labels) != len(set(labels)): raise ValueError('Duplicate trusted probe label')
    requirements = policy['requirements']
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 20: raise ValueError('Need 1-20 operational requirements')
    ids = []
    props = {p['id'] for p in snapshot['material']['specification']['properties']}
    for req in requirements:
        requirement_check(req, probes); ids.append(req['id'])
        if req['intent_quote'] not in snapshot['material']['input']['intent']:
            raise ValueError('Requirement quotation is absent from creator intent')
        if req['scope'] == 'spec' and req['property_id'] not in props:
            raise ValueError('Operational requirement references an absent Lean property')
    if len(ids) != len(set(ids)): raise ValueError('Duplicate requirement ID')
    return copy.deepcopy(policy)


def submission_check(snapshot, policy, submission):
    policy_check(snapshot, policy)
    fields(submission, 'version snapshot_digest policy_digest contributor requirement_id reasoning trace', 'attack submission')
    if submission['version'] != VERSION or submission['snapshot_digest'] != snapshot['digest']:
        raise ValueError('Attack submission addresses a different snapshot')
    if submission['policy_digest'] != digest(policy): raise ValueError('Attack submission addresses a different policy')
    text(submission['contributor'], 'contributor attribution'); text(submission['reasoning'], 'attack reasoning')
    if submission['requirement_id'] not in {r['id'] for r in policy['requirements']}:
        raise ValueError('Unknown attacked requirement')
    validate_trace(submission['trace'])
    if submission['trace']['contract_name'] != policy['contract_name']:
        raise ValueError('Attack selects a different contract')
    return copy.deepcopy(submission)


def assess(requirement, replayed):
    if replayed['status'] != 'replayed': return {'status':'inconclusive', 'violations':[]}
    frames = replayed.get('frames', [])
    if len(frames) != len(replayed['transactions']) + 1 or [f['step'] for f in frames] != list(range(len(frames))):
        return {'status':'inconclusive', 'violations':[], 'reason':'Incomplete replay state history'}
    scope = requirement['step_scope']
    if scope == 'each': selected = frames
    elif scope == 'final': selected = frames[-1:]
    else:
        selected = [frames[i+1] for i, tx in enumerate(replayed['transactions'])
                    if tx['action']['function'] == scope[6:] and tx['status'] == 'success']
    if not selected: return {'status':'inconclusive', 'violations':[], 'reason':'No successful matching action to check'}
    checks = []
    try:
        for frame in selected:
            satisfied = evaluate(requirement['predicate'], frame['values'])
            if type(satisfied) is not bool: raise ValueError('Top-level predicate is not boolean')
            checks.append({'step':frame['step'], 'satisfied':satisfied, 'values':frame['values']})
    except (KeyError, TypeError, ValueError) as error:
        return {'status':'inconclusive', 'violations':[], 'reason':str(error)}
    violations = [c for c in checks if not c['satisfied']]
    status = 'demonstrated_violation' if violations else 'not_demonstrated'
    return {'status':status, 'violations':violations, 'checks':checks}


def render(output, report):
    write(Path(output)/'attack.json', report)
    payload = html.escape(json.dumps(report, indent=2, ensure_ascii=False))
    page = '<!doctype html><meta charset="utf-8"><title>Transaction attack evidence</title>'
    page += '<style>body{font:17px system-ui;max-width:1050px;margin:40px auto;padding:24px}pre{font:13px monospace;white-space:pre-wrap;overflow-wrap:anywhere}aside{padding:16px;background:#fff4da}</style>'
    page += '<h1>Transaction attack: ' + html.escape(report['status']) + '</h1>'
    page += '<p>' + html.escape(report['submission']['reasoning']) + '</p>'
    page += '<aside>Operational requirement checks are separate from Lean refutations. English interpretation and model/EVM correspondence are not proved. Attack acceptance is separate from contract approval.</aside>'
    page += '<h2>State transitions, requirements and evidence</h2><pre>' + payload + '</pre>'
    (Path(output)/'report.html').write_text(page)


def adjudicate(snapshot, policy, submission, output):
    submission = submission_check(snapshot, policy, submission)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    trace = copy.deepcopy(submission['trace'])
    trace['observations'] = []  # Only owner-authored probes decide the requirement.
    replayed = replay(snapshot['material']['input'], trace, output/'replay', probes=policy['probes'])
    rows = {r['id']:assess(r, replayed) for r in policy['requirements']}
    requirement = next(r for r in policy['requirements'] if r['id'] == submission['requirement_id'])
    assessment = rows[requirement['id']]; status = assessment['status']
    if status == 'demonstrated_violation':
        status = 'demonstrated_' + ('proposed' if requirement['review_status'] == 'pending' else requirement['scope']) + '_requirement_violation'
    report = {'version':VERSION, 'snapshot_digest':snapshot['digest'], 'policy_digest':digest(policy),
              'submission_digest':digest(submission), 'submission':submission, 'requirement':requirement,
              'status':status, 'assessment':assessment, 'all_requirement_checks':rows, 'replay':replayed,
              'formal_refutation':'not_checked; use general evidence for exact Lean target refutation',
              'requirement_review':requirement['review_status'], 'attack_acceptance':'pending',
              'creator_approval':'pending', 'contract_correspondence':'not_proved', 'accepted':False}
    render(output, report)
    return report


def case_material(snapshot, policy, submission):
    requirement = next(r for r in policy['requirements'] if r['id'] == submission['requirement_id'])
    trace = copy.deepcopy(submission['trace']); trace['observations'] = []
    # Notes, attribution and epoch are excluded from exact-duplicate identity.
    return {'input_digest':digest(snapshot['material']['input']), 'requirement':requirement,
            'probes':policy['probes'], 'trace':trace}


def accept(snapshot, policy, submission, registry, output, category, reason):
    """Maintainer-only decision. Always replay freshly; never accept an agent's report."""
    text(reason, 'maintainer decision')
    if category not in ('contract_bug', 'spec_gap', 'model_gap'): raise ValueError('Invalid acceptance category')
    submission_check(snapshot, policy, submission)
    requirement = next(r for r in policy['requirements'] if r['id'] == submission['requirement_id'])
    if requirement['review_status'] != 'approved': raise ValueError('Review the operational requirement before accepting attacks')
    report = adjudicate(snapshot, policy, submission, output)
    if report['assessment']['status'] != 'demonstrated_violation':
        raise ValueError('No replayed requirement violation; attack not accepted')
    if report['assessment']['violations'][0]['step'] == 0:
        raise ValueError('Requirement already fails at deployment; review the initial-state policy')
    material = case_material(snapshot, policy, submission); case_id = digest(material)
    registry = Path(registry); registry.mkdir(parents=True, exist_ok=True)
    path = registry/(case_id+'.json')
    case = {'version':VERSION, 'id':case_id, 'material':material, 'origin_snapshot':snapshot,
            'origin_policy':policy, 'submission':submission,
            'decision':{'category':category, 'reason':reason, 'evidence_digest':digest(report)}}
    # Exclusive create supports concurrent independent maintainers without overwriting.
    try:
        with path.open('x') as handle: json.dump(case, handle, indent=2, ensure_ascii=False); handle.write('\n')
        state = 'accepted'
    except FileExistsError:
        existing = read(path)
        if existing.get('material') != material: raise ValueError('Registry case identity mismatch')
        state = 'duplicate'
    report['attack_acceptance'] = state; report['regression_case_id'] = case_id
    # accepted stays false: accepting a finding does not approve a contract.
    render(output, report)
    return report


def regress(snapshot, registry, output):
    """Replay original predicates/probes, even after a target is weakened or removed."""
    validate_snapshot(snapshot)
    if not Path(registry).is_dir(): raise ValueError('Accepted attack registry does not exist')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    rows = []; current = snapshot['material']; props = {p['id']:p for p in current['specification']['properties']}
    for path in sorted(Path(registry).glob('*.json')):
        case = read(path)
        if case.get('version') != VERSION or case.get('id') != digest(case['material']) or path.stem != case['id']:
            raise ValueError('Corrupt registry case')
        origin = validate_snapshot(case['origin_snapshot'])
        policy_check(origin, case['origin_policy']); submission_check(origin, case['origin_policy'], case['submission'])
        if case['material'] != case_material(origin, case['origin_policy'], case['submission']):
            raise ValueError('Registry material differs from accepted attack')
        before = origin['material']['input']; after = current['input']
        if any(before.get(k) != after.get(k) for k in ('id','intent','approved_assumptions')):
            raise ValueError('Regression input changes intent, identity or approved assumptions')
        req = case['material']['requirement']
        if req['review_status'] != 'approved': raise ValueError('Unapproved regression requirement')
        original_props = {p['id']:p for p in origin['material']['specification']['properties']}
        mapping_changed = (req['scope'] == 'spec' and
                           (props.get(req['property_id']) != original_props[req['property_id']] or
                            current['specification']['model_body'] != origin['material']['specification']['model_body']))
        replayed = replay(after, case['material']['trace'], output/case['id'], probes=case['material']['probes'])
        assessment = assess(req, replayed)
        if assessment['status'] == 'demonstrated_violation': status = 'still_violates_original_requirement'
        elif assessment['status'] == 'not_demonstrated': status = 'requires_mapping_review' if mapping_changed else 'passed_replay'
        else: status = 'inconclusive'
        rows.append({'case_id':case['id'], 'origin_snapshot_digest':origin['digest'], 'requirement':req,
                     'decision':case['decision'], 'status':status, 'mapping_changed':mapping_changed,
                     'assessment':assessment, 'replay':replayed})
    result = {'version':VERSION, 'snapshot_digest':snapshot['digest'], 'cases':rows,
              'status':'no_cases' if not rows else ('passed_replay' if all(r['status']=='passed_replay' for r in rows) else 'needs_attention'),
              'accepted':False, 'creator_approval':'pending', 'contract_correspondence':'not_proved',
              'meaning':'Selected accepted transaction regressions only; no comprehensive safety conclusion'}
    write(output/'regressions.json', result)
    return result
