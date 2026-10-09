#!/usr/bin/env python3
"""Install checksum-pinned verifier runtimes; persist paths for separate Yukon commands."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / '.tools/v4'
RELEASES = {
 ('Linux', 'x86_64'): {
  'forge': ('https://github.com/foundry-rs/foundry/releases/download/v1.7.1/foundry_v1.7.1_linux_amd64.tar.gz', 'cf7e688ed0c4c48adffca788b496076e31060b67ac5afe1e43dbb5499c20c88b'),
  'lean': ('https://github.com/leanprover/lean4/releases/download/v4.22.0/lean-4.22.0-linux.tar.zst', '85097a4d659fe388193a5efb0c413b880e101f1290cc41d00eb60847b18f064e'),
  'solc': ('https://raw.githubusercontent.com/ethereum/solc-bin/gh-pages/linux-amd64/solc-linux-amd64-v0.8.26+commit.8a97fa7a', 'd5f23436f443edb85d8e76906d12f0a86ce0490e7663a9e608efeb7a93f149ef'),
 },
 ('Darwin', 'arm64'): {
  'forge': ('https://github.com/foundry-rs/foundry/releases/download/v1.7.1/foundry_v1.7.1_darwin_arm64.tar.gz', 'eacdc67718fac857cad9e19c7f6729dd80de731d09df81856391d093cfcab547'),
  'lean': ('https://github.com/leanprover/lean4/releases/download/v4.22.0/lean-4.22.0-darwin_aarch64.tar.zst', '84b21a78dc2d3b08b235178faeee4da5c650dad5a9fcafb121022a697d6c56e2'),
  'solc': ('https://raw.githubusercontent.com/ethereum/solc-bin/gh-pages/macosx-amd64/solc-macosx-amd64-v0.8.26+commit.8a97fa7a', '0ff016aef2396b12d1fc65429d8ea6cf53c2ee4b041bb8925644615ee1c30ab9'),
 },
}
VERSIONS = {'forge': '1.7.1', 'lean': '4.22.0', 'solc': '0.8.26'}

def main():
 if sys.version_info < (3, 9):
  raise SystemExit('Python 3.9+ required')
 releases = RELEASES.get((platform.system(), platform.machine()))
 if releases is None:
  raise SystemExit('Supported setup platforms: Linux x86_64 and macOS arm64')
 DEST.mkdir(parents=True, exist_ok=True)
 runtimes = {}
 for tool, (url, expected) in releases.items():
  override = os.environ.get('V4_' + tool.upper())
  if override:
   executable = Path(override).absolute()
  else:
   directory = DEST/tool
   executable = directory/('bin/lean' if tool == 'lean' else tool)
   if not executable.exists():
    archive = DEST/(tool + ('.tar.zst' if tool == 'lean' else '.tar.gz' if tool == 'forge' else '.download'))
    subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(archive), url], check=True)
    with archive.open('rb') as stream:
     digest = hashlib.sha256()
     for block in iter(lambda: stream.read(1024*1024), b''): digest.update(block)
    if digest.hexdigest() != expected: raise ValueError(tool + ' checksum mismatch')
    directory.mkdir(exist_ok=True)
    if tool == 'solc':
     archive.replace(executable); executable.chmod(0o755)
    else:
     args = ['tar', '-xf', str(archive), '-C', str(directory)]
     if tool == 'lean': args += ['--strip-components=1']
     subprocess.run(args, check=True)
     archive.unlink()
  version = subprocess.check_output([str(executable), '--version'], text=True)
  if not re.search(r'\b' + re.escape(VERSIONS[tool]) + r'(?:[+\s,)]|$)', version): raise ValueError('Wrong '+tool+' version')
  runtimes[tool] = str(executable)
 (DEST/'runtime.json').write_text(json.dumps(runtimes, indent=2)+'\n')
 print('Pinned runtimes ready: Foundry 1.7.1, Lean 4.22.0, Solidity 0.8.26')

if __name__ == '__main__': main()
