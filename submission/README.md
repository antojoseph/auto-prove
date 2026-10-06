# spec.prove submission surface

Solvers edit only files under `submission/`. Everything else in the repository is protected challenge machinery; the hosted verifier obtains the frozen snapshot and reviewed policy from `challenge/`, never from this directory.

## What to submit

### Transaction contributions — `submission/contributions/*.json`

One or more files, each a `transaction-attack-v1` object bound to the current challenge version:

```json
{
  "version": "transaction-attack-v1",
  "snapshot_digest": "<from challenge/snapshot.json>",
  "policy_digest": "<sha256 of canonical challenge/policy.json>",
  "contributor": "your attribution",
  "requirement_id": "ReleaseWithinDeposit or OtherPayerBacking",
  "reasoning": "the claimed connection between observed behavior and the requirement",
  "trace": { "contract_name": "MilestoneEscrow", "constructor_arguments": [], "actions": [ ... ], "observations": [ ... ] }
}
```

The verifier validates every file, replays each trace on a disposable local Anvil (pinned Anvil/Cast 1.7.1, Solidity 0.8.28) and scores demonstrated violations of maintainer-reviewed requirements. Traces are data: bounded actions and view observations only — no code is ever executed from a submission.

### Formal evidence (optional) — `submission/formal.json`

An exact-target refutation of a frozen Lean property, kernel-checked by the hosted verifier through two independent kernels (nanoda, con-ron):

```json
{
  "property_id": "ReleasedWithinDeposit",
  "proof": "<Lean tactic proof of the negation of the frozen statement>"
}
```

## Scoring (fail-closed)

- score = (distinct demonstrated requirement/case pairs) + 5 x (distinct kernel-checked exact-target refutations)
- Any invalid file, stale digest, pending-review requirement claim, or inconclusive replay rejects the whole submission: nonzero exit, no score.
- A submission is promoted only if it beats the current promoted score.

## Invariants

Accepting a finding never approves the contract: every result leaves `accepted: false`, `creator_approval: pending` and `contract_correspondence: not_proved`. The numeric score is evidence credit for this internal pilot, not a security certificate or a payout rule.
