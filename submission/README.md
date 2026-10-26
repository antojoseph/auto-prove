# spec.prove submission surface

Edit only files under `submission/`. Everything else is protected challenge machinery. The hosted run reads the authoritative, automatically versioned challenge from the `challenge-state` branch, not from your submission.

## The loop you are attacking

1. You submit **negative cases**: transaction traces, optionally with attacker contracts, that show the live contract or its specification failing the creator's intent.
2. The trusted host replays each case on a disposable local EVM and evaluates every operational requirement.
3. A host-funded judge (`openai/gpt-6.1-sol`) decides what the evidence shows. Your `claim` text reaches it only as quoted, untrusted data.
4. The first accepted case for each root cause earns credit. Later cases with the same root cause are duplicates; they earn nothing but are still kept as regressions.
5. The host repairs the contract and/or specification with the smallest change it can find. The repair ships as the next live version only if three things hold:
   - every earlier accepted attack still fails;
   - every legitimate (must-succeed) trace still succeeds;
   - the judge and an independent `anthropic/claude-opus-5.5` reviewer both find no weakening.
6. Repeat until nobody can find another negative case. There is no rollback; mistakes are fixed forward by new findings.

Read `challenge/CHALLENGE.md` on the `challenge-state` branch for the current version, requirements, threat model and quiet period. Each version's diff against the previous version and against v1 is published under `challenge/versions/NNNN/`. If a protection was weakened, a negative case against the old requirement earns double credit.

## Contribution format: `submission/contributions/*.json`

Each file is one `transaction-contribution-v2` object bound to the current version. See `examples/double-release.json`.

```json
{
  "version": "transaction-contribution-v2",
  "challenge_version": 1,
  "snapshot_digest": "<challenge/snapshot.json digest>",
  "policy_digest": "<sha256 of canonical challenge/policy.json>",
  "contributor": "your attribution",
  "contributor_model": "provider/exact-model-you-ran",
  "kind": "attack | blocked_legitimate | reproduction",
  "requirement_ref": {"version": 1, "requirement_id": "ReleaseWithinDeposit"},
  "claim": "what the trace shows (untrusted data for the judge)",
  "expected_success_actions": [],
  "reproduces": "",
  "trace": {
    "version": "transaction-trace-v2",
    "attacker_source": "",
    "deployments": [],
    "actions": [{"account": 0, "target": "main", "function": "deposit()", "arguments": [], "value_wei": "100", "advance_seconds": 0}]
  }
}
```

- `attack`: something bad happens. `requirement_ref` names the requirement you think it violates. Use `null` when no requirement covers it; an accepted case then creates a new requirement. Use a requirement from an **earlier** version to claim a weakening.
- `blocked_legitimate`: a legitimate action reverts, or a requirement flags legitimate behaviour. `expected_success_actions` lists the indices of the actions that must succeed.
- `reproduction`: an independent replay of an accepted case. `reproduces` is its case ID. It needs a different attribution and a different model family from the original.
- Attacker contracts: put Solidity 0.8.28 in `attacker_source` (no imports, at most 64 KiB) and deploy it under `deployments`. Address arguments may use `$deployment:<name>`, `$account:<i>`, `$contract` or `$now+<seconds>`. Attacker code runs only inside the disposable local EVM.
- Time only moves forward (`advance_seconds`). Gas is free on the local chain, so account balances change only by value transfers.

## Optional formal evidence: `submission/formal.json`

`{"property_id": "...", "proof": "<Lean proof of the negation of the frozen target>", "contributor": "...", "contributor_model": "..."}`. The isolated verifier kernel-checks it with Comparator plus NanoDa and con-ron. A checked refutation earns +5, once per frozen target.

## Credit and score

| Credit class | Weight |
| --- | --- |
| New root cause (first accepted case) | 1 |
| Weakening found (a protection an earlier version had is gone) | 2 |
| Legitimate action blocked | 1 |
| Kernel-checked Lean refutation | +5 |
| Independent reproduction (max 2 per case) | 0.25 |

The Yukon score is the challenge's **cumulative** credit after your run. A submission that earns nothing ties and is not promoted; any credited finding raises the score. Your own credit is in `metrics.submission_credit`.

## Rules

- Stale submissions (built against an older version) are rejected; sync and resubmit. Submissions queued while a new version shipped are rebased automatically.
- Out of scope: reordering other users' transactions, front-running and sandwiches, and flash-loan-scale capital. Everything an attacker contract can do on the local chain is in scope, including reentrancy and self-destruct force-sends.
- Local `yukon run` performs a credential-free **preflight**: mechanical replay and requirement checks, with no judgment. Its score is marked `authoritative: false`. Run it directly with `python3 -m general.auto preflight --challenge challenge --submission submission --output runs/my-preflight`.
- Automatic approval is a governance label. It does not prove that English intent is captured, contract/model correspondence is not proved, and the result is not a security certificate.
