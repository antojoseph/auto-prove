"""Held-out evaluation corpus (backlog I-19). Developer-authored ground truth.

Each case gives creator input, a trusted environment/policy, legitimate seed
traces, known attacks, and safe/unsafe source variants. HELD-OUT items
(heldout_seeds, heldout_attacks) are never shown to the loop: after the loop
repairs an unsafe variant, they test whether the fix generalises and whether it
over-restricts legitimate use. Keep a private copy of any corpus used for a
rewarded evaluation; public cases can be overfitted.

    python3 general/corpus/build.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def act(account, function, arguments=(), value='0', advance=0, target='main'):
    return {'account': account, 'target': target, 'function': function, 'arguments': list(arguments), 'value_wei': value,
            'advance_seconds': advance}


def trace(*actions, source='', deployments=()):
    return {'version': 'transaction-trace-v2', 'attacker_source': source, 'deployments': list(deployments), 'actions': list(actions)}


def origin():
    return {'version': 1, 'source': 'open', 'rationale': 'Corpus ground truth.'}


def env(contract, setup=(), args=()):
    return {'deployments': [{'name': 'main', 'contract_name': contract, 'constructor_arguments': list(args), 'account': 0,
                             'value_wei': '0'}], 'setup': list(setup)}


# --- Vault: reentrancy -------------------------------------------------------
VAULT_SAFE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
contract Vault {
    mapping(address => uint256) public balanceOf;
    uint256 public totalDeposits;
    function deposit() external payable {
        balanceOf[msg.sender] += msg.value;
        totalDeposits += msg.value;
    }
    function withdraw() external {
        uint256 amount = balanceOf[msg.sender];
        require(amount > 0);
        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
    }
}
'''
VAULT_REENTRANT = VAULT_SAFE.replace('''        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);''', '''        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;''')
ATTACKER = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
interface IVault { function deposit() external payable; function withdraw() external; }
contract Attacker {
    IVault public vault; uint256 public depth; uint256 public limit;
    constructor(address target, uint256 reentries) { vault = IVault(target); limit = reentries; }
    function attack() external payable { vault.deposit{value: msg.value}(); vault.withdraw(); }
    receive() external payable { if (depth < limit) { depth += 1; vault.withdraw(); } }
}
'''
def reentry(n, value):
    return trace(act(3, 'attack()', value=value, target='attacker'), source=ATTACKER,
                 deployments=[{'name': 'attacker', 'contract_name': 'Attacker', 'constructor_arguments': ['$deployment:main', str(n)],
                               'account': 3, 'value_wei': '0'}])
QUOTE_V = 'The vault must always hold enough ether to pay every depositor their recorded balance'
VAULT = {
    'input': {'id': 'CorpusVault', 'intent': 'Depositors can deposit ether and withdraw their own balance at any time. ' + QUOTE_V +
              ', even against malicious callers and contracts.', 'contract_source': VAULT_SAFE, 'approved_assumptions': []},
    'environment': env('Vault', [act(1, 'deposit()', value='100')]),
    'probes': [{'kind': 'view', 'label': 'VictimBalance', 'target': 'main', 'function': 'balanceOf(address)', 'arguments': ['$account:1']},
               {'kind': 'view', 'label': 'Total', 'target': 'main', 'function': 'totalDeposits()', 'arguments': []},
               {'kind': 'balance', 'label': 'Held', 'target': 'main'}],
    'requirements': [
        {'id': 'TotalBacked', 'scope': 'intent', 'property_id': '', 'requirement': 'Held ether covers recorded balances.',
         'intent_quote': QUOTE_V, 'step_scope': 'each', 'predicate': {'op': 'le', 'args': [{'ref': 'Total'}, {'ref': 'Held'}]}, 'origin': origin()},
        {'id': 'VictimBacked', 'scope': 'intent', 'property_id': '', 'requirement': 'An existing depositor stays fully backed.',
         'intent_quote': QUOTE_V, 'step_scope': 'each', 'predicate': {'op': 'le', 'args': [{'ref': 'VictimBalance'}, {'ref': 'Held'}]}, 'origin': origin()}],
    'seeds': [{'description': 'deposit then withdraw', 'trace': trace(act(2, 'deposit()', value='30'), act(2, 'withdraw()')), 'expected_success_actions': [0, 1]}],
    'heldout_seeds': [{'description': 'existing depositor withdraws, redeposits, withdraws',
                       'trace': trace(act(1, 'withdraw()'), act(1, 'deposit()', value='5'), act(1, 'withdraw()')), 'expected_success_actions': [0, 1, 2]}],
    'attacks': [{'name': 'reenter-once', 'trace': reentry(1, '10')}],
    'heldout_attacks': [{'name': 'reenter-three-times', 'trace': reentry(3, '20')}],
    'variants': [{'name': 'safe', 'source': VAULT_SAFE, 'safe': True}, {'name': 'reentrant', 'source': VAULT_REENTRANT, 'safe': False}],
}

# --- Escrow: cumulative release and payer-only release ------------------------
ESCROW_SAFE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
contract MilestoneEscrow {
    mapping(address => uint256) public deposited;
    mapping(address => uint256) public released;
    function deposit() external payable { deposited[msg.sender] += msg.value; }
    function release(address payer, uint256 amount) external {
        require(msg.sender == payer);
        require(released[payer] + amount <= deposited[payer]);
        released[payer] += amount;
        (bool ok,) = msg.sender.call{value: amount}(""); require(ok);
    }
}
'''
ESCROW_NO_CUMULATIVE = ESCROW_SAFE.replace('require(released[payer] + amount <= deposited[payer]);', 'require(amount <= deposited[payer]);')
ESCROW_ANY_CALLER = ESCROW_SAFE.replace('        require(msg.sender == payer);\n', '')
QUOTE_E = 'funds released for a payer must never exceed what that payer deposited'
QUOTE_O = 'other payers must keep their deposited funds available in the escrow at all times'
R = 'release(address,uint256)'
ESCROW = {
    'input': {'id': 'CorpusEscrow', 'intent': 'Payers escrow funds for milestone work, and the escrow must hold them safely: ' + QUOTE_E +
              ', and ' + QUOTE_O + '. Only a payer may release its own deposit.', 'contract_source': ESCROW_SAFE,
              'approved_assumptions': []},
    'environment': env('MilestoneEscrow', [act(1, 'deposit()', value='100')]),
    'probes': [{'kind': 'view', 'label': 'Deposited', 'target': 'main', 'function': 'deposited(address)', 'arguments': ['$account:0']},
               {'kind': 'view', 'label': 'Released', 'target': 'main', 'function': 'released(address)', 'arguments': ['$account:0']},
               {'kind': 'view', 'label': 'OtherDeposited', 'target': 'main', 'function': 'deposited(address)', 'arguments': ['$account:1']},
               {'kind': 'view', 'label': 'OtherReleased', 'target': 'main', 'function': 'released(address)', 'arguments': ['$account:1']},
               {'kind': 'balance', 'label': 'Balance', 'target': 'main'},
               {'kind': 'account_balance', 'label': 'OutsiderBalance', 'account': 2}],
    'requirements': [
        {'id': 'OnlyPayerReleases', 'scope': 'intent', 'property_id': '',
         'requirement': 'An outside account (account 2 never deposits) can never receive escrowed funds.',
         'intent_quote': 'Only a payer may release its own deposit', 'step_scope': 'each',
         'predicate': {'op': 'le', 'args': [{'ref': 'OutsiderBalance'}, 10**22]}, 'origin': origin()},
        {'id': 'ReleaseWithinDeposit', 'scope': 'intent', 'property_id': '', 'requirement': 'Released never exceeds deposited.',
         'intent_quote': QUOTE_E, 'step_scope': 'each', 'predicate': {'op': 'le', 'args': [{'ref': 'Released'}, {'ref': 'Deposited'}]}, 'origin': origin()},
        {'id': 'OtherPayerBacking', 'scope': 'intent', 'property_id': '', 'requirement': 'Other payers\' unreleased deposits stay backed.',
         'intent_quote': QUOTE_O, 'step_scope': 'each',
         'predicate': {'op': 'le', 'args': [{'op': 'sub', 'args': [{'ref': 'OtherDeposited'}, {'ref': 'OtherReleased'}]}, {'ref': 'Balance'}]}, 'origin': origin()}],
    'seeds': [{'description': 'payer releases own deposit in two steps',
               'trace': trace(act(0, 'deposit()', value='100'), act(0, R, ['$account:0', '60']), act(0, R, ['$account:0', '40'])),
               'expected_success_actions': [0, 1, 2]}],
    'heldout_seeds': [{'description': 'other payer releases its own setup deposit',
                       'trace': trace(act(1, R, ['$account:1', '100'])), 'expected_success_actions': [0]}],
    'attacks': [{'name': 'double-release', 'trace': trace(act(0, 'deposit()', value='100'), act(0, R, ['$account:0', '100']), act(0, R, ['$account:0', '100']))},
                {'name': 'outsider-release', 'trace': trace(act(2, R, ['$account:1', '100']))}],
    'heldout_attacks': [{'name': 'split-overdraw', 'trace': trace(act(0, 'deposit()', value='50'), act(0, R, ['$account:0', '30']), act(0, R, ['$account:0', '30']))}],
    'variants': [{'name': 'safe', 'source': ESCROW_SAFE, 'safe': True},
                 {'name': 'no-cumulative-limit', 'source': ESCROW_NO_CUMULATIVE, 'safe': False},
                 {'name': 'any-caller', 'source': ESCROW_ANY_CALLER, 'safe': False}],
}

# --- Timelock: time-based release ---------------------------------------------
TIMELOCK_SAFE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
contract Timelock {
    address public beneficiary;
    uint256 public unlockTime;
    bool public paid;
    constructor(address who, uint256 unlockAt) payable { beneficiary = who; unlockTime = unlockAt; }
    function claim() external {
        require(msg.sender == beneficiary);
        require(block.timestamp >= unlockTime);
        require(!paid);
        paid = true;
        (bool ok,) = beneficiary.call{value: address(this).balance}(""); require(ok);
    }
}
'''
TIMELOCK_EARLY = TIMELOCK_SAFE.replace('        require(block.timestamp >= unlockTime);\n', '')
QUOTE_T = 'nobody can take the funds before the unlock time'
TIMELOCK = {
    'input': {'id': 'CorpusTimelock', 'intent': 'The deployer locks ether for a beneficiary; ' + QUOTE_T +
              ', and the beneficiary can claim them once at or after the unlock time.', 'contract_source': TIMELOCK_SAFE,
              'approved_assumptions': []},
    'environment': {'deployments': [{'name': 'main', 'contract_name': 'Timelock', 'constructor_arguments': ['$account:1', '$now+86400'],
                                     'account': 0, 'value_wei': '1000'}], 'setup': []},
    'probes': [{'kind': 'balance', 'label': 'Locked', 'target': 'main'},
               {'kind': 'view', 'label': 'Unlock', 'target': 'main', 'function': 'unlockTime()', 'arguments': []},
               {'kind': 'view', 'label': 'Paid', 'target': 'main', 'function': 'paid()', 'arguments': []},
               {'kind': 'block_timestamp', 'label': 'Now'}],
    'requirements': [
        {'id': 'LockedUntilPaid', 'scope': 'intent', 'property_id': '', 'requirement': 'Funds stay locked until the single claim.',
         'intent_quote': QUOTE_T, 'step_scope': 'each',
         'predicate': {'op': 'or', 'args': [{'op': 'eq', 'args': [{'ref': 'Locked'}, 1000]}, {'op': 'ge', 'args': [{'ref': 'Now'}, {'ref': 'Unlock'}]}]},
         'origin': origin()}],
    'seeds': [{'description': 'beneficiary claims after unlock', 'trace': trace(act(1, 'claim()', advance=86400)), 'expected_success_actions': [0]}],
    'heldout_seeds': [{'description': 'beneficiary claims well after unlock', 'trace': trace(act(1, 'claim()', advance=200000)), 'expected_success_actions': [0]}],
    'attacks': [{'name': 'early-claim', 'trace': trace(act(1, 'claim()', advance=10))}],
    'heldout_attacks': [{'name': 'claim-one-hour-early', 'trace': trace(act(1, 'claim()', advance=82800))}],
    'variants': [{'name': 'safe', 'source': TIMELOCK_SAFE, 'safe': True}, {'name': 'no-time-check', 'source': TIMELOCK_EARLY, 'safe': False}],
}

def vault_loop_responses():
    import copy
    props = [{'id': 'Placeholder', 'requirement': 'Corpus placeholder', 'intent_basis': 'Evaluation harness only',
              'statement': '∀ n : Nat, corpusPlaceholder n = n', 'explanation': 'Not a security property'}]
    review = {'reviewed_candidate_digest': '$PAYLOAD:reviewed_candidate_digest', 'verdict': 'approve', 'weakening_found': False,
              'unrelated_changes': False, 'over_restrictive': False, 'reasons': 'Effects before interaction; nothing else changes.'}
    return {'open_review': [{'reviewed_candidate_digest': '$PAYLOAD:reviewed_candidate_digest', 'verdict': 'approve',
                             'missing_requirements': [], 'reasons': 'Corpus ground-truth policy.'}],
            'judge': [{'verdict': 'contract_defect', 'root_cause_key': 'withdraw_reentrancy_before_state_update', 'cited_actions': [0],
                       'violated_requirement_ids': ['VictimBacked'], 'new_requirement_json': '', 'new_probes_json': '',
                       'ambiguity_readings': [], 'ambiguity_choice': '', 'out_of_scope': False,
                       'reasoning': 'Recorded mechanism fixture: reentrant withdraw pays twice before zeroing the balance.'}],
            'repair': [{'contract_source': VAULT_SAFE, 'model_body': 'def corpusPlaceholder (n : Nat) : Nat := n',
                        'properties_json': json.dumps(props, ensure_ascii=False),
                        'requirements_json': json.dumps(VAULT['requirements']), 'probes_json': json.dumps(VAULT['probes']),
                        'environment_json': json.dumps(VAULT['environment']), 'model_map_json': 'null', 'removed_or_relaxed': [],
                        'change_summary': 'Zero the balance before the external call.', 'reasoning': 'Checks-effects-interactions.'}],
            'repair_review_judge': [copy.deepcopy(review)], 'repair_review': [copy.deepcopy(review)]}


if __name__ == '__main__':
    (HERE / 'responses').mkdir(exist_ok=True); (HERE / 'responses' / 'vault-loop.json').write_text(json.dumps(vault_loop_responses(), indent=2, ensure_ascii=False) + '\n')
    for case in (VAULT, ESCROW, TIMELOCK):
        (HERE / (case['input']['id'] + '.json')).write_text(json.dumps(case, indent=2, ensure_ascii=False) + '\n')
