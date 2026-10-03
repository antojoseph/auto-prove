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


def replay(data, trace, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    report = {'status':'inconclusive', 'input_digest':digest(data), 'trace_digest':digest(trace),
              'scope':'concrete Solidity transactions on disposable local Anvil; no model/EVM equivalence proof',
              'intent_connection':'fallible interpretation; creator review pending', 'transactions':[], 'observations':[]}
    process = None
    try:
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
        for action in trace['actions']:
            calldata = '0x'
            if action['function']:
                calldata = command([cast,'calldata',signature(action['function'])] + arguments(action['arguments']))
            elif action['arguments']: raise ValueError('Empty calldata takes no arguments')
            result = receipt({'from':account(action['account']), 'to':address, 'data':calldata,
                              'value':amount(action['value_wei'])})
            report['transactions'].append({'action':action,'status':'success' if int(result['status'],16)==1 else 'reverted',
                                            'transaction_hash':result['transactionHash'],'gas_used':int(result['gasUsed'],16)})
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
