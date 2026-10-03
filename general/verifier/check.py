#!/usr/bin/env python3
"""Runs only inside the pinned, restricted outer container.

Export and adjudication are separate container invocations. Adjudication processes
inert exports only: it never builds participant code or reads their Lake config.
"""
import json
import pathlib
import shutil
import subprocess
import sys

WORK = pathlib.Path('/work')
OUTPUT = pathlib.Path('/output')
SEEDS = "propext Quot.sound Classical.choice Quot Quot.mk Quot.lift Quot.ind Nat.add Nat.sub Nat.mul Nat.pow Nat.gcd Nat.div Nat.mod Nat.beq Nat.ble Nat.land Nat.lor Nat.xor Nat.shiftLeft Nat.shiftRight String.ofList Char.ofNat List eagerReduce Nat String String.mk Char optParam autoParam semiOutParam outParam".split()


def run(command, timeout=90):
    result = subprocess.run(command, cwd=WORK, capture_output=True, text=True, timeout=timeout)
    with (OUTPUT/'checker.log').open('a') as log:
        log.write('$ ' + ' '.join(command) + '\n' + result.stdout[-200000:] + result.stderr[-200000:])
    return result.returncode


def main():
    request = json.loads(pathlib.Path('/input/request.json').read_text())
    mode = request['mode']
    if mode == 'export':
        module = request['module']
        if module not in ('Challenge', 'Solution'): raise ValueError('Invalid module')
        for name in ('Model.lean', module + '.lean', 'lakefile.toml'):
            shutil.copyfile(pathlib.Path('/input')/name, WORK/name)
        code = run(['lake', 'update'])
        if code == 0: code = run(['lake', 'build', module])
        if code == 0:
            # This subprocess may evaluate participant metaprograms. It has only
            # this container's disposable workspace, never the protected target.
            with (OUTPUT/'proof.export').open('w') as export:
                result = subprocess.run(['lake', 'env', 'leanexport', module, '--'] + request['targets'] + SEEDS,
                                        cwd=WORK, stdout=export, stderr=subprocess.PIPE, text=True, timeout=90)
            with (OUTPUT/'checker.log').open('a') as log: log.write(result.stderr[-200000:])
            code = result.returncode
        return code
    if mode != 'judge': raise ValueError('Invalid mode')
    for name in ('Challenge.export', 'Solution.export', 'comparator.json', 'lakefile.toml'):
        shutil.copyfile(pathlib.Path('/input')/name, WORK/name)
    # No source modules exist here and no participant build/config is loaded.
    # Both exports skip compilation. Outer Docker isolation replaces bwrap,
    # which cannot create nested namespaces on Docker Desktop. Never invoke
    # this flag on a host or with source compilation in the judging container.
    (WORK/'lake-manifest.json').write_text('{"version":"1.1.0","packagesDir":".lake/packages","packages":[],"name":"autoprove","lakeDir":".lake"}')
    return run(['lake', 'comparator', '--config', 'comparator.json',
                '--challenge-from-export', 'Challenge.export',
                '--solution-from-export', 'Solution.export', '--inadvisably-no-sandbox'])


if __name__ == '__main__':
    try: sys.exit(main())
    except (Exception, subprocess.TimeoutExpired) as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        sys.exit(2)
