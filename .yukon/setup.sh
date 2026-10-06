#!/usr/bin/env bash
# Setup for the spec.prove contribution benchmark. This is the ONLY step that
# may use the network. Everything is installed into repository-relative paths
# because environment variables do NOT persist between Yukon's setupCommand
# and benchmarkCommand; run.sh re-derives the paths from the repo root.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

command -v python3 >/dev/null
python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
command -v docker >/dev/null
docker build -t auto-prove-verifier:lean4.35.0-rc2 general/verifier

# Pinned Foundry 1.7.1 (anvil + cast) into .tools/foundry.
if [[ ! -x .tools/foundry/bin/anvil ]]; then
  mkdir -p .tools
  curl --fail --silent --show-error --location \
    https://raw.githubusercontent.com/foundry-rs/foundry/master/foundryup/install \
    --output "$root/.tools/foundryup-install.sh"
  FOUNDRY_DIR="$root/.tools/foundry" bash "$root/.tools/foundryup-install.sh"
  FOUNDRY_DIR="$root/.tools/foundry" "$root/.tools/foundry/bin/foundryup" -i v1.7.1
fi
anvil_version="$("$root/.tools/foundry/bin/anvil" --version)"
cast_version="$("$root/.tools/foundry/bin/cast" --version)"
grep -q '1\.7\.1' <<<"$anvil_version" || { echo "anvil is not 1.7.1: $anvil_version" >&2; exit 1; }
grep -q '1\.7\.1' <<<"$cast_version" || { echo "cast is not 1.7.1: $cast_version" >&2; exit 1; }

# Pinned Solidity 0.8.28, checksum-verified, into .tools/solc.
if [[ ! -x .tools/solc/solc ]]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64|Darwin-x86_64)
      file="solc-macosx-amd64-v0.8.28+commit.7893614a"
      sha="81515b0e53deaa266d549545ccaac0a5a96e6d4e8201c77f673b2c710976d9ea" ;;
    Linux-x86_64)
      file="solc-linux-amd64-v0.8.28+commit.7893614a"
      sha="9a0fb7e0db2c0641dbae1c5cc645dc686820c83af516226abb1c0a2f76636f25" ;;
    *)
      echo "unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
  esac
  mkdir -p .tools/solc
  case "$(uname -s)" in
    Darwin) base="https://binaries.soliditylang.org/macosx-amd64" ;;
    Linux)  base="https://binaries.soliditylang.org/linux-amd64" ;;
  esac
  curl --fail --silent --show-error --location "$base/$file" --output .tools/solc/solc
  echo "$sha  .tools/solc/solc" | shasum -a 256 --check
  chmod +x .tools/solc/solc
fi
solc_version="$(.tools/solc/solc --version)"
grep -q '0\.8\.28' <<<"$solc_version" || { echo "solc is not 0.8.28: $solc_version" >&2; exit 1; }

echo "setup complete: foundry 1.7.1, solc 0.8.28, verifier image built"
