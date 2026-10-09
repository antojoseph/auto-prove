#!/usr/bin/env python3
"""Fail-closed hosted adapter. Input is one data-only trace, never participant code."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).resolve().parent
SCORE = ROOT / '.yukon/score.json'

def supported_score(evidence):
 for flag in ('validation_completed', 'kernel_checked', 'abstract_all_traces_invariant_proved', 'concrete_abstract_replay_agree'):
  if evidence.get(flag) is not True: raise ValueError('Incomplete verification: ' + flag)
 if evidence.get('accepted') is not False or evidence.get('creator_approval') != 'pending':
  raise ValueError('Semantic approval must remain pending')
 if evidence.get('contract_correspondence') != 'not_proved': raise ValueError('Incorrect proof scope')
 if evidence['repaired']['violations']: raise ValueError('Repaired control violated requirements')
 violations = set(evidence['seeded']['violations'])
 if not violations <= {'R2', 'R3'}: raise ValueError('Unknown scored requirement')
 # Require the submission's stated objection to be demonstrated before awarding coverage.
 if not evidence.get('objection_supported'): return 0
 return len(violations)

def validate_surface(root):
 directory = root / 'submission'
 trace = directory / 'trace.json'
 if directory.is_symlink() or not directory.is_dir(): raise ValueError('Submission must be a directory')
 if trace.is_symlink() or not trace.is_file(): raise ValueError('Submission must be a regular trace.json file')
 if sorted(p.name for p in directory.iterdir()) != ['trace.json']:
  raise ValueError('Only submission/trace.json is permitted')
 return trace

def main():
 SCORE.unlink(missing_ok=True)
 trace = validate_surface(ROOT)
 runtimes = json.loads((ROOT/'.tools/v4/runtime.json').read_text())
 env = {**os.environ, **{'V4_'+name.upper(): path for name, path in runtimes.items()}}
 out = ROOT/'runs'/('reproduced-v4-hosted-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
 subprocess.run([sys.executable, str(BASE/'run.py'), str(trace), '--output', str(out)], cwd=ROOT, env=env, check=True)
 evidence = json.loads((out/'evidence.json').read_text())
 score = supported_score(evidence)
 result = {'score': score, 'metrics': {'requirements_demonstrated': score, 'maximum': 2,
           'kernel_checked': True, 'accepted': False, 'creator_approval': 'pending',
           'contract_correspondence': 'not_proved', 'evidence': str(out.relative_to(ROOT))}}
 SCORE.parent.mkdir(exist_ok=True)
 temporary = SCORE.with_suffix('.tmp')
 temporary.write_text(json.dumps(result, indent=2)+'\n')
 temporary.replace(SCORE)
 print(json.dumps(result, indent=2))

if __name__ == '__main__': main()
