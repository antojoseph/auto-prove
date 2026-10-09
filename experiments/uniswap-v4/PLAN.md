# Plan: internal Uniswap v4 hook verification challenge

## Outcome

Build a local, reproducible spec.prove demonstration around a deliberately flawed fee-and-rebate hook, then prepare it for a separate internal Yukon dev challenge. Show a concrete transaction sequence breaking a stated requirement, a narrow repair that preserves the requirement, and independent replay plus Lean evidence for the repair.

This is a vulnerability seeded in our custom hook. It is not a claim of a vulnerability in Uniswap v4, an audit of all of v4, or a proof of deployed bytecode. No mainnet transactions or contract deployments are part of this plan.

## Isolation and release boundary

- Keep the new family under `experiments/uniswap-v4/`; preserve the original escrow implementation and recorded evidence.
- Run Solidity against a local Foundry EVM with the actual pinned v4 PoolManager and test ERC20 tokens. No RPC endpoint or wallet is needed.
- Write new evidence only to new `runs/reproduced-*` directories.
- Use a separate dev benchmark and submission schema if hosting is added. Do not replace the existing escrow benchmark or mix their scores.
- Keep any hosted UI on the existing internal spec.fail project with Vercel team protection. Do not publish or register the challenge on yukon.org, merge into Yukon master, or change `yukon-prod`.
- Preserve shared dev authentication defaults and existing redirect entries. The spec.fail callback fix is a separate onboarding dependency, not permission to change production auth.
- Local implementation approval does not constitute creator semantic approval. Keep `accepted: false`, `creator_approval: pending`, and `contract_correspondence: not_proved` until the appropriate reviews occur.

## Proposed target and intent — pending creator review

Two v4 pools share a custom hook and the same two test ERC20 tokens. They differ in pool configuration, so they have distinct pool IDs. A dedicated test router attributes swaps to their actual payer.

| Requirement | Proposed behavior |
| --- | --- |
| R1: fee and credit | On an exact-input swap, collect 1% of gross output, rounded down. Credit half that fee, rounded down per swap, as the payer's rebate. |
| R2: entitlement | A user's cumulative claims for a pool and currency cannot exceed that user's cumulative earned rebate. |
| R3: pool isolation | One pool's claims cannot consume another pool's fee reserves. |
| R4: attribution | Only PoolManager invokes the active callback; only the dedicated router supplies payer identity; users claim only their own credit. |
| R5: rollback | Rejected claims and failed transfers leave accounting and balances unchanged. |

The fee rate, rebate rate, rounding policy, and retention of remaining fees are proposed demo choices, not established product requirements. They are listed in `intent.json` for explicit review.

Initial scope excludes native currency, exact-output swaps, adversarial/rebasing/fee-on-transfer tokens, production routing, slippage protection, fee withdrawal, and upgrade administration. The Lean model initially covers two pools, one currency, and one recipient per pool. Solidity tests cover additional concrete cases, but those tests do not expand the theorem's scope.

## Demonstration narrative

1. Swap 10,000 input units through pool A and then pool B. In the current fixture each swap collects 99 output-token fee units and earns 49 rebate units.
2. Claim A's 49-unit rebate three times.
3. The seeded hook checks each request against lifetime earned credit, ignoring prior claims. It pays 147 from A despite collecting only 99 for A. Shared custody falls from 198 to 51, below B's untouched 99-unit fee reserve.
4. Patch the claim guard to account for cumulative prior claims and enforce the pool's remaining reserve. Keep the original fee and rebate requirements unchanged.
5. Replay the identical sequence. The repaired hook pays 49 once and rejects the next two claims, leaving shared custody of 149. B can still claim its own rebate.
6. Present the transaction receipts, resulting balances, regression checks, formal witness, and proof scope together. Do not equate a passing test or AI opinion with creator approval.

“Patching” here means building and checking a revised local contract variant. There is no automatic modification of a deployed contract.

## Current implementation status

As of 9 October 2026, the following work exists locally and is uncommitted:

- Pinned official `Uniswap/v4-core` at `46c6834698c48bc4a463a86d8420f4eb1d7f3b75`, with submodule revisions recorded in `dependencies.json`. The experiment uses Solidity 0.8.26, matching PoolManager's exact pragma; the escrow project keeps its existing compiler setting.
- Implemented `src/RebateHook.sol` with seeded and repaired variants and `src/DemoRouter.sol` for local exact-input swaps.
- The initial eight Solidity tests passed, including the concrete cross-pool attack, its repair, currency and user checks, and 256 fuzz cases for split claims.
- Lean 4.22.0 successfully checked the hand-authored model, the 99/99/49 attack witness, the repaired witness, an invariant for arbitrary finite action sequences, and preservation of the other pool's remaining reserve. Standard Lean axioms are audited; no custom axioms or proof placeholders are used.
- Added a bounded JSON attack schema, seed fixture, intent draft, dependency setup script, and a runner intended to generate concrete replay and Lean witness artifacts.
- Six Python tests passed for malformed input, duplicate keys, prose/code separation, replay mismatch detection, axiom audit failure, and a non-violating sequence.

**The packaged end-to-end runner has not yet completed successfully.** Three additional Solidity tests were added after the initial eight passed. Foundry rejected the name `testFailedTransferRollsBackClaimAndCanRetry` because it interprets the `testFail` prefix as a removed convention. Rename that test, rerun the expanded suite, and continue through the generated submission and witness stages. Do not describe the new challenge as ready for participants until these stages pass.

Nothing from this new experiment has been pushed, deployed, or registered with Yukon. No Supabase settings changed.

## Execution plan

### 1. Finish the local harness

- Rename the transfer-failure test and run the expanded Solidity suite.
- Verify rollback/retry, separate recipients, unauthorized router/callback calls, unsupported exact-output swaps, both swap directions, partial claims, and claims after new earnings.
- Finish the JSON-driven EVM replay for the same submission against both variants. Rejected claims must be recorded as outcomes, not silently treated as successful transactions.
- Compare actual fee collections, claim outcomes, and final balances against the abstract accounting replay. Fail closed on any mismatch.
- Generate and kernel-check a Lean witness from validated numeric trace data. Never compile submission prose or arbitrary submitted source.
- Export source hashes, dependency revisions, compiler versions, test results, proof logs, and a readable local report. Failed runs must remain clearly marked as failed.

Exit criterion: one documented command reproduces the seeded violation and the repair, with passing Solidity/Python checks and checked Lean evidence. A fresh checkout can reproduce it without credentials or RPC access.

### 2. Review semantic scope

- Review R1–R5, the fee/rebate policy, environmental assumptions, and unresolved questions in `intent.json`.
- Confirm what counts as an intent violation versus unsupported behavior or a deliberately excluded environment.
- Review the mapping between Solidity storage/actions and the abstract model. Clearly label the missing Solidity/EVM correspondence proof.
- Decide whether to keep the first challenge bounded to one modeled recipient per pool or extend the model before offering multi-user formal claims.

Exit criterion: a recorded human decision on the initial scope. Unresolved choices stay pending; the runner must not auto-approve them.

### 3. Make it usable by an internal participant

- Add a short README with setup, the contract under review, original intent, supported actions, the seed attack, and the exact local submission command.
- Make the report explain the attack and repair before exposing detailed logs.
- Exercise a valid objection, an ordinary non-violating sequence, an invalid submission, and a replay failure. A non-violation must receive no evidence credit.
- Add a reproducible CI job scoped to the new experiment once the local runner is stable. Keep network dependency installation separate from offline validation.

Exit criterion: a colleague can clone, understand the target, submit a JSON trace, and inspect evidence without editing the trusted verifier.

### 4. Prepare a separate hosted dev challenge

- Inspect the existing Yukon dev runner requirements and adapt this family's setup/run/score interfaces.
- Pin the target contract, intent, model, and evaluator for the benchmark revision. Keep solver-controlled files separate from trusted validation files.
- Define evidence scoring before importing: avoid duplicate credit for equivalent repeated-claim traces and do not advertise scores as security certificates.
- Keep the intentionally buggy target frozen for submissions; present the repaired variant as the regression/control. Interactive specification evolution and contract patch submissions require a later versioned protocol.
- Create a separate internal dev benchmark and UI entry only after the artifact and scope are reviewable. Preserve the existing escrow board and public challenge visibility.

Exit criterion: hosted validation reproduces a local supported objection, rejects invalid data, and displays the result only in the internal demo.

### 5. Retest onboarding and invite internally

- An authorized admin must add the narrow spec.fail callback entry in `yukon-dev`. The current account can view the settings, but the Add URL control is disabled.
- Retest a fresh participant through Vercel team access, GitHub sign-in returning to spec.fail, CLI authentication against dev, local validation, hosted submission, and leaderboard display.
- Check that the participant sees the intended v4 hook family, source revision, requirements, assumptions, and participation instructions.

Exit criterion: a fresh authorized participant completes the entire path and sees a validated result. Existing escrow scores alone do not establish that the new v4 challenge works end to end.

## Later phase: proposer, attacker, and judge

The first milestone is a deterministic, seeded demonstration. It does not yet run independent proposing/attacking agents or an AI judge.

A later phase can add separate proposer and attacker contexts, with the judge evaluating whether replay-supported objections justify a change. The judge must not substitute for Lean checking, modify the original intent silently, or grant creator approval. Every approved revision should preserve its parent version, requirement mapping, evidence, and regression suite. Unsupported objections and ambiguous intent stop for review.

## Completion checklist

- [ ] Expanded local Solidity suite passes.
- [ ] Packaged seeded and repaired submission replay passes.
- [ ] Generated Lean witness and axiom audit pass.
- [ ] Non-violating and malformed submissions receive correct outcomes.
- [ ] Fresh-checkout reproduction and report inspection complete.
- [ ] Intent and assumptions reviewed.
- [ ] Separate hosted dev benchmark and scoring validated.
- [ ] Internal UI and fresh-participant onboarding tested.
- [ ] Production Yukon and public challenge listings unchanged.
