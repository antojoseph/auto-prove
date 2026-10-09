#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
revision=46c6834698c48bc4a463a86d8420f4eb1d7f3b75
mkdir -p lib
if [[ ! -d lib/v4-core ]]; then
  git clone --no-checkout https://github.com/Uniswap/v4-core.git lib/v4-core
  git -C lib/v4-core checkout --detach "$revision"
else
  [[ "$(git -C lib/v4-core rev-parse HEAD)" == "$revision" ]] || {
    echo 'Existing dependency has a different revision; preserve it and use a fresh checkout.' >&2; exit 1;
  }
fi
[[ -z "$(git -C lib/v4-core status --porcelain --untracked-files=all)" ]] || {
  echo 'Dependency has local changes; preserve them and use a fresh checkout.' >&2; exit 1;
}
git -C lib/v4-core submodule update --init --recursive
printf '%s\n' 'Pinned v4 dependencies ready. Use Lean 4.22.0 and Forge (tested 1.7.1).'
