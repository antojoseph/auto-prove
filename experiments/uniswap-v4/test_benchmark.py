import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('v4_benchmark', Path(__file__).with_name('benchmark.py'))
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

class HostedTests(unittest.TestCase):
 def evidence(self):
  return {'validation_completed': True, 'kernel_checked': True, 'abstract_all_traces_invariant_proved': True,
   'concrete_abstract_replay_agree': True, 'accepted': False, 'creator_approval': 'pending',
   'contract_correspondence': 'not_proved', 'objection_supported': True,
   'seeded': {'violations': ['R2', 'R3']}, 'repaired': {'violations': []}}
 def test_requirement_coverage_is_bounded_and_deduplicated(self):
  x=self.evidence(); self.assertEqual(benchmark.supported_score(x),2)
  x['seeded']['violations']=['R2','R2']; self.assertEqual(benchmark.supported_score(x),1)
 def test_unsupported_claim_has_no_credit(self):
  x=self.evidence();x['objection_supported']=False
  self.assertEqual(benchmark.supported_score(x),0)
 def test_missing_verification_and_approval_fail_closed(self):
  for key,value in [('kernel_checked',False),('accepted',True),('creator_approval','approved')]:
   x=self.evidence();x[key]=value
   with self.assertRaises(ValueError):benchmark.supported_score(x)
 def test_control_violation_is_rejected(self):
  x=self.evidence();x['repaired']['violations']=['R2']
  with self.assertRaises(ValueError):benchmark.supported_score(x)
 def test_participant_symlinks_and_extra_files_are_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'submission').mkdir(); (root/'real.json').write_text('{}')
   (root/'submission/trace.json').symlink_to(root/'real.json')
   with self.assertRaises(ValueError):benchmark.validate_surface(root)
   (root/'submission/trace.json').unlink();(root/'submission/trace.json').write_text('{}')
   self.assertEqual(benchmark.validate_surface(root),root/'submission/trace.json')
   (root/'submission/code.py').write_text('raise SystemExit(0)')
   with self.assertRaises(ValueError):benchmark.validate_surface(root)

if __name__=='__main__':unittest.main()
