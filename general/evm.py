"""Generic concrete transaction replay on a disposable localhost Anvil chain.

This executes creator Solidity, not agent-generated tests. The trusted runner
records receipts and view results. No external RPC, real wallet, or network is used.
Concrete replay is evidence for selected transactions, not an EVM equivalence proof.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from .core import digest, write


def executable(env, name):
    selected = os.environ.get(env) or shutil.which(name)
    if not selected: raise RuntimeError(name + ' unavailable; install the pinned runtime')
    return selected


def command(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode: raise ValueError('Compiler/ABI encoding failed: ' + result.stderr[-4000:])
    return result.stdout.strip()


def validate_trace(trace):
    if not isinstance(trace, dict) or set(trace) != {'contract_name', 'constructor_arguments', 'actions', 'observations'}:
        raise ValueError('Invalid transaction trace fields')
    if not isinstance(trace['contract_name'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', trace['contract_name']):
        raise ValueError('Invalid contract name')
    def args(values):
        if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v, str) or len(v) > 4096 or v.startswith('-') for v in values):
            raise ValueError('Invalid ABI arguments')
    args(trace['constructor_arguments'])
    if not isinstance(trace['actions'], list) or not 1 <= len(trace['actions']) <= 30:
        raise ValueError('Need 1-30 replay actions')
    if not isinstance(trace['observations'], list) or len(trace['observations']) > 30:
        raise ValueError('Trace exceeds bounded replay budget')
    for action in trace['actions']:
        if not isinstance(action, dict) or set(action) != {'account', 'function', 'arguments', 'value_wei'}:
            raise ValueError('Invalid action fields')
        if type(action['account']) is not int or not 0 <= action['account'] < 10:
            raise ValueError('Invalid local account index')
        if not isinstance(action['function'], str) or (action['function'] and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)', action['function'])):
            raise ValueError('Invalid ABI signature')
        args(action['arguments'])
        if not action['function'] and action['arguments']: raise ValueError('Empty calldata takes no arguments')
        value = action['value_wei']
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,78}', value) or int(value) >= 2**256:
            raise ValueError('Invalid wei amount')
    for observation in trace['observations']:
        if not isinstance(observation, dict) or set(observation) != {'label', 'function', 'arguments'}:
            raise ValueError('Invalid observation fields')
        if not isinstance(observation['label'], str) or len(observation['label']) > 200:
            raise ValueError('Invalid observation label')
        if not isinstance(observation['function'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)', observation['function']):
            raise ValueError('Invalid ABI signature')
        args(observation['arguments'])
    return trace


def decode_scalar(raw, abi_type):
    """Decode one static ABI value; never guess a value from a failed/empty call."""
    if not isinstance(raw, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', raw):
        raise ValueError('Expected one static ABI result')
    number = int(raw, 16)
    if abi_type == 'bool':
        if number not in (0, 1): raise ValueError('Noncanonical ABI bool')
        return bool(number)
    if abi_type == 'address':
        if number >= 2**160: raise ValueError('Noncanonical ABI address')
        return '0x' + raw[-40:].lower()
    match = re.fullmatch(r'(u?int)([0-9]+)', abi_type)
    if not match: raise ValueError('Probe supports only uint/int, bool or address scalar results')
    bits = int(match[2])
    if bits not in range(8, 257, 8): raise ValueError('Unsupported ABI integer size')
    if match[1] == 'uint':
        if number >= 2**bits: raise ValueError('Noncanonical ABI uint')
        return number
    signed = number - 2**256 if number >= 2**255 else number
    if not -(2**(bits-1)) <= signed < 2**(bits-1): raise ValueError('Noncanonical ABI int')
    return signed


def replay(data, trace, output, probes=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    report = {'status':'inconclusive', 'input_digest':digest(data), 'trace_digest':digest(trace),
              'scope':'concrete Solidity transactions on disposable local Anvil; no model/EVM equivalence proof',
              'intent_connection':'fallible interpretation; creator review pending', 'transactions':[], 'observations':[],
              'frames':[], 'probes_digest':digest(probes) if probes is not None else None}
    process = None
    try:
        validate_trace(trace)
        solc = executable('AUTO_PROVE_SOLC', 'solc')
        anvil = executable('AUTO_PROVE_ANVIL', 'anvil')
        cast = executable('AUTO_PROVE_CAST', 'cast')
        if '0.8.28' not in command([solc, '--version']): raise ValueError('Requires Solidity 0.8.28')
        if '1.7.1' not in command([anvil, '--version']): raise ValueError('Requires Anvil 1.7.1')
        request = {'language':'Solidity', 'sources':{'Contract.sol':{'content':data['contract_source']}},
                   'settings':{'outputSelection':{'*':{'*':['abi','evm.bytecode.object']}}}}
        with tempfile.TemporaryDirectory(prefix='auto-prove-solc-') as work:
            compiled = subprocess.run([solc, '--standard-json', '--no-import-callback'], input=json.dumps(request),
                                      capture_output=True, text=True, cwd=work, timeout=45)
        payload = json.loads(compiled.stdout)
        errors = [e.get('formattedMessage','compile error') for e in payload.get('errors',[]) if e.get('severity') == 'error']
        if compiled.returncode or errors: raise ValueError('Solidity compile failed: ' + '\n'.join(errors)[:4000])
        selected = payload['contracts']['Contract.sol'][trace['contract_name']]
        bytecode = selected['evm']['bytecode']['object']
        if not re.fullmatch('[0-9a-fA-F]+', bytecode): raise ValueError('Unlinked or missing deployment bytecode')
        if len(trace['actions']) > 30 or len(trace['observations']) > 30: raise ValueError('Trace exceeds bounded replay budget')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); port = listener.getsockname()[1]
        # Unique ephemeral chain ID. No network-provided endpoint or keys.
        chain_id = int(digest(trace)[:7],16) + 1
        process = subprocess.Popen([anvil, '--host','127.0.0.1','--port',str(port), '--chain-id',str(chain_id),
                                    '--silent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = 'http://127.0.0.1:' + str(port)
        rpc_id = [0]
        def rpc(method, params):
            if process.poll() is not None: raise ValueError('Local Anvil exited')
            rpc_id[0] += 1
            body = json.dumps({'jsonrpc':'2.0','id':rpc_id[0],'method':method,'params':params}).encode()
            req = urllib.request.Request(url, body, {'Content-Type':'application/json'})
            # Ignore host proxy settings for this private loopback VM.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as response: result = json.load(response)
            if 'error' in result: raise ValueError('Local EVM: ' + str(result['error'])[:2000])
            return result['result']
        for _ in range(60):
            try:
                if int(rpc('eth_chainId',[]),16) == chain_id: break
            except (OSError, ValueError): pass
            time.sleep(0.05)
        else: raise ValueError('Local EVM did not start')
        accounts = rpc('eth_accounts',[])
        address = None
        def account(index):
            if not isinstance(index,int) or isinstance(index,bool) or not 0 <= index < len(accounts):
                raise ValueError('Invalid local account index')
            return accounts[index]
        def arguments(values):
            if not isinstance(values,list) or len(values) > 20: raise ValueError('Invalid ABI arguments')
            result = []
            for value in values:
                value = str(value)
                if value.startswith('$account:'): value = account(int(value.split(':')[1]))
                elif value == '$contract':
                    if address is None: raise ValueError('Contract address unavailable before deployment')
                    value = address
                if len(value)>4096 or value.startswith('-'): raise ValueError('Invalid ABI argument')
                result.append(value)
            return result
        def signature(value):
            if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\([A-Za-z0-9_,()\[\]]*\)',value):
                raise ValueError('Invalid ABI signature')
            return value
        def amount(value):
            value = str(value)
            if not re.fullmatch(r'[0-9]{1,78}',value) or int(value)>=2**256: raise ValueError('Invalid wei amount')
            return hex(int(value))
        def receipt(tx):
            txid = rpc('eth_sendTransaction',[dict(tx,gas=hex(8_000_000))])
            for _ in range(60):
                result = rpc('eth_getTransactionReceipt',[txid])
                if result is not None: return result
                time.sleep(.05)
            raise ValueError('Transaction receipt timeout')
        constructor = selected['abi']
        constructor_inputs = next((e['inputs'] for e in constructor if e['type']=='constructor'),[])
        encoded = ''
        if constructor_inputs:
            sig = 'f(' + ','.join(e['type'] for e in constructor_inputs) + ')'
            encoded = command([cast,'abi-encode',signature(sig)] + arguments(trace['constructor_arguments']))[2:]
        elif trace['constructor_arguments']: raise ValueError('Contract constructor takes no arguments')
        deployment = receipt({'from':account(0),'data':'0x'+bytecode+encoded,'value':'0x0'})
        if int(deployment['status'],16) != 1: raise ValueError('Local deployment reverted')
        address = deployment['contractAddress']; report['contract_address'] = address
        def capture(step):
            if probes is None: return
            values = {}; raw_values = {}
            for probe in probes:
                label = probe['label']
                if label in values: raise ValueError('Duplicate trusted probe label')
                if probe['kind'] == 'balance':
                    raw = rpc('eth_getBalance', [address, 'latest']); value = int(raw, 16)
                elif probe['kind'] == 'view':
                    sig = signature(probe['function'])
                    entries = [e for e in selected['abi'] if e.get('type') == 'function' and
                               e['name'] + '(' + ','.join(v['type'] for v in e['inputs']) + ')' == sig]
                    if len(entries) != 1 or entries[0]['stateMutability'] not in ('view', 'pure') or len(entries[0]['outputs']) != 1:
                        raise ValueError('Trusted probe must select one scalar view/pure ABI function')
                    calldata = command([cast, 'calldata', sig] + arguments(probe['arguments']))
                    raw = rpc('eth_call', [{'from':account(0), 'to':address, 'data':calldata}, 'latest'])
                    value = decode_scalar(raw, entries[0]['outputs'][0]['type'])
                else: raise ValueError('Unknown trusted probe kind')
                values[label] = value; raw_values[label] = raw
            report['frames'].append({'step':step, 'values':values, 'raw_values':raw_values})
        capture(0)
        for action in trace['actions']:
            calldata = '0x'
            if action['function']:
                calldata = command([cast,'calldata',signature(action['function'])] + arguments(action['arguments']))
            elif action['arguments']: raise ValueError('Empty calldata takes no arguments')
            result = receipt({'from':account(action['account']), 'to':address, 'data':calldata,
                              'value':amount(action['value_wei'])})
            report['transactions'].append({'action':action,'status':'success' if int(result['status'],16)==1 else 'reverted',
                                            'transaction_hash':result['transactionHash'],'gas_used':int(result['gasUsed'],16)})
            capture(len(report['transactions']))
        for observation in trace['observations']:
            calldata = command([cast,'calldata',signature(observation['function'])] + arguments(observation['arguments']))
            value = rpc('eth_call',[{'from':account(0),'to':address,'data':calldata},'latest'])
            report['observations'].append({'label':observation['label'],'function':observation['function'],
                                           'arguments':observation['arguments'],'raw_value':value})
        report['contract_balance_wei'] = int(rpc('eth_getBalance',[address,'latest']),16)
        report['status'] = 'replayed'
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report['reason'] = str(error)
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
    write(output/'replay.json', report)
    return report
