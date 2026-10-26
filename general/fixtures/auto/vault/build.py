"""Developer-authored fixtures: open a Vault challenge, then attack it with a reentrant contract.

Recorded role responses stand in for the proposer, policy author, open reviewer,
judge, repair author and reviewers; they exercise the mechanism, not live model
judgment. Replay, Lean compilation and the differential check are real.

    python3 general/fixtures/auto/vault/build.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

VAULT = '''// SPDX-License-Identifier: MIT
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
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;
    }
}
'''
VAULT_FIXED = VAULT.replace('''        require(amount > 0);
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;
''', '''        require(amount > 0);
        balanceOf[msg.sender] = 0;
        totalDeposits -= amount;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok);
''')
assert VAULT_FIXED != VAULT

INPUT = {'id': 'ReentrantVault',
         'intent': 'Depositors can deposit ether and withdraw their own balance at any time. The vault must always hold '
                   'enough ether to pay every depositor their recorded balance, even against malicious callers and contracts.',
         'contract_source': VAULT, 'approved_assumptions': []}

MODEL = '''structure VaultState where
  balanceOf : Nat → Nat
  totalDeposits : Nat
  held : Nat

def put (f : Nat → Nat) (who value : Nat) : Nat → Nat :=
  fun a => if a = who then value else f a

def depositV (s : VaultState) (who amount : Nat) : VaultState :=
  { s with balanceOf := put s.balanceOf who (s.balanceOf who + amount),
           totalDeposits := s.totalDeposits + amount, held := s.held + amount }

abbrev withdrawAllowed (s : VaultState) (who : Nat) : Prop :=
  0 < s.balanceOf who ∧ s.balanceOf who ≤ s.held

def withdrawV (s : VaultState) (who : Nat) : VaultState :=
  if withdrawAllowed s who then
    { s with balanceOf := put s.balanceOf who 0, totalDeposits := s.totalDeposits - s.balanceOf who,
             held := s.held - s.balanceOf who }
  else s'''

PROPERTIES = [
    {'id': 'WithdrawPaysOwnBalance', 'requirement': 'A withdrawal pays exactly the caller\'s recorded balance.',
     'intent_basis': 'Depositors can withdraw their own balance.',
     'statement': '∀ (s : VaultState) (who : Nat), withdrawAllowed s who → (withdrawV s who).held = s.held - s.balanceOf who',
     'explanation': 'Sequential model: the vault pays the balance and zeroes it in one step. Reentrancy is not modelled.', 'proof': 'by sorry'},
    {'id': 'OtherBalancesUnchanged', 'requirement': 'A withdrawal never changes another depositor\'s balance.',
     'intent_basis': 'Every depositor keeps their recorded balance.',
     'statement': '∀ (s : VaultState) (who other : Nat), other ≠ who → (withdrawV s who).balanceOf other = s.balanceOf other',
     'explanation': 'Only the caller\'s entry changes.', 'proof': 'by sorry'},
]
CANDIDATE = {'status': 'supported', 'summary': 'Ether vault with per-depositor balances.',
             'threat_model': ['Malicious callers and attacker contracts with callbacks.'], 'model_body': MODEL,
             'properties': PROPERTIES, 'assumptions': [], 'unresolved_questions': [],
             'execution_gaps': ['The sequential Lean model does not represent reentrant callbacks during withdraw.']}

ENVIRONMENT = {'deployments': [{'name': 'vault', 'contract_name': 'Vault', 'constructor_arguments': [], 'account': 0, 'value_wei': '0'}],
               'setup': [{'account': 1, 'target': 'vault', 'function': 'deposit()', 'arguments': [], 'value_wei': '100', 'advance_seconds': 0}]}
PROBES = [{'kind': 'view', 'label': 'VictimBalance', 'target': 'vault', 'function': 'balanceOf(address)', 'arguments': ['$account:1']},
          {'kind': 'view', 'label': 'Total', 'target': 'vault', 'function': 'totalDeposits()', 'arguments': []},
          {'kind': 'balance', 'label': 'Held', 'target': 'vault'}]
ORIGIN = {'version': 1, 'source': 'open', 'rationale': 'States the backing protection in the intent.'}
QUOTE = 'The vault must always hold enough ether to pay every depositor their recorded balance'
REQUIREMENTS = [
    {'id': 'TotalBacked', 'scope': 'intent', 'property_id': '', 'requirement': 'Held ether covers the sum of recorded balances.',
     'intent_quote': QUOTE, 'step_scope': 'each', 'predicate': {'op': 'le', 'args': [{'ref': 'Total'}, {'ref': 'Held'}]}, 'origin': ORIGIN},
    {'id': 'VictimBacked', 'scope': 'spec', 'property_id': 'OtherBalancesUnchanged',
     'requirement': 'An existing depositor\'s recorded balance stays fully backed by held ether.', 'intent_quote': QUOTE,
     'step_scope': 'each', 'predicate': {'op': 'le', 'args': [{'ref': 'VictimBalance'}, {'ref': 'Held'}]}, 'origin': ORIGIN},
]


def act(account, function, value='0', target='vault'):
    return {'account': account, 'target': target, 'function': function, 'arguments': [], 'value_wei': value, 'advance_seconds': 0}


def trace(*actions, source='', deployments=()):
    return {'version': 'transaction-trace-v2', 'attacker_source': source, 'deployments': list(deployments), 'actions': list(actions)}


SEEDS = [{'description': 'A new depositor deposits and withdraws.', 'trace': trace(act(2, 'deposit()', '30'), act(2, 'withdraw()')),
          'expected_success_actions': [0, 1]},
         {'description': 'The existing depositor withdraws its full balance.', 'trace': trace(act(1, 'withdraw()')),
          'expected_success_actions': [0]}]
MODEL_MAP = {'state_type': 'VaultState', 'initial': 'VaultState.mk (fun a => if a = 1 then 100 else 0) 100 100',
             'actions': [{'target': 'vault', 'function': 'deposit()', 'term': 'depositV s $sender $value'},
                         {'target': 'vault', 'function': 'withdraw()', 'term': 'withdrawV s $sender'}],
             'observations': [{'probe': 'VictimBalance', 'term': 's.balanceOf 1'}, {'probe': 'Total', 'term': 's.totalDeposits'},
                              {'probe': 'Held', 'term': 's.held'}]}

ATTACKER = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
interface IVault { function deposit() external payable; function withdraw() external; }
contract Attacker {
    IVault public vault; uint256 public reentered;
    constructor(address target) { vault = IVault(target); }
    function attack() external payable { vault.deposit{value: msg.value}(); vault.withdraw(); }
    receive() external payable { if (reentered == 0) { reentered = 1; vault.withdraw(); } }
}
'''
ATTACK = {'contributor': 'fixture-solver-reentrancy', 'contributor_model': 'openai/gpt-6.1-sol', 'kind': 'attack',
          'requirement_ref': {'version': 1, 'requirement_id': 'VictimBacked'},
          'claim': 'An attacker contract re-enters withdraw() from receive() before its balance is zeroed.',
          'expected_success_actions': [], 'reproduces': '',
          'trace': trace(act(3, 'attack()', '10', target='attacker'), source=ATTACKER,
                         deployments=[{'name': 'attacker', 'contract_name': 'Attacker', 'constructor_arguments': ['$deployment:vault'],
                                       'account': 3, 'value_wei': '0'}])}


def review(reasons):
    return {'reviewed_candidate_digest': '$PAYLOAD:reviewed_candidate_digest', 'verdict': 'approve', 'weakening_found': False,
            'unrelated_changes': False, 'over_restrictive': False, 'reasons': reasons}


OPEN = {'proposer': [CANDIDATE],
        'policy_author': [{'environment_json': json.dumps(ENVIRONMENT), 'probes_json': json.dumps(PROBES),
                           'requirements_json': json.dumps(REQUIREMENTS, ensure_ascii=False), 'must_succeed_json': json.dumps(SEEDS),
                           'model_map_json': json.dumps(MODEL_MAP, ensure_ascii=False),
                           'reasoning': 'Setup gives an existing depositor 100 wei that attacks could steal.'}],
        'open_review': [{'reviewed_candidate_digest': '$PAYLOAD:reviewed_candidate_digest', 'verdict': 'approve',
                         'missing_requirements': [], 'reasons': 'Backing is observable for the total and for an existing depositor.'}]}
ATTACK_RESPONSES = {
    'judge': [{'verdict': 'contract_defect', 'root_cause_key': 'withdraw_reentrancy_before_state_update', 'cited_actions': [0],
               'violated_requirement_ids': ['VictimBacked'], 'new_requirement_json': '', 'new_probes_json': '',
               'ambiguity_readings': [], 'ambiguity_choice': '', 'out_of_scope': False,
               'reasoning': 'withdraw() pays before zeroing the balance; the attacker re-enters and is paid twice, leaving 90 wei '
                            'held against the victim\'s recorded 100. VictimBacked captures it.'}],
    'repair': [{'contract_source': VAULT_FIXED, 'model_body': MODEL, 'properties_json': json.dumps([{k: v for k, v in p.items() if k != 'proof'} for p in PROPERTIES], ensure_ascii=False),
                'requirements_json': json.dumps(REQUIREMENTS, ensure_ascii=False), 'probes_json': json.dumps(PROBES),
                'environment_json': json.dumps(ENVIRONMENT), 'model_map_json': json.dumps(MODEL_MAP, ensure_ascii=False),
                'removed_or_relaxed': [], 'change_summary': 'withdraw() zeroes the balance before paying (checks-effects-interactions).',
                'reasoning': 'Reordering the two effects before the external call closes reentrancy without changing behaviour for honest users.'}],
    'repair_review_judge': [review('Effects precede the interaction; reentry finds a zero balance and reverts.')],
    'repair_review': [review('Same function, same storage; legitimate withdrawals pass; the sequential model already matches.')],
}


def build():
    files = {'input.json': INPUT, 'responses-open.json': OPEN, 'responses-attack.json': ATTACK_RESPONSES}
    for name, value in files.items():
        (HERE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    (HERE / 'templates/s1').mkdir(parents=True, exist_ok=True)
    (HERE / 'templates/s1/reentrancy.json').write_text(json.dumps(ATTACK, indent=2) + '\n')


if __name__ == '__main__': build()
