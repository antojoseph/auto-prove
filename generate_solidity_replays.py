"""Generate EVM tests for the intended side of B's validated witness traces."""
import json
from pathlib import Path
from engine import ROOT, validate_trace


def generate():
    report=json.loads((ROOT/"runs/demo/report.json").read_text())
    lines=['// SPDX-License-Identifier: MIT','pragma solidity 0.8.28;',
           'import "./TokenEscrow.t.sol";',
           '// Generated from validated review traces. Checks reference-model observations on Solidity.',
           'contract ReferenceTraceReplayTest {',
           'Vm constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));',
           'address constant BOB = address(0xB0B); address constant EVE = address(0xE0E);',
           'MockToken token; TokenEscrow escrow;',
           'function setUp() public { vm.warp(0); token = new MockToken();',
           'escrow = new TokenEscrow(token, BOB, 100, 10);',
           'token.mint(address(this), 1000); token.approve(address(escrow), 100); }']
    count=0
    for case in report['cases']:
        for finding in case['evaluation']['findings']:
            if not finding['validated']: continue
            validate_trace(finding['trace']); count+=1
            lines += [f'function testReferenceWitness{count}() public {{']
            for s in finding['replay']['steps']:
                a=s['action']; state=s['intended']['state']
                actor={'alice':'address(this)','bob':'BOB','eve':'EVE'}[a['caller']]
                lines += ['{',f'vm.warp({a["time"]});',f'token.configure({str(not a["transfer_ok"]).lower()}, false, address(0));']
                if a['kind']=='donate':
                    lines += [f'token.mint({actor}, {a["amount"]});',f'vm.prank({actor});',
                              f'bool success = token.transfer(address(escrow), {a["amount"]});']
                else:
                    method='fund' if a['kind']=='fund' else 'release'
                    lines += [f'vm.prank({actor});',f'(bool success,) = address(escrow).call(abi.encodeCall(TokenEscrow.{method}, ()));']
                expected=str(s['intended']['outcome']=='ok').lower()
                lines += [f'require(success == {expected}, "outcome");',
                    f'require(escrow.funded() == {str(state["funded"]).lower()}, "funded");',
                    f'require(escrow.released() == {str(state["released"]).lower()}, "released");',
                    f'require(token.balanceOf(address(escrow)) == {state["balance"]}, "escrow balance");',
                    f'require(token.balanceOf(BOB) == {state["bob"]}, "beneficiary balance");','}']
            lines += ['}']
    lines += ['}']
    target=ROOT/'contracts/test/ReferenceTraceReplay.t.sol'
    target.write_text('\n'.join(lines)+'\n')
    print(f'Generated {count} Solidity replay tests: {target}')


if __name__=='__main__': generate()
