# Recorded generalized experiments

Both inputs are synthetic. The proposer generated the Lean model and formal targets from source + English; no hand-authored family reference model was supplied. `gpt-6-sol` was used through Codex CLI 0.157.0. Usage files record completed invocations; the timed-out vault revision has no completed usage record.

- **Lending:** two live proposal/review rounds. The reviewer identified a collateral-withdrawal bug, a healthy-state precondition that omitted already-underwater withdrawals, and omitted callback behavior. The proposer strengthened the withdrawal target and expanded the callback abstraction. Independent rechecking supports **three exact-target counterexamples** and **one model observation**. Six agent-generated concrete replay records replayed on disposable Anvil chains, including both one-step and two-step collateral removal. Positive proof attempts remain inconclusive due to compiler errors and intentionally incomplete safety proofs. Lender accounting, repayment and more general callback behavior remain unresolved.
- **Owner vault:** a separately generated model and **six target proofs** pass protected Comparator, Lean, NanoDa and con-ron. A checked model observation supports the adversary's argument that the abstraction omits nested owner callbacks; that source-level callback scenario was not replayed. A revision model call timed out after 360 seconds. Semantic review remains incomplete.
- **Verifier gates:** seven recorded cases check real proof acceptance, placeholder rejection, target replacement, forbidden axioms, equivalent model-body replacement, meaning-changing definitions, and exact-target refutation. The final results all use **no editable definition holes**.

The first live processes loaded a superseded Comparator configuration that mistakenly treated model declarations as editable definition holes. Their judgments are retained as `superseded_*` and never used as final verification. The protected rechecks and all accepted witnesses here use `definition_names: []`. Standalone one-theorem witnesses were normalized into proof terms only after exact target matching; their original agent text remains in review.json.

Open `lending/report.html` and `vault/report.html` for full inputs, assumptions, actual targets, revisions and evidence. Reproduce an individual counterexample using:

```sh
python3 -m general evidence general/evidence/lending/round-2/snapshot.json \
  finding.json --output runs/reproduced-counterexample
```

`finding.json` is one finding object from `general/evidence/lending/round-2/review.json`. The generated files and logs in its `finding-*` directory show the exact proposition and proof. No model inference is needed for replaying those artifacts. Concrete replay similarly takes the finding's `evm_trace` as a separate JSON file.

Every result leaves semantic approval pending and contract correspondence unproved. This is evidence of the pipeline working on two small inputs, with its real failures exposed, not a reliability estimate for arbitrary contracts or diverse solver communities.
