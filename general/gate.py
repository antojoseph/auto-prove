"""Anti-weakening gate for automatic repairs (backlog I-13, decisions D-5, D-24).

A candidate version (new contract source and/or specification and/or policy)
ships only if every mechanical floor passes AND two reviewers from different
model families approve it. Mechanical floors:

1. The candidate parses: specification, frozen snapshot and policy v2 validate.
2. The contract compiles; existing storage variables keep slot, offset and type
   (new variables may only be appended); no new address literals appear.
3. The submitted negative case is fixed on the candidate.
4. Every accepted attack (must_fail case) no longer violates its ORIGINAL
   requirement with its ORIGINAL probes, even if the requirement was changed.
5. Every legitimate trace (must_succeed case) still succeeds with each listed
   action and violates none of the candidate's requirements.
6. Requirement removals and changes are declared; undeclared ones are rejected.
7. The Lean model and frozen targets compile (Docker; ``not_run`` only when
   explicitly configured off for offline tests, and then recorded as such).
8. Model/EVM divergences on recorded traces do not increase.

Within these floors the judge-family reviewer and the independent reviewer
decide whether anything was weakened (D-5). Patch-size metrics are evidence for
that review (D-24): changed functions, line counts and storage effects.
"""
from __future__ import annotations
import copy
import re
from pathlib import Path
from .backend import container, LAKE
from .challenge import (policy_check, requirement_checks, run_case, version_diff, blocked_is_safe)
from .attacks import assess
from .chain import members, storage_layout, compile_source, replay as chain_replay
from .core import digest, validate_model, write
from . import differential

ADDRESS = re.compile(r'0x[0-9a-fA-F]{40}')


def lean_compile(snapshot, output):
    """Compile the frozen model and challenge stubs in the isolated verifier."""
    import shutil, tempfile
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    if not shutil.which('docker'): return {'status': 'failed', 'reason': 'Docker unavailable'}
    m = snapshot['material']
    names = ['AutoSpec.req_' + p['id'] for p in m['specification']['properties']]
    definitions = ['AutoSpec.' + n for n in validate_model(m['specification']['model_body'])]
    with tempfile.TemporaryDirectory(prefix='auto-prove-compile-') as temp:
        root = Path(temp); root.chmod(0o755)
        inputs = root / 'in'; outputs = root / 'out'
        inputs.mkdir(mode=0o755); outputs.mkdir(mode=0o777); outputs.chmod(0o777)
        (inputs / 'Model.lean').write_text(m['model_source'])
        (inputs / 'Challenge.lean').write_text(m['challenge_source'])
        (inputs / 'lakefile.toml').write_text(LAKE)
        write(inputs / 'request.json', {'mode': 'export', 'module': 'Challenge', 'targets': names + definitions})
        code, log = container(inputs, outputs)
    (output / 'lean-compile.log').write_text(log)
    return {'status': 'compiled' if code == 0 else 'failed',
            'reason': None if code == 0 else 'Lean model/targets did not compile; inspect lean-compile.log'}


def contract_metrics(before, after):
    old = members(before); new = members(after)
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    added = sorted(set(new) - set(old)); removed = sorted(set(old) - set(new))
    lines_before = before.splitlines(); lines_after = after.splitlines()
    import difflib
    delta = sum(1 for line in difflib.unified_diff(lines_before, lines_after, lineterm='', n=0)
                if line.startswith(('+', '-')) and not line.startswith(('+++', '---')))
    contracts_before = compile_source(before); contracts_after = compile_source(after)
    layout = {}; layout_ok = True; layout_notes = []
    for name in contracts_before:
        if name not in contracts_after:
            layout_ok = False; layout_notes.append('Contract removed: ' + name); continue
        old_layout = storage_layout(before, name); new_layout = storage_layout(after, name)
        prefix = new_layout[:len(old_layout)]
        strip = lambda rows: [{k: r[k] for k in ('label', 'slot', 'offset')} | {'type': re.sub(r'\)\d+_', ')_', r['type'])} for r in rows]
        if strip(prefix) != strip(old_layout):
            layout_ok = False; layout_notes.append('Storage layout of existing variables changed in ' + name)
        layout[name] = {'before': old_layout, 'after': new_layout}
    new_addresses = sorted(set(ADDRESS.findall(after)) - set(ADDRESS.findall(before)))
    return {'changed_members': changed, 'added_members': added, 'removed_members': removed,
            'changed_lines': delta, 'storage_layout_preserved': layout_ok, 'storage_notes': layout_notes,
            'storage_layout': layout, 'new_address_literals': new_addresses}


def requirement_delta(before, after, declared):
    strip = lambda r: {k: v for k, v in r.items() if k != 'origin'}
    old = {r['id']: strip(r) for r in before['requirements']}
    new = {r['id']: strip(r) for r in after['requirements']}
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k] != new[k])
    added = sorted(set(new) - set(old))
    declared_ids = {d['requirement_id'] for d in declared}
    undeclared = sorted(set(removed + changed) - declared_ids)
    return {'removed': removed, 'changed': changed, 'added': added, 'declared': declared,
            'undeclared_removals_or_changes': undeclared}


def mechanical(challenge, candidate, finding, output, options):
    """Run every floor; never short-circuit so reviewers see all results."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    replay_fn = options.get('replay', chain_replay)
    current = challenge.version_files(challenge.current)
    snapshot, policy = candidate['snapshot'], candidate['policy']
    result = {'candidate_digest': candidate['digest'], 'failures': [], 'checks': {}}
    fail = lambda reason: result['failures'].append(reason)
    try:
        policy_check(snapshot, policy)
    except ValueError as error:
        fail('Candidate policy invalid: ' + str(error)); write(output / 'gate.json', result); return result

    before = current['snapshot']['material']['input']['contract_source']
    after = snapshot['material']['input']['contract_source']
    try:
        metrics = contract_metrics(before, after); result['checks']['contract'] = metrics
        if not metrics['storage_layout_preserved']: fail('; '.join(metrics['storage_notes']))
        if metrics['new_address_literals']: fail('New address literals introduced: ' + ', '.join(metrics['new_address_literals']))
    except ValueError as error:
        fail('Candidate contract does not compile: ' + str(error))
        write(output / 'gate.json', result); return result

    delta = requirement_delta(current['policy'], policy, candidate['removed_or_relaxed'])
    result['checks']['requirements'] = delta
    if delta['undeclared_removals_or_changes']:
        fail('Undeclared requirement removal or change: ' + ', '.join(delta['undeclared_removals_or_changes']))
    if finding['judgment']['verdict'] != 'spec_defect' and (delta['removed'] or delta['changed']):
        fail('Only a spec_defect verdict may remove or change existing requirements')
    new_req = finding.get('new_requirement')
    if new_req and new_req['id'] not in {r['id'] for r in policy['requirements']}:
        fail('Candidate omits the judge requirement ' + new_req['id'])

    # 3. The triggering case is fixed on the candidate.
    trigger = finding['contribution']['trace']
    trigger_probes = policy['probes']
    replayed = replay_fn(snapshot['material']['input'], policy['environment'], trigger, output / 'trigger', trigger_probes)
    verdict = finding['judgment']['verdict']
    trigger_row = {'replay_status': replayed['status']}
    if replayed['status'] != 'replayed':
        fail('Triggering trace replay inconclusive: ' + str(replayed.get('reason')))
    else:
        checks = requirement_checks(policy, replayed)
        trigger_row['checks'] = {k: v['status'] for k, v in checks.items()}
        if verdict == 'blocked_legitimate' or finding['contribution']['kind'] == 'blocked_legitimate':
            statuses = [t['status'] for t in replayed['transactions']]
            blocked = [i for i in finding['contribution']['expected_success_actions'] if statuses[i] != 'success']
            trigger_row['blocked_actions'] = blocked
            if blocked: fail('Legitimate actions still revert: ' + ', '.join(map(str, blocked)))
        violated = sorted(k for k, v in checks.items() if v['status'] != 'not_demonstrated')
        if violated: fail('Triggering trace still violates: ' + ', '.join(violated))
        # Old requirements the finding violated must stay fixed even if relaxed (unless spec_defect).
        if verdict != 'spec_defect':
            for item in finding.get('violated', []):
                requirement = item['requirement']
                original = replay_fn(snapshot['material']['input'], policy['environment'], trigger,
                                     output / ('trigger-original-' + requirement['id']), item['probes'])
                state = blocked_is_safe(assess(requirement, original))['status'] if original['status'] == 'replayed' else 'inconclusive'
                trigger_row['original_' + requirement['id']] = state
                if state != 'not_demonstrated': fail('Triggering trace still violates original ' + requirement['id'])
    result['checks']['trigger'] = trigger_row

    # 4-5. Regression floor.
    rows = []
    for case in challenge.cases():
        row = run_case(case['material'], snapshot, policy, output / 'cases' / case['id'][:16], replay_fn)
        row = {'case_id': case['id'], 'kind': case['material']['kind'], **{k: v for k, v in row.items() if k != 'replay'}}
        rows.append(row)
        if row['status'] != 'passed': fail('Regression ' + case['id'][:12] + ' (' + case['material']['kind'] + ') failed: ' + str(row.get('reason')))
    result['checks']['regressions'] = rows

    # 7. Lean compiles.
    if options.get('lean', 'docker') == 'docker':
        lean = lean_compile(snapshot, output / 'lean'); result['checks']['lean'] = lean
        if lean['status'] != 'compiled': fail(lean['reason'])
    else:
        result['checks']['lean'] = {'status': 'not_run', 'reason': 'Lean compile disabled by configuration'}

    # 8. Model/EVM divergence must not increase on the recorded traces.
    if options.get('differential', 'docker') == 'docker' and policy.get('model_map') is not None:
        traces = [('trigger', trigger, replayed)]
        for case in challenge.cases():
            probes = policy['probes']
            again = replay_fn(snapshot['material']['input'], policy['environment'], case['material']['trace'],
                              output / 'diff-replays' / case['id'][:16], probes)
            traces.append((case['id'][:16], case['material']['trace'], again))
        new_report = differential.compare(snapshot, policy, traces, output / 'differential-candidate')
        result['checks']['differential'] = {'candidate': summary(new_report)}
        if current['policy'].get('model_map') is not None:
            old_traces = []
            for name, trace, _ in traces:
                again = replay_fn(current['snapshot']['material']['input'], current['policy']['environment'], trace,
                                  output / 'diff-replays-current' / name, current['policy']['probes'])
                old_traces.append((name, trace, again))
            old_report = differential.compare(current['snapshot'], current['policy'], old_traces, output / 'differential-current')
            result['checks']['differential']['current'] = summary(old_report)
            if new_report['status'] == 'inconclusive':
                fail('Differential check inconclusive: ' + str(new_report.get('reason')))
            elif old_report['status'] not in ('inconclusive', 'not_run') and new_report['divergences'] > old_report['divergences']:
                fail('Model/EVM divergences increased from %d to %d' % (old_report['divergences'], new_report['divergences']))
    else:
        result['checks']['differential'] = {'status': 'not_run'}

    result['checks']['diff'] = version_diff(current['snapshot'], current['policy'], snapshot, policy)
    result['status'] = 'passed' if not result['failures'] else 'failed'
    write(output / 'gate.json', result)
    return result


def summary(report):
    return {'status': report['status'], 'divergences': report.get('divergences', 0),
            'modeled_traces': report.get('modeled_traces', 0),
            'details': [{'name': t['name'], 'status': t['status'], 'divergences': t.get('divergences', []),
                         'reason': t.get('reason')} for t in report.get('traces', [])]}


def review_payload(challenge, candidate, finding, gate_result):
    current = challenge.version_files(challenge.current)
    return {'intent': current['snapshot']['material']['input']['intent'],
            'approved_assumptions': current['snapshot']['material']['input'].get('approved_assumptions', []),
            'threat_model': challenge.meta['threat_model'],
            'accepted_finding': {'verdict': finding['judgment']['verdict'],
                                 'root_cause_key': finding['judgment']['root_cause_key'],
                                 'judge_reasoning': finding['judgment']['reasoning'],
                                 'ambiguity_choice': finding['judgment']['ambiguity_choice'],
                                 'new_requirement': finding.get('new_requirement')},
            'current_contract_source': current['snapshot']['material']['input']['contract_source'],
            'candidate_contract_source': candidate['snapshot']['material']['input']['contract_source'],
            'diff': gate_result['checks'].get('diff'),
            'removed_or_relaxed': candidate['removed_or_relaxed'],
            'change_summary': candidate['change_summary'],
            'mechanical_gate': {k: v for k, v in gate_result['checks'].items() if k != 'diff'},
            'mechanical_failures': gate_result['failures'],
            'reviewed_candidate_digest': candidate['digest']}


def validate_review(review, candidate):
    if not isinstance(review, dict) or set(review) != {'reviewed_candidate_digest', 'verdict', 'weakening_found',
                                                       'unrelated_changes', 'over_restrictive', 'reasons'}:
        raise ValueError('Invalid repair review fields')
    if review['reviewed_candidate_digest'] != candidate['digest']: raise ValueError('Review addresses a different candidate')
    if review['verdict'] not in ('approve', 'reject'): raise ValueError('Invalid review verdict')
    if not isinstance(review['reasons'], str) or not review['reasons'].strip(): raise ValueError('Review needs reasons')
    for key in ('weakening_found', 'unrelated_changes', 'over_restrictive'):
        if type(review[key]) is not bool: raise ValueError('Invalid review flag')
    approved = review['verdict'] == 'approve' and not (review['weakening_found'] or review['unrelated_changes'] or review['over_restrictive'])
    return dict(review, approved=approved)


def reviews(challenge, candidate, finding, gate_result, roles, output):
    """D-5 judge-family weakening review + D-15 independent different-family review."""
    payload = review_payload(challenge, candidate, finding, gate_result)
    rows = {}
    for role in ('repair_review_judge', 'repair_review'):
        try:
            rows[role] = validate_review(roles(role, payload, Path(output) / role), candidate)
        except (ValueError, RuntimeError) as error:
            rows[role] = {'approved': False, 'verdict': 'invalid', 'reasons': str(error)}
    write(Path(output) / 'reviews.json', rows)
    return rows
