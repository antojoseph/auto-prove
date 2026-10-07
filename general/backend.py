"""Protected targets, separate exports, then independent kernels in outer Docker."""
from __future__ import annotations
import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from .core import TOOLCHAIN, AXIOMS, validate_snapshot, validate_model, write

IMAGE = 'auto-prove-verifier:lean' + TOOLCHAIN
MAX_EXPORT = 64 * 1024 * 1024
LAKE = 'name = "autoprove"\nversion = "0.1.0"\n[[lean_lib]]\nname = "Model"\n[[lean_lib]]\nname = "Challenge"\n[[lean_lib]]\nname = "Solution"\n'


def container(input_dir, output_dir, timeout=180):
    name = 'auto-prove-' + uuid.uuid4().hex
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only', '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--pids-limit', '128', '--memory', '2g', '--cpus', '2',
               '--ulimit', 'fsize=67108864:67108864',
               '--tmpfs', '/work:rw,size=512m,uid=10001,gid=10001,mode=0700',
               '--tmpfs', '/tmp:rw,size=128m,mode=1777',
               '--mount', 'type=bind,source=' + str(input_dir) + ',target=/input,readonly',
               '--mount', 'type=bind,source=' + str(output_dir) + ',target=/output', IMAGE]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        log = output_dir/'checker.log'
        if log.is_symlink(): raise ValueError('Symlink checker log')
        content = log.read_text()[-200000:] if log.exists() and log.stat().st_size <= 2_000_000 else ''
        return result.returncode, content + result.stdout[-20000:] + result.stderr[-20000:]
    except subprocess.TimeoutExpired:
        return 2, 'Proof checker timed out; no acceptance.'
    finally:
        # A timed-out Docker CLI can leave its container running.
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=20)


def verify(snapshot, solution, output):
    validate_snapshot(snapshot)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    result = {'status': 'inconclusive', 'target_digest': snapshot['digest'],
              'kernel_checked': False, 'target_matched': False, 'independent_kernels': [],
              'isolation': 'separate network-free non-root Docker containers; no nested bwrap',
              'contract_correspondence': 'not_proved'}
    m = snapshot['material']; spec = m['specification']
    write(output/'snapshot.json', snapshot)
    (output/'Model.lean').write_text(m['model_source'])
    (output/'Challenge.lean').write_text(m['challenge_source'])
    (output/'Solution.lean').write_text(solution)
    names = ['AutoSpec.req_' + p['id'] for p in spec['properties']]
    definitions = ['AutoSpec.' + n for n in validate_model(spec['model_body'])]
    if not shutil.which('docker'):
        result['reason'] = 'Docker unavailable'; write(output/'result.json', result); return result
    with tempfile.TemporaryDirectory(prefix='auto-prove-') as temp:
        root = Path(temp); root.chmod(0o755)
        exports = {}
        for module, source in [('Challenge', m['challenge_source']), ('Solution', solution)]:
            inputs = root/(module+'-input'); outputs = root/(module+'-output')
            inputs.mkdir(mode=0o755); outputs.mkdir(mode=0o777); outputs.chmod(0o777)
            (inputs/'Model.lean').write_text(m['model_source'])
            (inputs/(module+'.lean')).write_text(source)
            (inputs/'lakefile.toml').write_text(LAKE)
            write(inputs/'request.json', {'mode':'export', 'module':module, 'targets':names + definitions})
            code, log = container(inputs, outputs)
            (output/(module+'.log')).write_text(log)
            exported = outputs/'proof.export'
            if code or not exported.exists() or exported.is_symlink() or not 0 < exported.stat().st_size <= MAX_EXPORT:
                result['reason'] = module + ' compilation/export failed; inspect log'
                write(output/'result.json', result); return result
            exports[module] = exported.read_bytes()
        inputs = root/'judge-input'; outputs = root/'judge-output'
        inputs.mkdir(mode=0o755); outputs.mkdir(mode=0o777); outputs.chmod(0o777)
        for module, data in exports.items(): (inputs/(module+'.export')).write_bytes(data)
        (inputs/'lakefile.toml').write_text(LAKE)
        write(inputs/'request.json', {'mode':'judge'})
        write(inputs/'comparator.json', {'challenge_module':'Challenge', 'solution_module':'Solution',
              # Comparator's definition_names are EDITABLE definition holes,
              # not definitions to freeze. No participant holes are permitted.
              'theorem_names':names, 'definition_names':[], 'permitted_axioms':AXIOMS,
              'external_kernels':{'nanoda':['/opt/lean/bin/nanoda_bin'], 'con-ron':['/opt/lean/bin/con-ron']}})
        code, log = container(inputs, outputs)
        (output/'comparator.log').write_text(log)
        if code == 0:
            # Native Comparator's zero status requires every configured kernel,
            # the target comparison and the permitted-axiom check to pass.
            result.update(status='proved', kernel_checked=True, target_matched=True,
                          independent_kernels=['nanoda', 'con-ron'])
        elif code == 1:
            result.update(status='rejected', reason='Target, axiom policy or kernel check rejected the proof')
        else:
            result['reason'] = 'Comparator could not complete; inspect log'
    write(output/'result.json', result)
    return result
