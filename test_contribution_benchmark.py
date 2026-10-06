import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from general.core import read
from general import contribution_benchmark

ROOT = Path(__file__).resolve().parent


def challenge_files():
    snapshot = read(ROOT/'challenge/snapshot.json')
    policy = read(ROOT/'challenge/policy.json')
    contribution = read(ROOT/'submission/contributions/baseline-double-release.json')
    return snapshot, policy, contribution


def report(both=True, replayed=True):
    checks = {'ReleaseWithinDeposit': {'status': 'demonstrated_violation' if both else 'not_demonstrated'},
              'OtherPayerBacking': {'status': 'demonstrated_violation'}}
    return {'status': 'demonstrated_spec_requirement_violation' if both else 'not_demonstrated',
            'assessment': {'status': 'demonstrated_violation' if both else 'not_demonstrated'},
            'all_requirement_checks': checks,
            'replay': {'status': 'replayed' if replayed else 'inconclusive', 'reason': 'compiler missing'}}


class ContributionBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.policy, self.contribution = challenge_files()

    def write_submission(self, folder, contributions=None, formal=None):
        submission = Path(folder)/'submission'
        (submission/'contributions').mkdir(parents=True)
        for name, contribution in (contributions or {'baseline.json': self.contribution}).items():
            (submission/'contributions'/name).write_text(json.dumps(contribution, indent=2))
        if formal is not None:
            (submission/'formal.json').write_text(json.dumps(formal, indent=2))
        return submission

    def score(self, folder, contributions=None, formal=None, adjudicate=None, evidence=None):
        submission = self.write_submission(folder, contributions, formal)
        adjudator = adjudicate or (lambda *a: report())
        evidencer = evidence or (lambda *a: {'status': 'supported_model_counterexample',
                                             'independent_kernels': ['nanoda', 'con-ron']})
        with tempfile.TemporaryDirectory() as output:
            with patch('general.contribution_benchmark.adjudicate', side_effect=adjudator), \
                 patch('general.contribution_benchmark.evidence', side_effect=evidencer):
                return contribution_benchmark.score(Path(ROOT/'challenge'), submission, Path(output)/'evidence',
                                                    Path(folder)/'score.json')

    def test_baseline_scores_both_requirement_pairs(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.score(folder)
            self.assertEqual(result['score'], 2)
            self.assertEqual(len(result['metrics']['distinct_requirement_case_pairs']), 2)
            self.assertFalse(result['metrics']['accepted'])
            self.assertEqual(result['metrics']['creator_approval'], 'pending')
            self.assertEqual(result['metrics']['contract_correspondence'], 'not_proved')

    def test_kernel_checked_refutation_adds_five(self):
        formal = {'property_id': 'ReleasedWithinDeposit', 'proof': 'by decide'}
        with tempfile.TemporaryDirectory() as folder:
            result = self.score(folder, formal=formal)
            self.assertEqual(result['score'], 7)
            self.assertEqual(result['metrics']['kernel_checked_refutations'][0]['property_id'], 'ReleasedWithinDeposit')

    def test_unchecked_formal_evidence_fails_closed(self):
        formal = {'property_id': 'ReleasedWithinDeposit', 'proof': 'bogus'}
        unchecked = {'status': 'inconclusive', 'reason': 'compile failed'}
        with tempfile.TemporaryDirectory() as folder:
            submission = self.write_submission(folder, formal=formal)
            with tempfile.TemporaryDirectory() as output, \
                 patch('general.contribution_benchmark.adjudicate', side_effect=lambda *a: report()), \
                 patch('general.contribution_benchmark.evidence', return_value=unchecked):
                with self.assertRaisesRegex(SystemExit, 'kernel-checked'):
                    contribution_benchmark.score(Path(ROOT/'challenge'), submission, Path(output)/'evidence',
                                                Path(folder)/'score.json')
            self.assertFalse((Path(folder)/'score.json').exists())

    def test_nondemonstrating_contribution_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            submission = self.write_submission(folder)
            with tempfile.TemporaryDirectory() as output, \
                 patch('general.contribution_benchmark.adjudicate', side_effect=lambda *a: report(both=False)):
                with self.assertRaisesRegex(SystemExit, 'does not demonstrate'):
                    contribution_benchmark.score(Path(ROOT/'challenge'), submission, Path(output)/'evidence',
                                                Path(folder)/'score.json')
            self.assertFalse((Path(folder)/'score.json').exists())

    def test_inconclusive_replay_rejects(self):
        with tempfile.TemporaryDirectory() as folder:
            submission = self.write_submission(folder)
            with tempfile.TemporaryDirectory() as output, \
                 patch('general.contribution_benchmark.adjudicate', side_effect=lambda *a: report(replayed=False)):
                with self.assertRaisesRegex(SystemExit, 'inconclusive'):
                    contribution_benchmark.score(Path(ROOT/'challenge'), submission, Path(output)/'evidence',
                                                Path(folder)/'score.json')
            self.assertFalse((Path(folder)/'score.json').exists())

    def test_duplicate_case_across_files_scores_once(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.score(folder, contributions={
                'a.json': self.contribution,
                'b.json': copy.deepcopy(self.contribution)})
            self.assertEqual(result['score'], 2)
            self.assertEqual(len(result['metrics']['contributions']), 2)


if __name__ == '__main__': unittest.main()
