"""Proposed operational policies and explicit creator review decisions.

A proposal is a DRAFT operational policy in which every requirement is pending.
The creator sees the English requirement, its intent quotation, the trusted
state probes, the bounded predicate, the snapshot assumptions and any mapped
Lean target before deciding. A recorded decision approves an interpretation
for transaction checking only; it never approves the contract, grants semantic
approval, or proves model/EVM equivalence. Rejected requirements are excluded
from the reviewed operational policy and retained in the review record.
"""
from __future__ import annotations
import copy
import html
import json
from pathlib import Path
from .attacks import fields, policy_check
from .core import digest, text, validate_snapshot, write

PROPOSAL_VERSION = 'policy-proposal-v1'
REVIEW_VERSION = 'policy-review-v1'


def probe_view(probe):
    if probe['kind'] == 'balance': return {'kind':'balance', 'label':probe['label'], 'observes':'contract balance in wei'}
    return {'kind':'view', 'label':probe['label'], 'function':probe['function'], 'arguments':probe['arguments']}


def propose(snapshot, draft, output):
    validate_snapshot(snapshot)
    policy_check(snapshot, draft)
    for requirement in draft['requirements']:
        if requirement['review_status'] != 'pending':
            raise ValueError('A proposed requirement must start pending review')
    spec = snapshot['material']['specification']
    props = {p['id']:p for p in spec['properties']}
    items = []
    for requirement in draft['requirements']:
        if requirement['scope'] == 'spec':
            prop = props[requirement['property_id']]
            mapping = {'property_id':prop['id'], 'statement':prop['statement'],
                       'formal_mapping':prop['explanation'], 'intent_basis':prop['intent_basis']}
        else:
            mapping = None
        items.append({'requirement_id':requirement['id'], 'scope':requirement['scope'],
                      'english_requirement':requirement['requirement'],
                      'intent_quote':requirement['intent_quote'],
                      'observed_state_fields':[probe_view(p) for p in draft['probes']],
                      'step_scope':requirement['step_scope'], 'predicate':requirement['predicate'],
                      'lean_mapping':mapping,
                      'unmapped_note':None if mapping else
                      'intent requirement; no Lean target is claimed or checked'})
    packet = {'version':PROPOSAL_VERSION, 'snapshot_digest':snapshot['digest'],
              'policy_digest':digest(draft), 'proposal':draft, 'review_items':items,
              'snapshot_assumptions':spec['assumptions'],
              'snapshot_unresolved_questions':spec['unresolved_questions'],
              'decision_template':{'version':REVIEW_VERSION, 'snapshot_digest':snapshot['digest'],
                                   'policy_digest':digest(draft), 'creator':'creator name',
                                   'decisions':[{'requirement_id':r['id'], 'decision':'approved or rejected',
                                                 'reason':'why this interpretation is or is not the intended protection'}
                                                for r in draft['requirements']]},
              'meaning':'creator review decides the operational interpretation for transaction checking only; '
                        'it does not approve the contract or prove model/EVM equivalence',
              'creator_approval':'pending', 'accepted':False, 'contract_correspondence':'not_proved'}
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    write(output/'proposal.json', packet)
    render(output, packet)
    return packet


def decisions_check(packet, snapshot, decisions):
    validate_snapshot(snapshot)
    fields(decisions, 'version snapshot_digest policy_digest creator decisions', 'review decisions')
    if decisions['version'] != REVIEW_VERSION: raise ValueError('Unknown review decisions version')
    if decisions['snapshot_digest'] != snapshot['digest'] or decisions['policy_digest'] != packet['policy_digest']:
        raise ValueError('Review decisions address a different proposal')
    text(decisions['creator'], 'reviewing creator')
    proposed = {r['id'] for r in packet['proposal']['requirements']}
    seen = []
    for decision in decisions['decisions']:
        fields(decision, 'requirement_id decision reason', 'requirement decision')
        requirement_id = decision['requirement_id']
        if requirement_id not in proposed: raise ValueError('Decision addresses a requirement outside the proposal')
        if decision['decision'] not in ('approved', 'rejected'): raise ValueError('Invalid requirement decision')
        text(decision['reason'], 'decision reason')
        seen.append(requirement_id)
    if sorted(seen) != sorted(proposed): raise ValueError('Every proposed requirement needs exactly one decision')
    return copy.deepcopy(decisions)


def creator_review(snapshot, packet, decisions, output):
    decisions = decisions_check(packet, snapshot, decisions)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    reviewed = copy.deepcopy(packet['proposal'])
    rows = []
    for requirement in reviewed['requirements']:
        decision = next(d for d in decisions['decisions'] if d['requirement_id'] == requirement['id'])
        requirement['review_status'] = 'approved' if decision['decision'] == 'approved' else 'rejected'
        rows.append({'requirement_id':requirement['id'], 'decision':decision['decision'],
                     'reason':decision['reason']})
    approved = copy.deepcopy(reviewed)
    approved['requirements'] = [r for r in reviewed['requirements'] if r['review_status'] == 'approved']
    # A fully rejected proposal is a valid review outcome; it produces no usable
    # operational policy, so the requirement-bound policy check only applies then.
    usable = bool(approved['requirements'])
    if usable: policy_check(snapshot, approved)
    record = {'version':REVIEW_VERSION, 'snapshot_digest':snapshot['digest'],
              'proposed_policy_digest':packet['policy_digest'], 'reviewed_policy_digest':digest(approved),
              'creator':decisions['creator'], 'decisions':rows,
              'rejected_requirements':[r['id'] for r in reviewed['requirements'] if r['review_status'] == 'rejected'],
              'usable_for_transaction_checking':usable, 'approved_policy':approved,
              'meaning':'an approved operational requirement is a reviewed interpretation for transaction '
                        'checking; it is not contract approval, semantic approval, or a model/EVM equivalence proof',
              'creator_approval':'pending', 'accepted':False, 'contract_correspondence':'not_proved'}
    write(output/'reviewed-policy.json', approved)
    write(output/'review-record.json', record)
    render(output, record)
    return record


def render(output, payload):
    page = '<!doctype html><meta charset="utf-8"><title>Operational policy review</title>'
    page += '<style>body{font:17px system-ui;max-width:1050px;margin:40px auto;padding:24px}pre{font:13px monospace;white-space:pre-wrap;overflow-wrap:anywhere}aside{padding:16px;background:#fff4da}blockquote{border-left:4px solid #ccd4df;margin:8px 0;padding:4px 16px;color:#333f55}</style>'
    page += '<h1>Operational policy: creator review</h1>'
    page += '<aside>Reviewing an operational requirement approves an interpretation for transaction checking only. It does not approve the contract, grant semantic approval, or prove model/EVM equivalence. Rejected requirements cannot be attacked or accepted.</aside>'
    if payload['version'] == PROPOSAL_VERSION:
        page += '<h2>Proposed requirements</h2>'
        for item in payload['review_items']:
            page += '<section><h3>' + html.escape(item['requirement_id']) + '</h3>'
            page += '<p>' + html.escape(item['english_requirement']) + '</p>'
            page += '<blockquote>Intent: ' + html.escape(item['intent_quote']) + '</blockquote>'
            page += '<p>Observed state fields: ' + html.escape(json.dumps(item['observed_state_fields'])) + '</p>'
            page += '<p>Predicate: ' + html.escape(json.dumps(item['predicate'])) + '</p>'
            if item['lean_mapping']:
                page += '<p>Mapped Lean target <b>' + html.escape(item['lean_mapping']['property_id']) + '</b>: <code>' + html.escape(item['lean_mapping']['statement']) + '</code></p>'
            else:
                page += '<p>' + html.escape(item['unmapped_note']) + '</p>'
            page += '</section>'
        page += '<h2>Snapshot assumptions</h2><pre>' + html.escape(json.dumps(payload['snapshot_assumptions'], indent=2)) + '</pre>'
        page += '<h2>Decision template</h2><pre>' + html.escape(json.dumps(payload['decision_template'], indent=2)) + '</pre>'
    else:
        page += '<h2>Recorded creator decisions</h2>'
        for row in payload['decisions']:
            page += '<p><b>' + html.escape(row['requirement_id']) + '</b>: ' + html.escape(row['decision']) + ' — ' + html.escape(row['reason']) + '</p>'
    page += '<h2>Full record</h2><pre>' + html.escape(json.dumps(payload, indent=2, ensure_ascii=False)) + '</pre>'
    (Path(output)/'review.html').write_text(page)
