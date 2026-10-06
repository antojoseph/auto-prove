import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from general.core import digest, freeze, read, validate_snapshot
from general.attacks import (adjudicate, accept, regress, assess, policy_check,
                            submission_check, evaluate, expression)
from general.review import propose, creator_review
from general.evm import decode_scalar, validate_trace

ROOT = Path(__file__).resolve().parent


def fixtures():
    snapshot = read(ROOT/'general/evidence/lending/round-2/snapshot.json')
    req = {'id':'CollateralBacking', 'scope':'spec', 'property_id':'CollateralLock',
           'requirement':'Debt must remain at most half of collateral after withdrawal.',
           'intent_quote':'must not remove collateral while doing so would leave their debt undercollateralized',
           'review_status':'approved', 'step_scope':'each',
           'predicate':{'op':'le','args':[{'op':'mul','args':[2,{'ref':'Debt'}]}, {'ref':'Collateral'}]}}
    probes = [{'kind':'view','label':'Debt','function':'debt(address)','arguments':['$account:0']},
              {'kind':'view','label':'Collateral','function':'collateral(address)','arguments':['$account:0']}]
    policy = {'version':'transaction-attack-v1', 'snapshot_digest':snapshot['digest'],
              'contract_name':'LendingPool', 'probes':probes, 'requirements':[req]}
    submission = {'version':'transaction-attack-v1','snapshot_digest':snapshot['digest'],
                  'policy_digest':digest(policy), 'contributor':'synthetic-test', 'requirement_id':'CollateralBacking',
                  'reasoning':'Withdraw all collateral after borrowing; debt remains.',
                  'trace':read(ROOT/'general/fixtures/lending-attack-trace.json')}
    return snapshot, policy, submission


def mock_replay(bad=True, intermediate=False):
    def implementation(data, trace, output, probes=None):
        frames=[{'step':i,'values':{'Debt':0 if i<3 else 50,'Collateral':0 if i<2 else 100}}
                for i in range(len(trace['actions'])+1)]
        if bad: frames[-1]['values']['Collateral']=0
        if intermediate: frames[3]['values']['Collateral']=0
        return {'status':'replayed','input_digest':digest(data),'trace_digest':digest(trace),
                'probes_digest':digest(probes),'frames':frames,
                'transactions':[{'action':a,'status':'success'} for a in trace['actions']]}
    return implementation


class AttackTests(unittest.TestCase):
    def setUp(self): self.snapshot,self.policy,self.submission=fixtures()

    def test_stale_snapshot_policy_and_unknown_requirement_rejected(self):
        for key,value in [('snapshot_digest','0'*64),('policy_digest','0'*64),('requirement_id','Unknown')]:
            submission=copy.deepcopy(self.submission); submission[key]=value
            with self.assertRaises(ValueError): submission_check(self.snapshot,self.policy,submission)
        policy=copy.deepcopy(self.policy); policy['snapshot_digest']='0'*64
        with self.assertRaises(ValueError): policy_check(self.snapshot,policy)

    def test_submitter_cannot_supply_a_predicate_or_rpc(self):
        for key in ('predicate','rpc_url','policy'):
            s=copy.deepcopy(self.submission); s[key]='attacker controlled'
            with self.assertRaises(ValueError): submission_check(self.snapshot,self.policy,s)
        s=copy.deepcopy(self.submission); s['trace']['rpc_url']='https://external.invalid'
        with self.assertRaises(ValueError): submission_check(self.snapshot,self.policy,s)

    def test_policy_target_quote_and_duplicate_probe_validation(self):
        for mutation in ('property','quote','label','expression'):
            policy=copy.deepcopy(self.policy)
            if mutation=='property': policy['requirements'][0]['property_id']='Missing'
            if mutation=='quote': policy['requirements'][0]['intent_quote']='invented intent'
            if mutation=='label': policy['probes'].append(policy['probes'][0])
            if mutation=='expression': policy['requirements'][0]['predicate']={'ref':'Missing'}
            with self.assertRaises(ValueError): policy_check(self.snapshot,policy)

    def test_boolean_integer_and_address_decoding(self):
        self.assertEqual(decode_scalar('0x'+format(50,'064x'),'uint256'),50)
        self.assertEqual(decode_scalar('0x'+format(2**256-1,'064x'),'int8'),-1)
        self.assertIs(decode_scalar('0x'+format(1,'064x'),'bool'),True)
        self.assertEqual(decode_scalar('0x'+format(1,'064x'),'address'),'0x'+'0'*39+'1')
        for raw,kind in [('0x','uint256'),('0x'+format(2,'064x'),'bool'),('0x'+format(256,'064x'),'uint8')]:
            with self.assertRaises(ValueError): decode_scalar(raw,kind)

    def test_predicates_are_typed_bounded_data(self):
        for expr in ({'op':'eval','args':['arbitrary code']},{'ref':'unknown'}):
            with self.assertRaises(ValueError): expression(expr,{'Debt'})
        with self.assertRaises(ValueError): evaluate({'op':'le','args':[True,1]}, {})
        with self.assertRaises(ValueError): evaluate({'op':'eq','args':[True,1]}, {})
        with self.assertRaises(ValueError): evaluate({'op':'and','args':[1,True]}, {})
        expr=True
        for _ in range(10): expr={'op':'not','args':[expr]}
        with self.assertRaises(ValueError): expression(expr,set())

    def test_malformed_trace_rejected_before_runtime(self):
        for change in (True,-1,10,'0'):
            trace=copy.deepcopy(self.submission['trace']); trace['actions'][0]['account']=change
            with self.assertRaises(ValueError): validate_trace(trace)

    def test_verified_state_not_attacker_observations_decides(self):
        captured=[]
        def runner(data,trace,output,probes=None):
            captured.append(trace); return mock_replay()(data,trace,output,probes)
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=runner):
            result=adjudicate(self.snapshot,self.policy,self.submission,Path(folder)/'attack')
            self.assertEqual(result['status'],'demonstrated_spec_requirement_violation')
            self.assertEqual(result['assessment']['violations'][0]['values'],{'Debt':50,'Collateral':0})
            self.assertFalse(result['accepted']); self.assertEqual(result['attack_acceptance'],'pending')
            self.assertEqual(captured[0]['observations'],[])
            self.assertIn('not_checked',result['formal_refutation'])

    def test_intermediate_violation_survives_later_recovery(self):
        replayed=mock_replay(False,True)(self.snapshot['material']['input'],self.submission['trace'],'unused')
        result=assess(self.policy['requirements'][0],replayed)
        self.assertEqual(result['violations'][0]['step'],3)

    def test_safe_execution_and_failed_replay_do_not_accept(self):
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=mock_replay(False)):
            result=adjudicate(self.snapshot,self.policy,self.submission,Path(folder)/'safe')
            self.assertEqual(result['status'],'not_demonstrated')
            with self.assertRaisesRegex(ValueError,'not accepted'):
                accept(self.snapshot,self.policy,self.submission,Path(folder)/'registry',Path(folder)/'accept','contract_bug','test')
        self.assertEqual(assess(self.policy['requirements'][0],{'status':'inconclusive'})['status'],'inconclusive')

    def test_missing_history_and_missing_matching_call_are_inconclusive(self):
        replayed=mock_replay()(self.snapshot['material']['input'],self.submission['trace'],'unused')
        replayed['frames'].pop()
        self.assertEqual(assess(self.policy['requirements'][0],replayed)['status'],'inconclusive')
        replayed=mock_replay()(self.snapshot['material']['input'],self.submission['trace'],'unused')
        req=copy.deepcopy(self.policy['requirements'][0]); req['step_scope']='after:never()'
        self.assertEqual(assess(req,replayed)['status'],'inconclusive')

    def test_proposed_intent_requirement_keeps_review_pending(self):
        policy=copy.deepcopy(self.policy); req=policy['requirements'][0]
        req.update(scope='intent',property_id='',review_status='pending')
        s=copy.deepcopy(self.submission); s['policy_digest']=digest(policy)
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=mock_replay()):
            result=adjudicate(self.snapshot,policy,s,Path(folder)/'attack')
            self.assertEqual(result['status'],'demonstrated_proposed_requirement_violation')
            with self.assertRaisesRegex(ValueError,'Review the operational'):
                accept(self.snapshot,policy,s,Path(folder)/'registry',Path(folder)/'accept','spec_gap','test')

    def test_acceptance_deduplicates_notes_and_attribution(self):
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=mock_replay()):
            registry=Path(folder)/'registry'
            first=accept(self.snapshot,self.policy,self.submission,registry,Path(folder)/'first','contract_bug','test')
            s=copy.deepcopy(self.submission); s['contributor']='second'; s['reasoning']='different prose'
            second=accept(self.snapshot,self.policy,s,registry,Path(folder)/'second','contract_bug','reproduction')
            self.assertEqual(first['attack_acceptance'],'accepted'); self.assertEqual(second['attack_acceptance'],'duplicate')
            self.assertEqual(first['regression_case_id'],second['regression_case_id'])
            self.assertEqual(len(list(registry.glob('*.json'))),1)

    def test_regression_retains_original_requirement_after_target_removed(self):
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=mock_replay()):
            registry=Path(folder)/'registry'
            accept(self.snapshot,self.policy,self.submission,registry,Path(folder)/'accept','contract_bug','test')
            candidate=copy.deepcopy(self.snapshot['material']['specification'])
            candidate['properties']=[dict(p,proof='by sorry') for p in candidate['properties'] if p['id']!='CollateralLock']
            revised=freeze(self.snapshot['material']['input'],candidate)
            report=regress(revised,registry,Path(folder)/'regress')
            self.assertEqual(report['cases'][0]['status'],'still_violates_original_requirement')
            self.assertTrue(report['cases'][0]['mapping_changed'])
            with patch('general.attacks.replay',side_effect=mock_replay(False)):
                report=regress(revised,registry,Path(folder)/'safe-regress')
            self.assertEqual(report['cases'][0]['status'],'requires_mapping_review')

    def test_corrupt_registry_and_changed_intent_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch('general.attacks.replay',side_effect=mock_replay()):
            registry=Path(folder)/'registry'
            accept(self.snapshot,self.policy,self.submission,registry,Path(folder)/'accept','contract_bug','test')
            candidate=copy.deepcopy(self.snapshot['material']['specification'])
            candidate['properties']=[dict(p,proof='by sorry') for p in candidate['properties']]
            data=copy.deepcopy(self.snapshot['material']['input']); data['intent']+=' new meaning'
            with self.assertRaisesRegex(ValueError,'changes intent'):
                regress(freeze(data,candidate),registry,Path(folder)/'changed')
            path=next(registry.glob('*.json')); payload=read(path); payload['material']['requirement']['predicate']=True
            path.write_text(__import__('json').dumps(payload))
            with self.assertRaisesRegex(ValueError,'Corrupt'):
                regress(self.snapshot,registry,Path(folder)/'corrupt')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.policy, self.submission = fixtures()
        self.draft = copy.deepcopy(self.policy); self.draft['requirements'][0]['review_status'] = 'pending'
        self.decisions = {'version':'policy-review-v1', 'snapshot_digest':self.snapshot['digest'],
                          'policy_digest':digest(self.draft), 'creator':'fixture-creator',
                          'decisions':[{'requirement_id':'CollateralBacking', 'decision':'approved',
                                        'reason':'Matches the intended withdrawal protection.'}]}

    def proposal(self, folder):
        return propose(self.snapshot, self.draft, Path(folder)/'proposal')

    def test_proposal_requires_pending_requirements_and_shows_review_material(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'pending review'):
                propose(self.snapshot, self.policy, Path(folder)/'no')
            packet = self.proposal(folder)
            item = packet['review_items'][0]
            self.assertEqual(item['intent_quote'], self.draft['requirements'][0]['intent_quote'])
            self.assertEqual(item['lean_mapping']['property_id'], 'CollateralLock')
            self.assertIn('statement', item['lean_mapping'])
            self.assertEqual([f['label'] for f in item['observed_state_fields']], ['Debt', 'Collateral'])
            self.assertEqual(packet['creator_approval'], 'pending')
            self.assertFalse(packet['accepted'])
            self.assertEqual(packet['decision_template']['decisions'][0]['requirement_id'], 'CollateralBacking')
            self.assertTrue((Path(folder)/'proposal'/'review.html').exists())

    def test_decisions_must_bind_to_the_proposed_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            packet = self.proposal(folder)
            for mutation in ('version', 'snapshot', 'policy', 'missing', 'unknown', 'reason'):
                decisions = copy.deepcopy(self.decisions)
                if mutation == 'version': decisions['version'] = 'other'
                elif mutation == 'snapshot': decisions['snapshot_digest'] = '0'*64
                elif mutation == 'policy': decisions['policy_digest'] = '0'*64
                elif mutation == 'missing': decisions['decisions'] = []
                elif mutation == 'unknown':
                    decisions['decisions'] = decisions['decisions'] + [{'requirement_id':'Invented', 'decision':'approved', 'reason':'extra'}]
                elif mutation == 'reason': decisions['decisions'][0]['reason'] = ''
                with self.assertRaises(ValueError):
                    creator_review(self.snapshot, packet, decisions, Path(folder)/'review')

    def test_review_excludes_rejected_requirements_and_keeps_invariants(self):
        with tempfile.TemporaryDirectory() as folder:
            packet = self.proposal(folder)
            decisions = copy.deepcopy(self.decisions)
            decisions['decisions'][0]['decision'] = 'rejected'
            record = creator_review(self.snapshot, packet, decisions, Path(folder)/'review')
            self.assertEqual(record['rejected_requirements'], ['CollateralBacking'])
            self.assertEqual(record['approved_policy']['requirements'], [])
            self.assertEqual(record['creator_approval'], 'pending')
            self.assertFalse(record['accepted'])
            self.assertEqual(record['contract_correspondence'], 'not_proved')

    def test_approved_policy_supports_the_full_contribution_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            packet = self.proposal(folder)
            record = creator_review(self.snapshot, packet, self.decisions, Path(folder)/'review')
            reviewed = record['approved_policy']
            self.assertEqual(reviewed['requirements'][0]['review_status'], 'approved')
            submission = copy.deepcopy(self.submission)
            submission['policy_digest'] = digest(reviewed)
            with patch('general.attacks.replay', side_effect=mock_replay()):
                result = adjudicate(self.snapshot, reviewed, submission, Path(folder)/'attack')
                self.assertEqual(result['status'], 'demonstrated_spec_requirement_violation')
                accepted = accept(self.snapshot, reviewed, submission, Path(folder)/'registry',
                                  Path(folder)/'accept', 'contract_bug', 'reviewed fixture')
                self.assertEqual(accepted['attack_acceptance'], 'accepted')
                self.assertEqual(len(list((Path(folder)/'registry').glob('*.json'))), 1)


class EscrowFixtureTests(unittest.TestCase):
    def test_escrow_family_fixtures_validate(self):
        snapshot = validate_snapshot(read(ROOT/'general/fixtures/escrow/snapshot.json'))
        policy = read(ROOT/'general/fixtures/escrow/draft-policy.json')
        policy_check(snapshot, policy)
        self.assertTrue(all(r['review_status'] == 'pending' for r in policy['requirements']))
        for name in ('attack-safe', 'attack-double-release', 'attack-other-payer'):
            submission = read(ROOT/'general/fixtures/escrow'/(name + '.json'))
            submission_check(snapshot, policy, submission)
        for requirement in policy['requirements']:
            self.assertIn(requirement['intent_quote'], snapshot['material']['input']['intent'])
            if requirement['scope'] == 'spec':
                ids = {p['id'] for p in snapshot['material']['specification']['properties']}
                self.assertIn(requirement['property_id'], ids)


if __name__ == '__main__': unittest.main()
