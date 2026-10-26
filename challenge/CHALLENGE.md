# MilestoneEscrow — automatic challenge, version 1

Approval: **approved_automatically** (judge + independent reviewer + mechanical gate). Contract/model correspondence: **not proved**. This is not a security certificate.

- Snapshot digest: `3224e07cd6a289f68526fd0cdc0059caa968b4188cbdcabdb5df7d02bca84e43`
- Policy digest: `d3b34ab42fbb1a816bf4837b3fa9f24fb846afdc13e622bd277fb3a74458cc56`
- Quiet period: {"last_accepted_at": null, "days_since_last_accepted": null, "submissions_since_last_accepted": 0, "meaning": "time and submissions without a new accepted finding; never a security guarantee"}

## Threat model

- in scope: Any externally owned account may call any public function, in any order, with any arguments.
- in scope: Participants may deploy attacker contracts, including contracts with callbacks, reentrancy, reverting receivers and self-destruct force-sends of ether.
- in scope: Time may advance forward between transactions.
- out of scope: Reordering or front-running other users' transactions; sandwich attacks.
- out of scope: Flash-loan-scale capital or external protocols not deployed in the challenge environment.
- out of scope: Compiler, EVM, consensus or validator misbehaviour.

## Current requirements

- **ReleaseWithinDeposit** (spec, from v1): Released funds for a payer must never exceed that payer deposits.
- **OtherPayerBacking** (intent, from v1): Other payers' deposits must remain available in the escrow after any release.

## Version history

- v1 (2026-10-26T21:18:33.583604Z): Opened from creator input

Earlier versions and their diffs are published so participants can look for weakened protections (weakening found earns credit).
