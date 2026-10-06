# Repaired-lending and escrow-family evidence (recorded 2026-10-05)

All evidence here is credential-free and independently reproducible from the repository.

## lending-fixed

A regenerated specification for the source-repaired `LendingPool` (the withdraw guard from `general/fixtures/attacks/fixed-source-snapshot.json`). Property statements are unchanged from the reviewed revision; only the `withdrawAllowed` model definition changed.

- `snapshot.json` — frozen revised snapshot (digest `cbc67ee8aa84d9d2dd7e01e4b6bf988ac5e9da1606c640fdbf3abbee825ce972`). Reproduce with `python3 -m general freeze <input> candidate.json` using the input inside `general/fixtures/attacks/fixed-source-snapshot.json` and `candidate.json` here.
- `candidate.json` — the regenerated candidate: identical property statements, repaired `withdrawAllowed`.
- `Solution.lean` — proof file for the full verify: four real proofs and an honest `sorry` on `OtherClaimAvailability`; the trusted judge therefore rejects the batch (`rejected`), which is the recorded outcome, while the four targets are checked individually below.
- `finding-collaterallock.json`, `finding-borrowcap.json`, `finding-deposit.json`, `finding-borrowcheck.json` — observation findings whose checks produced the `observation-*.json` results (`status: supported_model_observation`, `independent_kernels: nanoda, con-ron`). `CollateralLock` and `BorrowCap` are the protections the repair restores.
- `finding-otherclaim.json` / `counterexample-evidence.json` — exact-target refutation of `OtherClaimAvailability` (`status: supported_model_counterexample`): over arbitrary states the pool need not back honest claims; a sound version needs a reachability invariant.

Reproduce any check with:

```sh
python3 -m general evidence general/evidence/lending-fixed/snapshot.json finding-collaterallock.json --output runs/reproduced-observation
```

## escrow

The second contract family (`MilestoneEscrow`, fixtures in `general/fixtures/escrow/`): a per-payer escrow whose release guard omits already-released amounts.

- `snapshot.json` — frozen snapshot of the developer-authored model (digest `3224e07cd6a289f68526fd0cdc0059caa968b4188cbdcabdb5df7d02bca84e43`).
- `counterexample-result.json` — kernel-checked exact-target refutation of `ReleasedWithinDeposit`: from a healthy state a 100 release over a 100 deposit with 30 already released leaves 130 above the deposit. The concrete double-release attack (`attack-double-release.json`) demonstrates the same defect on a disposable local chain: released 200 over deposited 100 while draining the balance that backs the other payer.

Every result leaves semantic approval pending and contract correspondence not proved. These are developer-authored demonstrations, not agent discoveries, and not a security certificate for either contract.
