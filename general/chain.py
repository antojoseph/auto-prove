"""Multi-contract replay with participant attacker contracts on a disposable Anvil.

Trace v2 extends the v1 runner in ``evm.py``:

- the challenge environment (which challenge contracts are deployed, with which
  constructor arguments, plus trusted setup calls) is owned by the policy, never
  by the submission;
- a submission may add attacker contracts compiled from participant Solidity;
- every action names its target deployment and may advance time forward only;
- trusted probes read view results, contract balances or account balances.

Isolation. Attacker source is compiled with the pinned solc, without an import
callback, under CPU, memory and size limits, in a fresh temporary directory.
Attacker bytecode runs only inside the EVM of a private, unique-chain-ID Anvil
bound to 127.0.0.1. Anvil exposes no cheatcodes to contracts; only this runner
speaks RPC to it. No external RPC endpoint, wallet or network is ever used.
Replay is evidence for selected transactions, not a model/EVM equivalence proof.
"""
from __future__ import annotations
import copy
import json
import os
import re
import resource
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from .core import digest, identifier, write
from .evm import command, decode_scalar, executable

TRACE_VERSION = 'transaction-trace-v2'
SIGNATURE = r'[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)'
MAX_ATTACKER_SOURCE = 64 * 1024
MAX_ACTIONS = 30
MAX_ADVANCE = 10 * 365 * 24 * 3600
GAS_PER_TX = 8_000_000
ACCOUNTS = 10
GENESIS_TIME = 1_700_000_000  # fixed genesis; gas is free so account balances track value only


def _args(values, label='ABI arguments'):
    if not isinstance(values, list) or len(values) > 20 or any(
            not isinstance(v, str) or len(v) > 4096 or v.startswith('-') for v in values):
        raise ValueError('Invalid ' + label)
    return values


def _wei(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value) or int(value) >= 2**256:
        raise ValueError('Invalid wei amount')
    return value


def _account(value):
    if type(value) is not int or not 0 <= value < ACCOUNTS:
        raise ValueError('Invalid local account index')
    return value


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Invalid ' + label + ' fields')


def validate_deployment(deployment):
    _fields(deployment, 'name contract_name constructor_arguments account value_wei', 'deployment')
    identifier(deployment['name']); identifier(deployment['contract_name'])
    _args(deployment['constructor_arguments'], 'constructor arguments')
    _account(deployment['account']); _wei(deployment['value_wei'])
    return deployment


def validate_action(action, targets):
    _fields(action, 'account target function arguments value_wei advance_seconds', 'action')
    _account(action['account'])
    if action['target'] not in targets: raise ValueError('Action targets an unknown deployment')
    if not isinstance(action['function'], str) or (action['function'] and not re.fullmatch(SIGNATURE, action['function'])):
        raise ValueError('Invalid ABI signature')
    _args(action['arguments'])
    if not action['function'] and action['arguments']: raise ValueError('Empty calldata takes no arguments')
    _wei(action['value_wei'])
    if type(action['advance_seconds']) is not int or not 0 <= action['advance_seconds'] <= MAX_ADVANCE:
        raise ValueError('Time may only advance forward by a bounded amount')
    return action


def validate_environment(environment):
    """Trusted challenge environment: deployments plus setup actions."""
    _fields(environment, 'deployments setup', 'environment')
    deployments = environment['deployments']
    if not isinstance(deployments, list) or not 1 <= len(deployments) <= 8:
        raise ValueError('Need 1-8 challenge deployments')
    names = [validate_deployment(d)['name'] for d in deployments]
    if len(names) != len(set(names)): raise ValueError('Duplicate deployment name')
    if not isinstance(environment['setup'], list) or len(environment['setup']) > MAX_ACTIONS:
        raise ValueError('Invalid trusted setup actions')
    for action in environment['setup']: validate_action(action, set(names))
    return environment


def validate_trace(trace, environment):
    _fields(trace, 'version attacker_source deployments actions', 'trace')
    if trace['version'] != TRACE_VERSION: raise ValueError('Unsupported trace version')
    validate_environment(environment)
    source = trace['attacker_source']
    if not isinstance(source, str) or len(source.encode()) > MAX_ATTACKER_SOURCE:
        raise ValueError('Invalid or oversized attacker source')
    if re.search(r'^\s*import\b', source, re.M): raise ValueError('Attacker source may not import files')
    deployments = trace['deployments']
    if not isinstance(deployments, list) or len(deployments) > 4: raise ValueError('Need at most 4 attacker deployments')
    if deployments and not source.strip(): raise ValueError('Attacker deployments need attacker source')
    challenge_names = {d['name'] for d in environment['deployments']}
    names = [validate_deployment(d)['name'] for d in deployments]
    if len(names) != len(set(names)) or set(names) & challenge_names:
        raise ValueError('Attacker deployment names must be unique and distinct from challenge deployments')
    actions = trace['actions']
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValueError('Need 1-30 replay actions')
    for action in actions: validate_action(action, challenge_names | set(names))
    return trace


def validate_probe(probe, challenge_names):
    if not isinstance(probe, dict): raise ValueError('Invalid probe')
    kind = probe.get('kind')
    if kind == 'view':
        _fields(probe, 'kind label target function arguments', 'view probe')
        if not re.fullmatch(SIGNATURE, probe['function'] if isinstance(probe['function'], str) else ''):
            raise ValueError('Invalid probe ABI signature')
        _args(probe['arguments'], 'probe arguments')
    elif kind == 'balance': _fields(probe, 'kind label target', 'balance probe')
    elif kind == 'account_balance':
        _fields(probe, 'kind label account', 'account balance probe'); _account(probe['account'])
    elif kind == 'block_timestamp': _fields(probe, 'kind label', 'block timestamp probe')
    else: raise ValueError('Invalid probe kind')
    if kind in ('view', 'balance') and probe['target'] not in challenge_names:
        raise ValueError('Trusted probes may only observe challenge deployments')
    return identifier(probe['label'])


def _limit_compiler():  # pragma: no cover - runs in the child process
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    try: resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    except (ValueError, OSError): pass  # macOS does not enforce address-space limits


_COMPILED = {}


def compile_source(source, unit='Contract.sol'):
    """Compile with the pinned solc; no import callback, bounded resources."""
    key = digest([source, unit])
    if key not in _COMPILED: _COMPILED[key] = _compile(source, unit)
    return copy.deepcopy(_COMPILED[key])


def _compile(source, unit):
    solc = executable('AUTO_PROVE_SOLC', 'solc')
    if '0.8.28' not in command([solc, '--version']): raise ValueError('Requires Solidity 0.8.28')
    request = {'language': 'Solidity', 'sources': {unit: {'content': source}},
               'settings': {'outputSelection': {'*': {'*': ['abi', 'evm.bytecode.object', 'storageLayout']}}}}
    with tempfile.TemporaryDirectory(prefix='auto-prove-solc-') as work:
        result = subprocess.run([solc, '--standard-json', '--no-import-callback'], input=json.dumps(request),
                                capture_output=True, text=True, cwd=work, timeout=60,
                                preexec_fn=_limit_compiler, env={'PATH': '/usr/bin:/bin'})
    try: payload = json.loads(result.stdout)
    except json.JSONDecodeError: raise ValueError('Solidity compiler returned no result') from None
    errors = [e.get('formattedMessage', 'compile error') for e in payload.get('errors', []) if e.get('severity') == 'error']
    if result.returncode or errors: raise ValueError('Solidity compile failed: ' + '\n'.join(errors)[:4000])
    return payload['contracts'].get(unit, {})


def source_ast(source, unit='Contract.sol'):
    """Compact AST of trusted challenge source (for function-level patch metrics)."""
    solc = executable('AUTO_PROVE_SOLC', 'solc')
    request = {'language': 'Solidity', 'sources': {unit: {'content': source}},
               'settings': {'outputSelection': {'*': {'': ['ast']}}}}
    with tempfile.TemporaryDirectory(prefix='auto-prove-solc-') as work:
        result = subprocess.run([solc, '--standard-json', '--no-import-callback'], input=json.dumps(request),
                                capture_output=True, text=True, cwd=work, timeout=60,
                                preexec_fn=_limit_compiler, env={'PATH': '/usr/bin:/bin'})
    payload = json.loads(result.stdout)
    if any(e.get('severity') == 'error' for e in payload.get('errors', [])): raise ValueError('Solidity parse failed')
    return payload['sources'][unit]['ast']


def members(source):
    """Map 'Contract.member(signature)' -> exact source text, for functions, modifiers, events and state."""
    ast = source_ast(source); data = source.encode(); rows = {}
    for contract in ast.get('nodes', []):
        if contract.get('nodeType') != 'ContractDefinition': continue
        for node in contract.get('nodes', []):
            kind = node.get('nodeType')
            if kind not in ('FunctionDefinition', 'ModifierDefinition', 'VariableDeclaration', 'EventDefinition',
                            'ErrorDefinition', 'StructDefinition', 'EnumDefinition'): continue
            name = node.get('name') or node.get('kind', 'anonymous')
            params = node.get('parameters', {}).get('parameters', []) if isinstance(node.get('parameters'), dict) else []
            types = ','.join(p.get('typeDescriptions', {}).get('typeString', '?') for p in params)
            start, length = map(int, node['src'].split(':')[:2])
            key = contract['name'] + '.' + name + ('(' + types + ')' if kind in ('FunctionDefinition', 'ModifierDefinition') else '')
            rows[key] = data[start:start + length].decode(errors='replace')
    return rows


def storage_layout(source, contract_name):
    compiled = compile_source(source)
    if contract_name not in compiled: raise ValueError('Contract missing from compiled source')
    layout = compiled[contract_name].get('storageLayout', {}).get('storage', [])
    return [{'label': s['label'], 'slot': s['slot'], 'offset': s['offset'], 'type': s['type']} for s in layout]


class Chain:
    """One private Anvil instance; terminated by close()."""

    def __init__(self, seed):
        anvil = executable('AUTO_PROVE_ANVIL', 'anvil')
        if '1.7.1' not in command([anvil, '--version']): raise ValueError('Requires Anvil 1.7.1')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        self.chain_id = int(digest(seed)[:7], 16) + 1
        self.process = subprocess.Popen([anvil, '--host', '127.0.0.1', '--port', str(port), '--chain-id', str(self.chain_id),
                                         '--accounts', str(ACCOUNTS), '--gas-price', '0', '--base-fee', '0',
                                         '--timestamp', str(GENESIS_TIME), '--silent'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = 'http://127.0.0.1:' + str(port); self.rpc_id = 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(100):
            try:
                if int(self.rpc('eth_chainId', []), 16) == self.chain_id: break
            except (OSError, ValueError): pass
            time.sleep(0.05)
        else:
            self.close(); raise ValueError('Local EVM did not start')
        self.accounts = self.rpc('eth_accounts', [])

    def rpc(self, method, params):
        if self.process.poll() is not None: raise ValueError('Local Anvil exited')
        self.rpc_id += 1
        body = json.dumps({'jsonrpc': '2.0', 'id': self.rpc_id, 'method': method, 'params': params}).encode()
        req = urllib.request.Request(self.url, body, {'Content-Type': 'application/json'})
        with self.opener.open(req, timeout=20) as response: result = json.load(response)
        if 'error' in result: raise ValueError('Local EVM: ' + str(result['error'])[:2000])
        return result['result']

    def send(self, tx):
        txid = self.rpc('eth_sendTransaction', [dict(tx, gas=hex(GAS_PER_TX), gasPrice='0x0')])
        for _ in range(100):
            receipt = self.rpc('eth_getTransactionReceipt', [txid])
            if receipt is not None: return receipt
            time.sleep(.05)
        raise ValueError('Transaction receipt timeout')

    def advance(self, seconds):
        if seconds:
            self.rpc('evm_increaseTime', [seconds]); self.rpc('evm_mine', [])

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)


def _signature_of(entry):
    return entry['name'] + '(' + ','.join(v['type'] for v in entry['inputs']) + ')'


def replay(input_data, environment, trace, output, probes):
    """Replay a v2 trace in the trusted environment and capture probe frames.

    Frame 0 is the state after deployment and trusted setup, before any
    submitted action. Each later frame follows one submitted action.
    """
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    report = {'version': TRACE_VERSION, 'status': 'inconclusive', 'input_digest': digest(input_data),
              'environment_digest': digest(environment), 'trace_digest': digest(trace),
              'probes_digest': digest(probes), 'deployments': {}, 'setup': [], 'transactions': [], 'frames': [],
              'scope': 'concrete Solidity transactions on a disposable local Anvil; no model/EVM equivalence proof'}
    chain = None
    try:
        validate_trace(trace, environment)
        challenge_names = {d['name'] for d in environment['deployments']}
        labels = [validate_probe(p, challenge_names) for p in probes]
        if len(labels) != len(set(labels)): raise ValueError('Duplicate trusted probe label')
        cast = executable('AUTO_PROVE_CAST', 'cast')
        compiled = {'challenge': compile_source(input_data['contract_source'])}
        if trace['attacker_source'].strip():
            compiled['attacker'] = compile_source(trace['attacker_source'], 'Attacker.sol')
        chain = Chain([report['input_digest'], report['environment_digest'], report['trace_digest']])
        addresses = {}; abis = {}

        def resolve(values):
            result = []
            for value in _args(values):
                if value.startswith('$account:'): value = chain.accounts[_account(int(value.split(':', 1)[1]))]
                elif value.startswith('$deployment:'):
                    name = value.split(':', 1)[1]
                    if name not in addresses: raise ValueError('Deployment address unavailable: ' + name)
                    value = addresses[name]
                elif value == '$contract': value = addresses[environment['deployments'][0]['name']]
                elif re.fullmatch(r'\$now\+[0-9]{1,10}', value):
                    latest = chain.rpc('eth_getBlockByNumber', ['latest', False])
                    value = str(int(latest['timestamp'], 16) + int(value[5:]))
                result.append(value)
            return result

        def deploy(deployment, origin):
            unit = compiled[origin]
            if deployment['contract_name'] not in unit: raise ValueError('Unknown ' + origin + ' contract ' + deployment['contract_name'])
            selected = unit[deployment['contract_name']]
            bytecode = selected['evm']['bytecode']['object']
            if not re.fullmatch('[0-9a-fA-F]+', bytecode): raise ValueError('Unlinked or abstract contract')
            inputs = next((e['inputs'] for e in selected['abi'] if e['type'] == 'constructor'), [])
            encoded = ''
            if inputs:
                sig = 'f(' + ','.join(e['type'] for e in inputs) + ')'
                encoded = command([cast, 'abi-encode', sig] + resolve(deployment['constructor_arguments']))[2:]
            elif deployment['constructor_arguments']: raise ValueError('Constructor takes no arguments')
            receipt = chain.send({'from': chain.accounts[deployment['account']], 'data': '0x' + bytecode + encoded,
                                  'value': hex(int(deployment['value_wei']))})
            if int(receipt['status'], 16) != 1: raise ValueError('Deployment reverted: ' + deployment['name'])
            addresses[deployment['name']] = receipt['contractAddress']; abis[deployment['name']] = selected['abi']
            report['deployments'][deployment['name']] = {'origin': origin, 'contract_name': deployment['contract_name'],
                                                         'address': receipt['contractAddress']}

        def act(action):
            chain.advance(action['advance_seconds'])
            calldata = '0x'
            if action['function']:
                calldata = command([cast, 'calldata', action['function']] + resolve(action['arguments']))
            receipt = chain.send({'from': chain.accounts[action['account']], 'to': addresses[action['target']],
                                  'data': calldata, 'value': hex(int(action['value_wei']))})
            block = chain.rpc('eth_getBlockByNumber', [receipt['blockNumber'], False])
            return {'action': action, 'status': 'success' if int(receipt['status'], 16) == 1 else 'reverted',
                    'transaction_hash': receipt['transactionHash'], 'gas_used': int(receipt['gasUsed'], 16),
                    'timestamp': int(block['timestamp'], 16)}

        def capture(step):
            values = {}; raw_values = {}
            for probe in probes:
                if probe['kind'] == 'block_timestamp':
                    raw = chain.rpc('eth_getBlockByNumber', ['latest', False])['timestamp']; value = int(raw, 16)
                elif probe['kind'] == 'account_balance':
                    raw = chain.rpc('eth_getBalance', [chain.accounts[probe['account']], 'latest']); value = int(raw, 16)
                elif probe['kind'] == 'balance':
                    raw = chain.rpc('eth_getBalance', [addresses[probe['target']], 'latest']); value = int(raw, 16)
                else:
                    entries = [e for e in abis[probe['target']] if e.get('type') == 'function' and _signature_of(e) == probe['function']]
                    if len(entries) != 1 or entries[0]['stateMutability'] not in ('view', 'pure') or len(entries[0]['outputs']) != 1:
                        raise ValueError('Trusted probe must select one scalar view/pure function: ' + probe['label'])
                    data = command([cast, 'calldata', probe['function']] + resolve(probe['arguments']))
                    raw = chain.rpc('eth_call', [{'from': chain.accounts[0], 'to': addresses[probe['target']], 'data': data}, 'latest'])
                    value = decode_scalar(raw, entries[0]['outputs'][0]['type'])
                values[probe['label']] = value; raw_values[probe['label']] = raw
            report['frames'].append({'step': step, 'values': values, 'raw_values': raw_values})

        for deployment in environment['deployments']: deploy(deployment, 'challenge')
        for action in environment['setup']:
            row = act(action); report['setup'].append(row)
            if row['status'] != 'success': raise ValueError('Trusted setup action reverted')
        for deployment in trace['deployments']: deploy(deployment, 'attacker')
        capture(0)
        for action in trace['actions']:
            report['transactions'].append(act(action)); capture(len(report['transactions']))
        report['status'] = 'replayed'
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report['reason'] = str(error)
    finally:
        if chain is not None: chain.close()
    write(output / 'replay.json', report)
    return report


def v1_environment(policy_contract, trace_v1):
    """Express a v1 trace's self-chosen deployment as a trusted v2 environment."""
    return {'deployments': [{'name': 'main', 'contract_name': policy_contract,
                             'constructor_arguments': copy.deepcopy(trace_v1['constructor_arguments']),
                             'account': 0, 'value_wei': '0'}], 'setup': []}


def v1_trace(trace_v1):
    return {'version': TRACE_VERSION, 'attacker_source': '', 'deployments': [],
            'actions': [dict(a, target='main', advance_seconds=0) for a in trace_v1['actions']]}
