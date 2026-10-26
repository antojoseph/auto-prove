"""Versioned automatic challenge: policy v2, regression cases, ledger and versions.

A challenge directory is backend-owned state. Submissions never supply it.

    challenge.json          identity, current version, threat model, model roles
    versions/NNNN/          frozen snapshot, policy, decision record, diffs
    cases/<id>.json         append-only regression cases (must_fail / must_succeed)
    ledger.jsonl            append-only credit records
    events.jsonl            append-only processing outcomes (quiet-period metric)
    snapshot.json, policy.json, CHALLENGE.md   published copies of the current version

Automatic decisions count as approval (design decision D-7): a version adopted
by the judge, the independent reviewer and the mechanical gate is recorded as
``approval: approved_automatically``. That is a governance label. It is not a
proof that English intent is captured, and contract/model correspondence is
still ``not_proved``.
"""
from __future__ import annotations
import copy
import difflib
import json
import time
from pathlib import Path
from .attacks import assess, expression
from .chain import validate_environment, validate_probe, validate_trace, TRACE_VERSION
from .core import digest, freeze, identifier, read, text, validate_snapshot, write

POLICY_VERSION = 'transaction-policy-v2'
CHALLENGE_VERSION = 'auto-challenge-v1'
CASE_VERSION = 'auto-case-v1'
CONTRIBUTION_VERSION = 'transaction-contribution-v2'
APPROVAL = 'approved_automatically'
CREDIT_WEIGHTS = {'new_root_cause': 1.0, 'weakening_found': 2.0, 'legit_action_blocked': 1.0,
                  'lean_refutation': 5.0, 'reproduction': 0.25}
MAX_REPRODUCTIONS = 2
DEFAULT_THREAT_MODEL = {
    'in_scope': ['Any externally owned account may call any public function, in any order, with any arguments.',
                 'Participants may deploy attacker contracts, including contracts with callbacks, reentrancy, '
                 'reverting receivers and self-destruct force-sends of ether.',
                 'Time may advance forward between transactions.'],
    'out_of_scope': ['Reordering or front-running other users\' transactions; sandwich attacks.',
                     'Flash-loan-scale capital or external protocols not deployed in the challenge environment.',
                     'Compiler, EVM, consensus or validator misbehaviour.']}


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def seconds_since(stamp):
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc) - datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)).total_seconds()


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Invalid ' + label + ' fields')


# ---------------------------------------------------------------------------
# Operational policy v2

def validate_requirement(requirement, labels, intent, properties):
    fields(requirement, 'id scope property_id requirement intent_quote step_scope predicate origin', 'requirement')
    identifier(requirement['id']); text(requirement['requirement'], 'English requirement')
    text(requirement['intent_quote'], 'intent quotation')
    if requirement['intent_quote'] not in intent: raise ValueError('Requirement quotation is absent from creator intent: ' + requirement['id'])
    if requirement['scope'] not in ('spec', 'intent'): raise ValueError('Invalid requirement scope')
    if requirement['scope'] == 'spec':
        if requirement['property_id'] not in properties: raise ValueError('Requirement references an absent Lean property')
    elif requirement['property_id'] != '': raise ValueError('An intent requirement must not claim a Lean target')
    scope = requirement['step_scope']
    if not isinstance(scope, str) or (scope not in ('each', 'final') and not scope.startswith('after:')) or scope == 'after:':
        raise ValueError('Invalid predicate step scope')
    expression(requirement['predicate'], labels)
    origin = requirement['origin']
    fields(origin, 'version source rationale', 'requirement origin')
    if type(origin['version']) is not int or origin['version'] < 1: raise ValueError('Invalid requirement origin version')
    if origin['source'] not in ('open', 'judge', 'repair', 'migrated'): raise ValueError('Invalid requirement origin source')
    text(origin['rationale'], 'requirement rationale')
    return requirement


def policy_check(snapshot, policy):
    validate_snapshot(snapshot)
    fields(policy, 'version snapshot_digest environment probes requirements model_map', 'policy')
    if policy['version'] != POLICY_VERSION or policy['snapshot_digest'] != snapshot['digest']:
        raise ValueError('Policy addresses a different snapshot')
    validate_environment(policy['environment'])
    names = {d['name'] for d in policy['environment']['deployments']}
    probes = policy['probes']
    if not isinstance(probes, list) or not 1 <= len(probes) <= 30: raise ValueError('Need 1-30 trusted probes')
    labels = [validate_probe(p, names) for p in probes]
    if len(labels) != len(set(labels)): raise ValueError('Duplicate trusted probe label')
    requirements = policy['requirements']
    if not isinstance(requirements, list) or not 1 <= len(requirements) <= 40: raise ValueError('Need 1-40 requirements')
    material = snapshot['material']
    props = {p['id'] for p in material['specification']['properties']}
    ids = [validate_requirement(r, set(labels), material['input']['intent'], props)['id'] for r in requirements]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate requirement ID')
    if policy['model_map'] is not None:
        from .differential import validate_model_map
        validate_model_map(policy['model_map'], snapshot, set(labels))
    return copy.deepcopy(policy)


def requirement_checks(policy, replayed, requirements=None):
    rows = {}
    for requirement in (policy['requirements'] if requirements is None else requirements):
        rows[requirement['id']] = blocked_is_safe(assess(requirement, replayed))
    return rows


def blocked_is_safe(assessment):
    # A step-scoped predicate whose action never succeeded cannot be violated.
    if assessment.get('reason') == 'No successful matching action to check':
        return {'status': 'not_demonstrated', 'violations': [], 'reason': assessment['reason']}
    return assessment


# ---------------------------------------------------------------------------
# Contributions (submission data)

def contribution_check(challenge, contribution):
    fields(contribution, 'version challenge_version snapshot_digest policy_digest contributor contributor_model kind '
           'requirement_ref claim expected_success_actions reproduces trace', 'contribution')
    if contribution['version'] != CONTRIBUTION_VERSION: raise ValueError('Unknown contribution version')
    text(contribution['contributor'], 'contributor attribution'); text(contribution['contributor_model'], 'contributor model')
    text(contribution['claim'], 'contribution claim')
    if contribution['kind'] not in ('attack', 'blocked_legitimate', 'reproduction'): raise ValueError('Unknown contribution kind')
    if type(contribution['challenge_version']) is not int: raise ValueError('Invalid challenge version')
    ref = contribution['requirement_ref']
    if ref is not None:
        fields(ref, 'version requirement_id', 'requirement reference')
        if type(ref['version']) is not int or not 1 <= ref['version'] <= challenge.current: raise ValueError('Unknown referenced version')
        identifier(ref['requirement_id'])
        if ref['requirement_id'] not in {r['id'] for r in challenge.policy(ref['version'])['requirements']}:
            raise ValueError('Referenced requirement does not exist in that version')
    actions = contribution['expected_success_actions']
    if not isinstance(actions, list) or len(actions) > 30 or any(type(i) is not int for i in actions) or len(set(actions)) != len(actions):
        raise ValueError('Invalid expected success actions')
    if contribution['kind'] == 'blocked_legitimate':
        if not actions or ref is not None: raise ValueError('A blocked-legitimate case lists the actions that must succeed and no requirement')
    elif actions: raise ValueError('Only blocked-legitimate cases list expected successes')
    if contribution['kind'] == 'reproduction':
        if not isinstance(contribution['reproduces'], str) or not challenge.case_path(contribution['reproduces']).exists():
            raise ValueError('Reproduction must name an accepted case')
    elif contribution['reproduces'] != '': raise ValueError('Only reproductions name a case')
    policy = challenge.policy(challenge.current)
    validate_trace(contribution['trace'], policy['environment'])
    if any(i < 0 or i >= len(contribution['trace']['actions']) for i in actions):
        raise ValueError('Expected success action index outside the trace')
    return copy.deepcopy(contribution)


def bind_check(challenge, contribution, submitted_at=None):
    """D-23 stale rejection, D-27 rebase of submissions queued while versions shipped."""
    target = contribution['challenge_version']
    current = challenge.current
    if target == current:
        expected = challenge.version_files(current)
        if contribution['snapshot_digest'] != expected['snapshot']['digest'] or contribution['policy_digest'] != digest(expected['policy']):
            raise ValueError('Contribution digests do not match its challenge version')
        return {'bound_version': current, 'rebased_from': None}
    if not 1 <= target < current: raise ValueError('Contribution targets an unknown challenge version')
    old = challenge.version_files(target)
    if contribution['snapshot_digest'] != old['snapshot']['digest'] or contribution['policy_digest'] != digest(old['policy']):
        raise ValueError('Contribution digests do not match its challenge version')
    if submitted_at is None: raise ValueError('Stale contribution: sync to version ' + str(current) + ' and resubmit')
    shipped = [challenge.record(v)['created_at'] for v in range(target + 1, current + 1)]
    if all(created > submitted_at for created in shipped):
        return {'bound_version': current, 'rebased_from': target}
    raise ValueError('Stale contribution: sync to version ' + str(current) + ' and resubmit')


# ---------------------------------------------------------------------------
# Regression cases

def case_material(kind, trace, requirement=None, probes=None, expected=None):
    if kind == 'must_fail':
        return {'kind': kind, 'trace': trace, 'requirement': requirement, 'probes': probes}
    return {'kind': kind, 'trace': trace, 'expected_success_actions': sorted(expected)}


def run_case(case_material_value, snapshot, policy, output, replay_fn):
    """Replay one regression case on a candidate version; pass/fail plus evidence."""
    m = case_material_value
    probes = m['probes'] if m['kind'] == 'must_fail' else policy['probes']
    try:
        validate_trace(m['trace'], policy['environment'])
    except ValueError as error:
        return {'status': 'failed', 'reason': 'Case trace no longer fits the environment: ' + str(error)}
    replayed = replay_fn(snapshot['material']['input'], policy['environment'], m['trace'], output, probes)
    if replayed['status'] != 'replayed':
        return {'status': 'failed', 'reason': 'Replay inconclusive: ' + str(replayed.get('reason')), 'replay': replayed}
    if m['kind'] == 'must_fail':
        check = blocked_is_safe(assess(m['requirement'], replayed))
        ok = check['status'] == 'not_demonstrated'
        return {'status': 'passed' if ok else 'failed', 'check': check, 'replay_digest': digest(replayed),
                'reason': None if ok else 'Accepted attack still violates ' + m['requirement']['id']}
    statuses = [t['status'] for t in replayed['transactions']]
    blocked = [i for i in m['expected_success_actions'] if statuses[i] != 'success']
    checks = requirement_checks(policy, replayed)
    violated = sorted(k for k, v in checks.items() if v['status'] != 'not_demonstrated')
    ok = not blocked and not violated
    reason = None
    if blocked: reason = 'Legitimate actions reverted: ' + ', '.join(map(str, blocked))
    elif violated: reason = 'Legitimate behaviour violates requirement(s): ' + ', '.join(violated)
    return {'status': 'passed' if ok else 'failed', 'blocked_actions': blocked, 'violated_requirements': violated,
            'checks': {k: v['status'] for k, v in checks.items()}, 'replay_digest': digest(replayed), 'reason': reason}


# ---------------------------------------------------------------------------
# Diffs (published per version, D-17)

def text_diff(before, after, name):
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        fromfile='before/' + name, tofile='after/' + name))


def keyed_changes(before, after):
    old = {x['id']: x for x in before}; new = {x['id']: x for x in after}
    rows = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) == new.get(key): continue
        state = 'added' if key not in old else 'removed' if key not in new else 'changed'
        rows.append({'id': key, 'change': state, 'before': old.get(key), 'after': new.get(key)})
    return rows


def version_diff(before_snapshot, before_policy, after_snapshot, after_policy):
    b = before_snapshot['material']; a = after_snapshot['material']
    return {'contract_diff': text_diff(b['input']['contract_source'], a['input']['contract_source'], 'Contract.sol'),
            'model_diff': text_diff(b['specification']['model_body'], a['specification']['model_body'], 'Model.lean'),
            'property_changes': keyed_changes(b['specification']['properties'], a['specification']['properties']),
            'requirement_changes': keyed_changes(_strip_origin(before_policy['requirements']),
                                                 _strip_origin(after_policy['requirements'])),
            'probe_changes': keyed_changes([dict(p, id=p['label']) for p in before_policy['probes']],
                                           [dict(p, id=p['label']) for p in after_policy['probes']]),
            'environment_changed': before_policy['environment'] != after_policy['environment']}


def _strip_origin(requirements):
    return [{k: v for k, v in r.items() if k != 'origin'} for r in requirements]


def diff_markdown(diff, title):
    lines = ['# ' + title, '']
    for label, key in (('Contract', 'contract_diff'), ('Lean model', 'model_diff')):
        lines += ['## ' + label, '', '```diff', diff[key] or '(unchanged)', '```', '']
    for label, key in (('Formal properties', 'property_changes'), ('Operational requirements', 'requirement_changes'),
                       ('Trusted probes', 'probe_changes')):
        lines += ['## ' + label, '']
        if not diff[key]: lines.append('(unchanged)')
        for row in diff[key]:
            lines.append('- **' + row['id'] + '** ' + row['change'])
            if row['change'] != 'added': lines.append('  - before: `' + json.dumps(row['before'], ensure_ascii=False) + '`')
            if row['change'] != 'removed': lines.append('  - after: `' + json.dumps(row['after'], ensure_ascii=False) + '`')
        lines.append('')
    lines += ['Environment changed: ' + str(diff['environment_changed']), '']
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Store

class Challenge:
    def __init__(self, root):
        self.root = Path(root)
        self.meta = read(self.root / 'challenge.json')
        if self.meta.get('version') != CHALLENGE_VERSION: raise ValueError('Not an automatic challenge directory')

    @property
    def current(self):
        return self.meta['current']

    def folder(self, version):
        return self.root / 'versions' / ('%04d' % version)

    def version_files(self, version):
        folder = self.folder(version)
        snapshot = validate_snapshot(read(folder / 'snapshot.json'))
        policy = policy_check(snapshot, read(folder / 'policy.json'))
        return {'snapshot': snapshot, 'policy': policy}

    def snapshot(self, version): return self.version_files(version)['snapshot']
    def policy(self, version): return read(self.folder(version) / 'policy.json')
    def record(self, version): return read(self.folder(version) / 'record.json')

    def case_path(self, case_id):
        if not isinstance(case_id, str) or len(case_id) != 64 or set(case_id) - set('0123456789abcdef'):
            raise ValueError('Invalid case identifier')
        return self.root / 'cases' / (case_id + '.json')

    def cases(self):
        rows = []
        for path in sorted((self.root / 'cases').glob('*.json')):
            case = read(path)
            if case.get('version') != CASE_VERSION or case.get('id') != digest(case['material']) or path.stem != case['id']:
                raise ValueError('Corrupt regression case ' + path.name)
            rows.append(case)
        return rows

    def add_case(self, material, origin):
        case_id = digest(material); path = self.case_path(case_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = read(path)
            if existing['material'] != material: raise ValueError('Regression case identity mismatch')
            existing.setdefault('additional_origins', []).append(origin)
            write(path, existing)
            return case_id, 'duplicate'
        write(path, {'version': CASE_VERSION, 'id': case_id, 'material': material, 'origin': origin})
        return case_id, 'added'

    def ledger(self):
        path = self.root / 'ledger.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

    def events(self):
        path = self.root / 'events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

    def append(self, name, entry):
        with (self.root / name).open('a') as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + '\n')

    def credit(self, entry):
        if entry['class'] not in CREDIT_WEIGHTS: raise ValueError('Unknown credit class')
        entry = dict(entry, weight=CREDIT_WEIGHTS[entry['class']], entry=len(self.ledger()) + 1, time=now())
        self.append('ledger.jsonl', entry)
        return entry

    def credited_keys(self):
        return {e['key'] for e in self.ledger()}

    def reproductions(self, case_id):
        return [e for e in self.ledger() if e['class'] == 'reproduction' and e['key'].startswith('reproduction:' + case_id)]

    def all_requirements(self):
        """Every requirement ever active, keyed by (version, id), for weakening checks."""
        rows = {}
        for version in range(1, self.current + 1):
            for requirement in self.policy(version)['requirements']:
                rows[(version, requirement['id'])] = requirement
        return rows

    def adopt(self, snapshot, policy, record):
        """Write the next version and publish it. Callers have already gated it."""
        policy_check(snapshot, policy)
        version = self.current + 1
        if record['challenge_version'] != version: raise ValueError('Decision record addresses a different version')
        folder = self.folder(version)
        folder.mkdir(parents=True, exist_ok=False)
        previous = self.version_files(self.current) if self.current else None
        write(folder / 'snapshot.json', snapshot); write(folder / 'policy.json', policy)
        (folder / 'Contract.sol').write_text(snapshot['material']['input']['contract_source'])
        record = dict(record, snapshot_digest=snapshot['digest'], policy_digest=digest(policy), created_at=now(),
                      approval=APPROVAL, contract_correspondence='not_proved')
        if previous:
            diff = version_diff(previous['snapshot'], previous['policy'], snapshot, policy)
            write(folder / 'diff.json', diff)
            (folder / 'diff.md').write_text(diff_markdown(diff, 'Version %d → %d' % (self.current, version)))
            first = self.version_files(1)
            from_origin = version_diff(first['snapshot'], first['policy'], snapshot, policy)
            write(folder / 'diff-from-v1.json', from_origin)
            (folder / 'diff-from-v1.md').write_text(diff_markdown(from_origin, 'Version 1 → %d' % version))
        write(folder / 'record.json', record)
        self.meta['current'] = version
        self.meta['updated_at'] = record['created_at']
        write(self.root / 'challenge.json', self.meta)
        self.publish()
        return version

    def status(self):
        events = self.events()
        positions = [i for i, e in enumerate(events) if e['outcome'] in ('accepted_repaired', 'accepted_repair_pending')]
        last = events[positions[-1]]['time'] if positions else None
        since = len(events) - positions[-1] - 1 if positions else len(events)
        days = round(seconds_since(last) / 86400, 3) if last else None
        return {'current_version': self.current, 'versions': self.current,
                'quiet_period': {'last_accepted_at': last, 'days_since_last_accepted': days,
                                 'submissions_since_last_accepted': since,
                                 'meaning': 'time and submissions without a new accepted finding; never a security guarantee'},
                'pending_repairs': self.meta.get('pending_repairs', []),
                'cases': {'must_fail': sum(c['material']['kind'] == 'must_fail' for c in self.cases()),
                          'must_succeed': sum(c['material']['kind'] == 'must_succeed' for c in self.cases())},
                'credits': len(self.ledger()), 'approval': APPROVAL, 'contract_correspondence': 'not_proved'}

    def publish(self):
        files = self.version_files(self.current)
        write(self.root / 'snapshot.json', files['snapshot']); write(self.root / 'policy.json', files['policy'])
        status = self.status(); write(self.root / 'status.json', status)
        policy = files['policy']; record = self.record(self.current)
        lines = ['# ' + self.meta['id'] + ' — automatic challenge, version ' + str(self.current), '',
                 'Approval: **' + APPROVAL + '** (judge + independent reviewer + mechanical gate). '
                 'Contract/model correspondence: **not proved**. This is not a security certificate.', '',
                 '- Snapshot digest: `' + files['snapshot']['digest'] + '`',
                 '- Policy digest: `' + digest(policy) + '`',
                 '- Quiet period: ' + json.dumps(status['quiet_period']), '',
                 '## Threat model', '']
        lines += ['- in scope: ' + x for x in self.meta['threat_model']['in_scope']]
        lines += ['- out of scope: ' + x for x in self.meta['threat_model']['out_of_scope']]
        lines += ['', '## Current requirements', '']
        for r in policy['requirements']:
            lines.append('- **' + r['id'] + '** (' + r['scope'] + ', from v' + str(r['origin']['version']) + '): ' + r['requirement'])
        lines += ['', '## Version history', '']
        for v in range(1, self.current + 1):
            rec = self.record(v)
            lines.append('- v' + str(v) + ' (' + rec['created_at'] + '): ' + rec['summary'] +
                         (' — [diff](versions/%04d/diff.md)' % v if v > 1 else ''))
        lines += ['', 'Earlier versions and their diffs are published so participants can look for weakened protections '
                  '(weakening found earns credit).', '']
        (self.root / 'CHALLENGE.md').write_text('\n'.join(lines))


def create(root, challenge_id, snapshot, policy, record, threat_model=None, models=None):
    root = Path(root)
    if (root / 'challenge.json').exists(): raise ValueError('Challenge directory already initialized')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'cases').mkdir(exist_ok=True)
    write(root / 'challenge.json', {'version': CHALLENGE_VERSION, 'id': identifier(challenge_id), 'current': 0,
                                    'threat_model': threat_model or DEFAULT_THREAT_MODEL,
                                    'models': models or {}, 'pending_repairs': [], 'created_at': now()})
    challenge = Challenge(root)
    challenge.adopt(snapshot, policy, dict(record, challenge_version=1))
    return challenge


def refreeze(snapshot, contract_source=None, model_body=None, properties=None):
    """Freeze a revised specification/contract with the same intent and assumptions."""
    material = snapshot['material']
    data = copy.deepcopy(material['input'])
    if contract_source is not None: data['contract_source'] = contract_source
    candidate = copy.deepcopy(material['specification'])
    if model_body is not None: candidate['model_body'] = model_body
    if properties is not None: candidate['properties'] = copy.deepcopy(properties)
    for prop in candidate['properties']: prop['proof'] = 'by sorry'
    return freeze(data, candidate)
