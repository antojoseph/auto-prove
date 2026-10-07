"""One attack/revision loop, with distinct interpretation and proof evidence."""
from __future__ import annotations
import copy
import html
import json
from pathlib import Path
from app import invoke_agent
from .backend import verify
from .core import (freeze, theorem_source, counterexample_snapshot, observation_snapshot,
                   review_check, write, validate_input, specification, proof_term)
from .evm import replay


def unchecked(snapshot):
    return {'status':'not_run', 'kernel_checked':False, 'target_matched':False,
            'target_digest':snapshot['digest'], 'independent_kernels':[],
            'contract_correspondence':'not_proved'}


def check(snapshot, source, output, skip=False):
    if skip:
        result = unchecked(snapshot); write(Path(output)/'result.json', result); return result
    return verify(snapshot, source, output)


def evidence(snapshot, finding, output, skip=False):
    mode = finding['evidence_kind']
    if mode == 'reasoning_only':
        return {'status':'unconfirmed', 'meaning':'Reasoning only; no independently checked attack'}
    if mode == 'model_counterexample':
        target = counterexample_snapshot(snapshot, finding['property_id'])
        name = finding['property_id']
    else:
        target = observation_snapshot(snapshot, finding)
        name = 'Observation'
    try:
        term = proof_term(finding['proof'], target['material']['specification']['properties'][0]['statement'])
    except ValueError as error:
        return {'status':'inconclusive', 'kernel_checked':False, 'reason':str(error)}
    proofs = {name:term}
    result = check(target, theorem_source(target['material']['specification'], proofs), output, skip)
    if result['status'] == 'proved':
        result['status'] = 'supported_model_counterexample' if mode == 'model_counterexample' else 'supported_model_observation'
    result['evidence_scope'] = 'generated Lean model; Solidity/EVM transaction NOT replayed'
    result['intent_connection'] = 'fallible adversary interpretation; creator review pending'
    result['proof_format'] = 'standard one-theorem file unwrapped against exact target' if term != finding['proof'] else 'term'
    return result


def changes(previous, current):
    if previous is None: return []
    old = {p['id']:p for p in previous['material']['specification']['properties']}
    new = {p['id']:p for p in current['material']['specification']['properties']}
    result = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            result.append({'id':key, 'before':old.get(key), 'after':new.get(key),
                           'review_status':'pending; changed meaning must not be treated as a repaired proof'})
    return result


def render_report(output, report):
    write(Path(output)/'report.json', report)
    rows = []
    for row in report['rounds']:
        proof = row.get('proof_check', {}).get('status', 'not_run')
        findings = row.get('findings', [])
        rows.append('<article><h2>Round ' + str(row['number']) + '</h2><p>Formal proof: <b>' + html.escape(proof) + '</b></p>')
        for finding in findings:
            rows.append('<p><b>' + html.escape(finding['finding']['kind']) + '</b> — ' + html.escape(finding['finding']['reasoning']) + '</p><p>Evidence: ' + html.escape(finding['check']['status']) + '</p>')
            if finding.get('evm_check',{}).get('status') == 'replayed':
                rows.append('<p>Concrete replay: <b>replayed</b>; contract balance: ' + str(finding['evm_check'].get('contract_balance_wei','unknown')) + ' wei. Transaction receipts and view results are in the full evidence below.</p>')
        rows.append('</article>')
    data = html.escape(json.dumps(report, indent=2, ensure_ascii=False))
    page = '''<!doctype html><html><meta charset="utf-8"><title>Auto-prove: general intent pipeline</title>
<style>body{font:17px system-ui;max-width:1050px;margin:40px auto;padding:0 24px;background:#f5f7fb;color:#182438}h1{font-size:32px}article,aside{padding:20px;background:white;border:1px solid #ccd4df;border-radius:12px;margin:20px 0}aside{background:#fff4da}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px monospace}summary{cursor:pointer}</style>
<h1>Contract + intent → specifications → attacks → revision</h1>
<p>A reusable pipeline: the agent generates the model and security requirements for each input. The checker has no contract-family policy switches.</p>
<aside><b>Creator approval: pending. Contract correspondence: not proved.</b><p>Formal proofs and witnesses refer to the generated Lean model. Where enabled, separate replay results record selected Solidity transactions on a disposable local chain. These are not a proof of model/EVM correspondence. Agent agreement does not certify that the specification captures all intended protections.</p></aside>
''' + ''.join(rows) + '<details><summary>Full inputs, specifications, evidence and revision history</summary><pre>' + data + '</pre></details></html>'
    (Path(output)/'report.html').write_text(page)


def run(data, output, rounds=2, model=None, timeout=300, candidate=None, skip=False,
        agent=invoke_agent, evm=False, attack_registry=None):
    data = validate_input(data); output = Path(output)
    if output.exists(): raise ValueError('Use a new output directory to preserve evidence')
    if not 1 <= rounds <= 3: raise ValueError('Use 1-3 bounded rounds')
    if attack_registry and not evm: raise ValueError('Accepted transaction regressions require --evm')
    output.mkdir(parents=True)
    write(output/'input.json', data)
    report = {'version':'general-pipeline-v1', 'input':data, 'rounds':[],
              'mode':'live_agents' if candidate is None else 'supplied_candidate_with_live_review',
              'model':model or 'configured_default', 'creator_approval':'pending',
              'contract_correspondence':'not_proved', 'accepted':False,
              'stopping_rule':'bounded rounds or provisional convergence; no automatic certification'}
    if candidate is None:
        print('Generating model and security requirements from source + intent', flush=True)
        candidate = agent('general_proposer', {'input':data}, output/'agent-initial', timeout, model=model)
    previous = None; prior_attacks = []; history = []
    for number in range(1, rounds+1):
        folder = output/('round-' + str(number)); folder.mkdir()
        write(folder/'candidate.json', candidate)
        spec = specification(candidate)
        row = {'number':number, 'candidate':candidate, 'findings':[]}
        report['rounds'].append(row)
        if spec['status'] == 'unsupported':
            row['status'] = 'unsupported'; render_report(output, report); break
        snapshot = freeze(data, candidate); write(folder/'snapshot.json', snapshot)
        row['snapshot_digest'] = snapshot['digest']; row['property_changes'] = changes(previous, snapshot)
        if attack_registry:
            from .attacks import regress
            row['transaction_regressions'] = regress(snapshot, attack_registry, folder/'transaction-regressions')
        print('Round ' + str(number) + ': checking frozen target and proof attempts', flush=True)
        proofs = {p['id']:p['proof'] for p in candidate['properties']}
        source = theorem_source(spec, proofs); (folder/'Solution.lean').write_text(source)
        proof_check = check(snapshot, source, folder/'proof', skip); row['proof_check'] = proof_check
        diagnostics = {}
        for path in (folder/'proof').glob('*.log'):
            diagnostics[path.name] = path.read_text()[-12000:]
        print('Round ' + str(number) + ': independent attack review', flush=True)
        review = agent('general_reviewer', {'input':data, 'snapshot':snapshot,
                       'proof_status':proof_check, 'diagnostics':diagnostics, 'history':history,
                       'transaction_regressions':row.get('transaction_regressions')},
                       folder/'adversary', timeout, model=model)
        review_check(snapshot, review); write(folder/'review.json', review); row['review'] = review
        for i, finding in enumerate(review['findings']):
            checked = evidence(snapshot, finding, folder/('finding-' + str(i+1)), skip)
            replayed = replay(data, finding['evm_trace'], folder/('replay-' + str(i+1))) if evm and finding.get('evm_trace') else {'status':'not_run'}
            row['findings'].append({'finding':finding, 'check':checked, 'evm_check':replayed})
            if checked['status'].startswith('supported_model'):
                prior_attacks.append({'from_round':number, 'finding':finding,
                                     'original_statement':next((p['statement'] for p in spec['properties'] if p['id'] == finding['property_id']), None)})
        # Replay earlier model observations on revised definitions. Preserve the
        # original proposition, even when the proposer has weakened a target.
        row['earlier_attack_replays'] = []
        for i, attack in enumerate(prior_attacks):
            if attack['from_round'] == number: continue
            finding = copy.deepcopy(attack['finding'])
            if finding['evidence_kind'] == 'model_counterexample':
                finding['evidence_kind'] = 'model_observation'
                finding['observation_statement'] = '¬ (' + attack['original_statement'] + ')'
            replay = evidence(snapshot, finding, folder/('regression-' + str(i+1)), skip)
            row['earlier_attack_replays'].append({'from_round':attack['from_round'], 'finding':finding, 'check':replay})
        row['status'] = 'needs_review' if review['findings'] else 'provisionally_reviewed'
        history.append({'round':number, 'specification':spec, 'proof_status':proof_check,
                        'findings':row['findings'], 'property_changes':row['property_changes'],
                        'earlier_attack_replays':row['earlier_attack_replays'],
                        'transaction_regressions':row.get('transaction_regressions')})
        render_report(output, report)
        if not review['findings'] and proof_check['status'] == 'proved' and row.get('transaction_regressions', {}).get('status', 'passed_replay') == 'passed_replay': break
        if number < rounds:
            print('Revising using checked evidence and separately labelled objections', flush=True)
            candidate = agent('general_proposer', {'input':data, 'previous_candidate':candidate,
                              'history':history, 'diagnostics':diagnostics},
                              folder/'agent-revision', timeout, model=model)
        previous = snapshot
    print('Report: ' + str(output.resolve()/'report.html'), flush=True)
    return report
