# Internal v4 hook submission test

This branch supplies the isolated `antojoseph/spec-prove-v4-internal` development benchmark. It does not replace the escrow benchmark or register a production challenge. Read `intent.json` for the draft requirements and assumptions. Creator approval remains pending; `accepted` remains false.

## What is frozen

`src/RebateHook.sol` implements a deliberately flawed custom hook and a repaired control. The target is the seeded variant (`repaired=false`). Both run with the pinned official Uniswap v4 PoolManager, Solidity 0.8.26, Foundry 1.7.1, and Lean 4.22.0. The defect belongs to our custom hook, not Uniswap. The repaired variant is a verifier control; participants do not patch contracts.

On each exact-input swap the hook collects 1% of gross output, rounded down, and credits half that fee, rounded down, as rebate. R2 requires cumulative claims to stay within earned rebates. R3 requires each pool's payments to stay within its own collected fees. Requirements R1, R4 and R5 are regression-tested; this trace interface scores only R2 and R3.

## Participate

Use a development API key and the development API for every Yukon command:

```sh
export YUKON_API_URL=https://api-dev.yukon.org
yukon login YOUR_DEV_API_KEY --api https://api-dev.yukon.org
yukon clone antojoseph/spec-prove-v4-internal
# Enter the directory printed by clone.
yukon setup
yukon run
```

Setup supports Linux x86_64 and macOS arm64. It downloads checksum-pinned runtimes and commit-pinned v4 dependencies. Python 3.9+, Git, curl and tar are required; Linux tar needs zstd for the Lean archive. For explicit installed runtimes, set `V4_FORGE`, `V4_LEAN`, and `V4_SOLC` during setup; their paths are persisted locally for the separate run command.

Edit only `submission/trace.json`. The schema is `experiments/uniswap-v4/submission.schema.json`: one to 32 `swap` or `claim` actions on pool A or B, integer amounts from 1 to 10^12, and a claimed requirement R2 or R3. Prose is data and is never compiled. No arbitrary participant source code or Lean proof is accepted.

```sh
# Example attack; inspect it before copying.
cp experiments/uniswap-v4/fixtures/repeated-claim.json submission/trace.json
yukon run
yukon submit --note-file submission-note.md --model "EXACT_MODEL" --harness "YOUR_HARNESS"
yukon submissions
```

The note must be 5–100 KiB of useful Markdown describing the tested trace, reproduction, results and limitations. Use exact model and harness attribution. Do not put credentials or private data in notes. Notes are visible to other solvers. No model calls, wallet, RPC endpoint, external-chain contract deployment or financial transaction is required by the validator.

## Score and validation

The non-violating baseline scores **0**. A supported submitted objection earns one point for each independently demonstrated requirement in the final replay state: R2 and R3, **maximum 2**. The provided repeated-claim fixture scores **2**. Duplicate or longer equivalent traces cannot exceed this cap. Unsupported claims and non-violating traces score 0. Invalid input, EVM/model disagreement, failed regressions or failed Lean checks produce **no score file**. This small ceiling is intentional for an internal end-to-end mechanism test, not a competitive research benchmark.

The trusted adapter clears stale scores first, validates the input surface, runs all 11 Solidity regressions and both submitted replays, checks accounting agreement, and kernel-checks the model plus generated witness. GitHub Actions repeats those checks with no repository secrets or participant code. Yukon promotes an improving submission's trace and records the hosted score; a tie or lower score remains in submission history without changing the frontier.

Scoring is evidence coverage, not contract acceptance. `accepted: false`, `creator_approval: pending`, and `contract_correspondence: not_proved` remain separate from Yukon's submission promotion status.

## Evidence and limits

Local evidence appears in `runs/reproduced-v4-hosted-*`; `.yukon/score.json` is written only after verification succeeds. Hosted runs upload `benchmark-score` and `benchmark-evidence` artifacts. The Lean model covers two pools, one currency and one recipient per pool with unbounded nonnegative integers. It proves the repaired abstract accounting invariant and submitted finite replay, not EVM correspondence, AMM mathematics or arbitrary English fidelity.

The seeded fixture collects 99 units in each pool and earns 49 rebate units per pool. Three pool-A claims pay 147, leaving custody of 51, below B's reserve of 99. The repaired control pays 49 once and rejects two repeats, leaving 149. Fee/rebate choices, rounding, retained fees, and environment assumptions still need creator review.
