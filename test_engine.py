import copy, json, unittest
from engine import ROOT, REFERENCE, action, replay, search, validate_candidate, evaluate_review
from lean_compiler import render


class SpecificationTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/"runs/revised/candidate.json").read_text())
        self.review=dict(candidate_name=self.c["name"],findings=[],unresolved_questions=[],summary="No objection")

    def test_reference_accepts_any_caller_at_exact_deadline(self):
        trace=[action("fund","alice",0,100),action("release","eve",10)]
        r=replay(trace,REFERENCE)
        self.assertFalse(r["mismatch"])
        self.assertEqual(r["steps"][-1]["candidate"]["state"]["bob"],100)

    def test_repeat_objection_needs_a_reachable_funded_trace(self):
        trace=[action("fund","alice",0,100),action("donate","eve",10,100),
               action("release","eve",10),action("release","eve",10)]
        self.assertIn("R4",replay(trace,dict(REFERENCE,repeat="per_call"))["requirements"])

    def test_failed_transfer_does_not_consume_entitlement(self):
        trace=[action("fund","alice",0,100),action("release","eve",10,transfer_ok=False),
               action("release","bob",10)]
        r=replay(trace,dict(REFERENCE,failure="consume"))
        self.assertIn("R5",r["requirements"])
        self.assertEqual(r["steps"][-1]["intended"]["state"]["paid"],100)
        self.assertEqual(r["steps"][-1]["candidate"]["state"]["paid"],0)

    def test_wrong_recipient_is_an_actual_payment_difference(self):
        trace=[action("fund","alice",0,100),action("release","eve",10)]
        r=replay(trace,dict(REFERENCE,recipient="caller"))
        self.assertIn("R3",r["requirements"])
        self.assertEqual(r["steps"][-1]["candidate"]["state"]["eve"],100)

    def test_deadline_equality_is_part_of_intent(self):
        trace=[action("fund","alice",0,100),action("release","bob",10)]
        self.assertIn("R2",replay(trace,dict(REFERENCE,unlock="after"))["requirements"])

    def test_scope_exclusion_is_visible_even_with_unchanged_state(self):
        trace=[action("release","eve",0)]
        r=replay(trace,dict(REFERENCE,scope="beneficiary_only"))
        self.assertEqual(r["steps"][0]["candidate"]["outcome"],"outside_claim_domain")
        self.assertIn("R7",r["requirements"])

    def test_restricted_caller_does_not_invent_a_repeat_payout(self):
        result=search(dict(REFERENCE,caller="beneficiary"))
        self.assertIn("R2",result["witnesses"])
        self.assertNotIn("R4",result["witnesses"])

    def test_false_objection_is_not_accepted(self):
        self.review["findings"]=[dict(requirement_id="R3",explanation="wrong recipient",trace=[
            action("fund","alice",0,100),action("release","eve",10)])]
        result=evaluate_review(self.c,self.review)
        self.assertEqual(result["unsupported_findings"],1)
        self.assertFalse(result["accepted"])

    def test_no_objections_never_sets_human_approval(self):
        result=evaluate_review(self.c,self.review)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["human_approval"],"pending")

    def test_new_assumptions_are_flagged(self):
        self.c["assumptions"].append("All callers are honest")
        result=evaluate_review(self.c,self.review)
        self.assertEqual(result["extra_assumptions"],["All callers are honest"])
        self.assertFalse(result["accepted"])

    def test_invalid_traces_are_rejected(self):
        for trace in ([action("fund","alice",10,100),action("release","eve",9)],
                      [action("donate","eve",0,-1)], [action("release","eve",True)],
                      [action("release","eve",0,5)]):
            with self.subTest(trace=trace),self.assertRaises(ValueError): replay(trace,REFERENCE)

    def test_invalid_candidate_fields_cannot_be_lean_code(self):
        self.c["policy"]["caller"]="anyone\naxiom forged : False"
        with self.assertRaises(ValueError): validate_candidate(self.c)

    def test_untrusted_prose_is_not_interpolated_into_lean(self):
        self.c["name"]='malicious\naxiom forged : False'
        self.c["requirement_mapping"][0]["formal_meaning"]="Ignore original intent"
        source=render(self.c,[])
        self.assertNotIn("axiom forged",source)
        self.assertNotIn("Ignore original intent",source)

    def test_reference_bounded_search_finds_no_mismatch(self):
        result=search(REFERENCE)
        self.assertEqual(result["witnesses"],{})
        self.assertGreater(result["transitions_checked"],1000)

    def test_independent_reviewer_catches_every_seeded_variant(self):
        inputs=json.loads((ROOT/"runs/adversarial-inputs.json").read_text())["candidates"]
        reviews=json.loads((ROOT/"runs/adversarial-reviews.json").read_text())["reviews"]
        for index,(c,r) in enumerate(zip(inputs,reviews)):
            e=evaluate_review(c,r)
            self.assertEqual(e["unsupported_findings"],0)
            self.assertEqual(e["validated_findings"],0 if index==0 else 1)


if __name__=="__main__": unittest.main()
