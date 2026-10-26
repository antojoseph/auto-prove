"""Model <-> EVM differential replay (backlog I-18).

The policy may carry a trusted ``model_map``: how each mapped contract call
transforms the generated Lean model's state, and how each trusted probe reads
that state. Every recorded trace is replayed on Anvil (concrete EVM) and, step
by step, through the Lean model by ``#eval`` inside the network-free verifier
container. Any probe whose Lean value differs from the EVM value is a
divergence: evidence of a model gap, never of a contract defect by itself.

Agreement on the recorded traces is NOT a correspondence proof. It only shows
that the model reproduces these concrete observations.

Templates are single Lean term expressions validated like frozen targets. The
placeholders ``$sender``, ``$value``, ``$time`` and ``$arg0``..``$arg19`` are
substituted with numerals or ``true``/``false`` computed by the runner from
the replayed transaction; ``s`` names the pre-state.
"""
from __future__ import annotations
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from .core import identifier, lean_tokens, text, validate_model, validate_statement, write

IMAGE = 'auto-prove-verifier:lean4.35.0-rc2'
PLACEHOLDER = re.compile(r'\$(sender|value|time|arg(?:1[0-9]|[0-9]))\b')
DEPLOYMENT_BASE = 1000  # challenge/attacker deployment k is modeled as address number 1000+k


def fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Invalid ' + label + ' fields')


def template(value, label):
    text(value, label)
    validate_statement(PLACEHOLDER.sub('0', value))
    if '$' in PLACEHOLDER.sub('', value): raise ValueError('Unknown placeholder in ' + label)
    return value


def validate_model_map(model_map, snapshot, labels):
    fields(model_map, 'state_type initial actions observations', 'model map')
    names = set(validate_model(snapshot['material']['specification']['model_body']))
    if identifier(model_map['state_type']) not in names: raise ValueError('Model map state type is not a model declaration')
    template(model_map['initial'], 'initial state')
    if not isinstance(model_map['actions'], list) or not 1 <= len(model_map['actions']) <= 40:
        raise ValueError('Need 1-40 mapped actions')
    keys = set()
    for row in model_map['actions']:
        fields(row, 'target function term', 'mapped action')
        identifier(row['target'])
        if not isinstance(row['function'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)', row['function']):
            raise ValueError('Invalid mapped function signature')
        template(row['term'], 'mapped action term')
        if (row['target'], row['function']) in keys: raise ValueError('Duplicate mapped action')
        keys.add((row['target'], row['function']))
    if not isinstance(model_map['observations'], list) or not 1 <= len(model_map['observations']) <= 30:
        raise ValueError('Need 1-30 mapped observations')
    seen = set()
    for row in model_map['observations']:
        fields(row, 'probe term', 'mapped observation')
        if row['probe'] not in labels or row['probe'] in seen: raise ValueError('Mapped observation must name a distinct trusted probe')
        seen.add(row['probe']); template(row['term'], 'mapped observation term')
    return model_map


def _numeral(value, accounts, deployments):
    if value in ('true', 'false'): return value
    if value.startswith('$account:'): return str(int(value.split(':', 1)[1]))
    if value.startswith('$deployment:') or value == '$contract':
        name = deployments[0] if value == '$contract' else value.split(':', 1)[1]
        return str(DEPLOYMENT_BASE + deployments.index(name))
    if re.fullmatch(r'[0-9]{1,78}', value): return value
    return None  # strings, negative ints, raw addresses: not modeled


def instantiate(term, action, transaction, deployments):
    args = action['arguments']
    values = {'sender': str(action['account']), 'value': str(int(action['value_wei'])),
              'time': str(transaction.get('timestamp', 0))}
    for i, arg in enumerate(args):
        values['arg' + str(i)] = _numeral(arg, None, deployments)
    missing = []

    def substitute(match):
        value = values.get(match.group(1))
        if value is None: missing.append(match.group(1)); return '0'
        return value
    result = PLACEHOLDER.sub(substitute, term)
    return None if missing else '(' + result + ')'


def lean_program(snapshot, policy, traces):
    """Build one Lean file evaluating every modeled trace. Returns (source, plan)."""
    model_map = policy['model_map']
    actions = {(r['target'], r['function']): r['term'] for r in model_map['actions']}
    observations = model_map['observations']
    state = model_map['state_type']
    lines = ['import Std', 'namespace AutoSpec', snapshot['material']['specification']['model_body'], '']
    plan = []
    for t, (name, trace, replayed) in enumerate(traces):
        deployments = [d['name'] for d in policy['environment']['deployments']] + [d['name'] for d in trace['deployments']]
        row = {'name': name, 'status': 'modeled', 'steps': len(replayed['transactions'])}
        steps = []
        for k, tx in enumerate(replayed['transactions']):
            term = actions.get((tx['action']['target'], tx['action']['function']))
            if term is None:
                row['status'] = 'unmodeled'; row['reason'] = 'Unmapped call ' + tx['action']['target'] + '.' + (tx['action']['function'] or 'fallback'); break
            term = instantiate(term, tx['action'], tx, deployments)
            if term is None:
                row['status'] = 'unmodeled'; row['reason'] = 'Unmappable argument in step ' + str(k + 1); break
            steps.append(term)
        plan.append(row)
        if row['status'] != 'modeled': continue
        prefix = 'autoT%dS' % t
        lines.append('def %s0 : %s := %s' % (prefix, state, model_map['initial']))
        for k, term in enumerate(steps):
            lines.append('def %s%d : %s := (fun (s : %s) => %s) %s%d' % (prefix, k + 1, state, state, term, prefix, k))
        for k in range(len(steps) + 1):
            for obs in observations:
                lines.append('#eval ("AUTOOBS|%d|%d|%s|" ++ toString ((fun (s : %s) => %s) %s%d))'
                             % (t, k, obs['probe'], state, obs['term'], prefix, k))
    lines += ['end AutoSpec', '']
    source = '\n'.join(lines)
    lean_tokens(source)  # rejects unterminated comments/strings introduced by templates
    return source, plan


def run_lean(source, output, timeout=240):
    """Evaluate a generated file with the verifier image's Lean, network-free."""
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    (output / 'Differential.lean').write_text(source)
    if not shutil.which('docker'): return None, 'Docker unavailable'
    with tempfile.TemporaryDirectory(prefix='auto-prove-diff-') as temp:
        root = Path(temp); root.chmod(0o755)
        (root / 'Differential.lean').write_text(source); (root / 'Differential.lean').chmod(0o644)
        name = 'auto-prove-diff-' + uuid.uuid4().hex
        command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                   '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--memory', '2g', '--cpus', '2',
                   '--tmpfs', '/work:rw,size=256m,uid=10001,gid=10001,mode=0700', '--tmpfs', '/tmp:rw,size=64m,mode=1777',
                   '--mount', 'type=bind,source=' + str(root) + ',target=/input,readonly',
                   '--entrypoint', '/opt/lean/bin/lean', IMAGE, '/input/Differential.lean']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, 'Lean evaluation timed out'
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=20)
    (output / 'lean.log').write_text(result.stdout[-200000:] + result.stderr[-50000:])
    if result.returncode: return None, 'Lean evaluation failed; inspect lean.log'
    return result.stdout, None


def compare(snapshot, policy, traces, output, lean=run_lean):
    """traces: list of (name, trace, replayed). Returns divergence report."""
    report = {'status': 'not_run', 'traces': [], 'divergences': 0, 'modeled_traces': 0,
              'meaning': 'agreement on recorded traces only; not a model/EVM correspondence proof'}
    if policy.get('model_map') is None:
        report['reason'] = 'Policy has no model map'; write(Path(output) / 'differential.json', report); return report
    usable = [(n, t, r) for n, t, r in traces if r.get('status') == 'replayed']
    source, plan = lean_program(snapshot, policy, usable)
    modeled = [i for i, row in enumerate(plan) if row['status'] == 'modeled']
    report['traces'] = plan
    if not modeled:
        report['status'] = 'no_modeled_traces'; write(Path(output) / 'differential.json', report); return report
    stdout, failure = lean(source, output)
    if failure:
        report['status'] = 'inconclusive'; report['reason'] = failure
        write(Path(output) / 'differential.json', report); return report
    values = {}
    for line in stdout.splitlines():
        match = re.fullmatch(r'"AUTOOBS\|(\d+)\|(\d+)\|([A-Za-z][A-Za-z0-9_]*)\|(.*)"', line.strip())
        if match: values[(int(match[1]), int(match[2]), match[3])] = match[4]
    for t in modeled:
        name, trace, replayed = usable[t]; row = plan[t]; row['divergences'] = []
        for frame in replayed['frames']:
            for obs in policy['model_map']['observations']:
                evm = frame['values'].get(obs['probe'])
                model = values.get((t, frame['step'], obs['probe']))
                expected = str(evm).lower() if isinstance(evm, bool) else str(evm)
                if model is None:
                    row['divergences'].append({'step': frame['step'], 'probe': obs['probe'], 'evm': evm, 'model': None,
                                               'reason': 'Lean produced no value'})
                elif model != expected:
                    row['divergences'].append({'step': frame['step'], 'probe': obs['probe'], 'evm': evm, 'model': model})
        report['divergences'] += len(row['divergences'])
    report['modeled_traces'] = len(modeled)
    report['status'] = 'agrees_on_recorded_traces' if report['divergences'] == 0 else 'diverges'
    write(Path(output) / 'differential.json', report)
    return report
