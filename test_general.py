import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from general.core import (freeze, validate_snapshot, digest, theorem_source,
                          counterexample_snapshot, observation_snapshot, review_check, validate_model)
from general.pipeline import run


def fixtures():
    data = {'id':'Unseen', 'intent':'Only owner may withdraw', 'contract_source':'contract Unseen {}'}
    prop = {'id':'Authorization', 'requirement':'Unauthorized callers cannot reduce the balance',
            'intent_basis':'Explicit creator requirement', 'statement':'∀ owner caller balance : Nat, caller ≠ owner → spend owner caller balance = balance',
            'explanation':'Unauthorized callers leave funds unchanged', 'proof':'by intros; simp [spend, *]'}
    candidate = {'status':'supported', 'summary':'Owner access model', 'threat_model':['Malicious caller'],
                 'model_body':'def spend (owner caller balance : Nat) : Nat := if caller = owner then 0 else balance',
                 'properties':[prop], 'assumptions':[], 'unresolved_questions':[], 'execution_gaps':['No EVM correspondence']}
    return data, candidate


class GeneralTests(unittest.TestCase):
    def setUp(self): self.data, self.candidate = fixtures(); self.snapshot = freeze(self.data, self.candidate)

    def test_frozen_closure_includes_contract_intent_model_and_target(self):
        for key in ('contract_source', 'intent'):
            data = copy.deepcopy(self.data); data[key] += ' changed'
            self.assertNotEqual(freeze(data, self.candidate)['digest'], self.snapshot['digest'])
        candidate = copy.deepcopy(self.candidate); candidate['model_body'] += '\ndef extra : Nat := 1'
        self.assertNotEqual(freeze(self.data, candidate)['digest'], self.snapshot['digest'])
        candidate = copy.deepcopy(self.candidate); candidate['properties'][0]['statement'] = 'True'
        self.assertNotEqual(freeze(self.data, candidate)['digest'], self.snapshot['digest'])

    def test_proof_revision_does_not_change_reviewed_target(self):
        candidate = copy.deepcopy(self.candidate); candidate['properties'][0]['proof'] = 'by sorry'
        self.assertEqual(freeze(self.data, candidate), self.snapshot)

    def test_changed_sources_rejected_even_with_recomputed_hash(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['material']['challenge_source'] = 'theorem changed : True := by trivial'
        snapshot['digest'] = digest(snapshot['material'])
        with self.assertRaisesRegex(ValueError, 'Frozen sources'): validate_snapshot(snapshot)

    def test_policy_change_rejected_even_with_recomputed_hash(self):
        snapshot = copy.deepcopy(self.snapshot); snapshot['material']['axioms'].append('sorryAx')
        snapshot['digest'] = digest(snapshot['material'])
        with self.assertRaisesRegex(ValueError, 'policy'): validate_snapshot(snapshot)

    def test_creator_approval_cannot_be_forged(self):
        snapshot = copy.deepcopy(self.snapshot); snapshot['creator_approval'] = 'approved'
        with self.assertRaisesRegex(ValueError, 'does not grant'): validate_snapshot(snapshot)

    def test_negation_is_bound_to_exact_property(self):
        negative = counterexample_snapshot(self.snapshot, 'Authorization')
        self.assertEqual(negative['material']['specification']['properties'][0]['statement'],
                         '¬ (' + self.candidate['properties'][0]['statement'] + ')')
        with self.assertRaisesRegex(ValueError, 'Unknown property'): counterexample_snapshot(self.snapshot, 'Other')

    def test_stale_adversary_rejected(self):
        with self.assertRaisesRegex(ValueError, 'different candidate'):
            review_check(self.snapshot, {'candidate_digest':'wrong', 'findings':[]})

    def test_model_metaprograms_and_hidden_commands_rejected(self):
        for source in ['def x : Nat := 0\ninitialize IO.println "hello"',
                       'def x : Nat := 0\n  set_option maxRecDepth 0',
                       'def x : Nat := by sorry', 'def x : Nat := 0\n  axiom bad : False',
                       'def x : Nat := 0\n@[extern "f"] def y : Nat := 1']:
            with self.assertRaises(ValueError): validate_model(source)

    def test_comment_text_does_not_execute(self):
        self.assertEqual(validate_model('-- unsafe IO\ndef x : Nat := 0 /- by sorry -/'), ['x'])
        with self.assertRaises(ValueError): validate_model('def x : Nat := 0 /- unclosed')

    def test_model_observation_is_separate_from_refutation(self):
        finding = {'reasoning':'Concrete model fact', 'observation_statement':'spend 1 2 10 = 10'}
        observed = observation_snapshot(self.snapshot, finding)
        self.assertEqual(observed['observes_digest'], self.snapshot['digest'])
        self.assertNotIn('refutes_property', observed)

    def test_unified_loop_keeps_approval_pending(self):
        responses = iter([{'candidate_digest':self.snapshot['digest'], 'summary':'No identified issue',
                           'findings':[], 'unresolved_questions':[]}])
        def agent(*args, **kwargs): return next(responses)
        with tempfile.TemporaryDirectory() as root:
            result = run(self.data, Path(root)/'run', rounds=1, candidate=self.candidate, skip=True, agent=agent)
            self.assertFalse(result['accepted'])
            self.assertEqual(result['creator_approval'], 'pending')
            self.assertEqual(result['rounds'][0]['proof_check']['status'], 'not_run')

    def test_counterexample_requires_a_target(self):
        finding = {'kind':'spec_gap', 'property_id':'', 'evidence_kind':'model_counterexample', 'proof':'by decide'}
        with self.assertRaisesRegex(ValueError, 'needs a target'):
            review_check(self.snapshot, {'candidate_digest':self.snapshot['digest'], 'findings':[finding]})



class ProtectedBackendTests(unittest.TestCase):
    def test_no_editable_definition_holes_and_judge_has_no_source(self):
        from general import backend
        from general.core import read
        data,candidate=fixtures(); snapshot=freeze(data,candidate)
        calls=[]
        def isolated(inputs, outputs, timeout=180):
            request=read(inputs/'request.json'); calls.append(request['mode'])
            if request['mode']=='export':
                (outputs/'proof.export').write_text('inert mock export')
            else:
                config=read(inputs/'comparator.json')
                self.assertEqual(config['definition_names'],[])
                self.assertEqual(config['permitted_axioms'],['propext','Quot.sound','Classical.choice'])
                self.assertEqual(set(config['external_kernels']),{'nanoda','con-ron'})
                self.assertFalse((inputs/'Model.lean').exists())
                self.assertFalse((inputs/'Solution.lean').exists())
            return 0,'mock backend; control-flow test only'
        with tempfile.TemporaryDirectory() as root, patch('general.backend.container',side_effect=isolated), patch('general.backend.shutil.which',return_value='/mock/docker'):
            backend.verify(snapshot,theorem_source(snapshot['material']['specification'],{'Authorization':'by sorry'}),root)
        self.assertEqual(calls,['export','export','judge'])

    def test_coverage_assessor_cannot_award_unrelated_formal_evidence(self):
        from general.benchmark import score_case
        data,candidate=fixtures()
        report={'rounds':[{'candidate':candidate,'proof_check':{'status':'proved'},'findings':[]}]}
        rubric=[{'id':'Critical'}]
        judged={'criteria':[{'id':'Critical','covered':True,'property_id':'Unrelated','reasoning':'wrong mapping'}]}
        self.assertEqual(score_case(report,judged,rubric)['score'],0)
        judged['criteria'][0]['id']='ChangedCriterion'
        with self.assertRaisesRegex(ValueError,'rubric IDs'): score_case(report,judged,rubric)

class WitnessFormatTests(unittest.TestCase):
    def test_full_module_is_unwrapped_only_for_exact_target(self):
        from general.core import proof_term
        source='module\npublic import Model\npublic section\nnamespace AutoSpec\ntheorem example : ¬ (1 = 0) := by decide\nend AutoSpec'
        self.assertEqual(proof_term(source,'¬ (1 = 0)'), 'by decide')
        with self.assertRaisesRegex(ValueError,'expected'):
            proof_term(source,'¬ (1 = 1)')

if __name__ == '__main__': unittest.main()
