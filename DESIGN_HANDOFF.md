# Transaction-grounded specification review: design and handoff

Status: **local draft implementation, published for review; live transaction verification incomplete.**

This document describes the design, what has been implemented, how another researcher or agent can inspect and test it, and what still needs building. It does not assert that the current code is production-ready or that any contract is secure.

## The product

A creator supplies a smart contract, English intent and approved assumptions. Agents propose explicit requirements and a formal model. Other agents contribute transaction sequences and explain the requirement those sequences challenge. Evidence informs a revised specification or an identified contract defect. Accepted findings persist across revisions as regression cases.

Use Yukon for participation, submissions, discussion and platform rewards. There is no Choir dependency.

There is one contribution and revision loop with separate questions:

1. Does the observed behavior violate an existing requirement? If so, the contract may be defective, or the formal model may misrepresent the contract.
2. Does the behavior satisfy the modeled requirements but contradict an intended protection? If so, the specification may omit or weaken that protection.
3. Is the intended protection ambiguous? If so, the creator must decide what it means before a requirement can be treated as approved.

A transaction makes behavior reproducible. It does not independently prove the interpretation of English intent, equivalence between a Lean model and Solidity execution, or comprehensive security.

## End-to-end experience

**Creator:** supplies source and intent; reviews inferred requirements, threat assumptions, unresolved questions and the operational conditions used for transaction checking. Each approved revision becomes a frozen version.

**Contributor:** receives the protected snapshot and operational policy. Submits transactions, a requirement ID, reasoning, attribution, and the exact snapshot/policy digests. Contributors cannot submit replacement checker conditions or external RPC endpoints.

**Runner:** validates the contribution, starts a disposable local chain, uses the original source, and records receipts plus state observations. Owner-authored probes and predicates judge the result. State can be inspected after every transaction, after a specified successful function call, or only at the final state, according to the protected policy.

**Reviewer:** sees the state history, requirement check, explanation and relevant formal artifacts. Confirms the requirement's meaning and categorizes the accepted finding as a contract bug, specification gap or model gap. The runner does not infer this category conclusively from a transaction alone.

**Revision:** preserves the original accepted condition and scenario. Changing or removing a formal property does not remove its historical regression. A later replay can still expose the original failure. Changed formal mappings remain marked for review.

## Three protected artifacts

| Artifact | What it owns | Who may change it |
| --- | --- | --- |
| Frozen snapshot | Source, intent, model, Lean targets, assumptions and proof policy | Challenge maintainer through a reviewed revision |
| Operational policy | Contract selection, trusted state probes, requirement predicates, intent quotations and review status | Challenge maintainer |
| Accepted-case registry | Original scenario and condition, origin snapshot/policy, contributor and reviewer decision | Challenge maintainer |

Agents submit evidence against these artifacts. A submitter-controlled snapshot, policy or registry must never be treated as the authoritative challenge input. Hashes establish version identity, not ownership or authorization. Yukon integration must enforce that ownership boundary.

## Contribution format

The implemented JSON format is `transaction-attack-v1`. See `general/fixtures/attacks/withdraw-collateral.json` and `general/fixtures/attacks/intent-gap.json`.

Required fields:

- `version`, `snapshot_digest`, `policy_digest`;
- `contributor`: self-reported attribution, not authenticated identity;
- `requirement_id`: a requirement in the protected policy;
- `reasoning`: the claimed connection between observed behavior and the requirement;
- `trace`: selected contract name, constructor arguments, bounded actions and optional descriptive observations.

The trusted policy supplies `probes` and `requirements`. Each requirement includes an English description, a quotation present in the original intent, `scope` (`spec` or `intent`), its review status, a step selection and a bounded JSON predicate. A `spec` requirement also names the corresponding Lean property.

Predicates use typed comparisons, integer arithmetic and Boolean operators over trusted state observations. They are data, not executable agent code. Current probes support contract balance and scalar view/pure results: integers, Booleans and addresses. Tuple/array results, multi-contract deployments, sophisticated callback scenarios, external imports and chain forks need further work.

An operational condition mapped to a Lean property is a reviewed interpretation of that property. **A failed operational condition is not automatically an exact Lean refutation.** The existing `general evidence` command handles independently checked refutations of exact frozen formal targets.

## What is implemented locally

| File | Current responsibility |
| --- | --- |
| `general/attacks.py` | Policy/submission validation, bounded predicate evaluation, adjudication report, maintainer acceptance, exact-case deduplication and historical regressions |
| `general/evm.py` | Bounded trace validation, scalar ABI decoding and trusted state captures during replay |
| `general/__main__.py` | `attack`, `accept-attack`, `regress-attacks`, and `run --attack-registry` commands |
| `general/pipeline.py` | Optional replay of accepted cases in every revision round; results passed to proposer/reviewer history |
| `general/fixtures/attacks/` | Synthetic examples: existing requirement violation, incomplete specification/intent gap, and a source-patched comparison |
| `test_attacks.py` | Fourteen unit tests for validation, adjudication and regression behavior; EVM replay is mocked |

Acceptance reruns the scenario; it does not trust an uploaded report. Pending operational requirements cannot enter the accepted registry. Exact duplicate cases with different attribution or explanation share an identity and do not create multiple registry entries. This is limited deduplication, **not a solution to semantic duplicates, Sybil behavior or collusion**.

`attack_acceptance: accepted` accepts a finding. The report still leaves contract `accepted: false`, `creator_approval: pending` and `contract_correspondence: not_proved`.

## Verification completed and incomplete

**Completed for this revision:**

```sh
python3 -m unittest test_attacks test_general test_app test_engine
```

Observed result: **49 tests passed** (35 existing tests and 14 new tests). New transaction tests use mocked replay results. This establishes selected application behavior, not successful EVM execution.

**Incomplete:** the attempted live local transaction replay returned `inconclusive` with `[Errno 1] Operation not permitted`. No successful live transaction validation was completed for this revision. Further execution was stopped and verification handed to the maintainer. Do not describe the new draft as end-to-end validated.

The older recorded Lean and transaction evidence remains unchanged. It does not validate the new transaction contribution/registry implementation. Existing CI also needs to include `test_attacks.py` and a live integration job; the current general verifier workflow does not run this new test module.

## How to inspect and test

Use the branch containing this handoff, currently `general-intent-pipeline` in `antojoseph/auto-prove`. Start with this document, `GENERAL_PIPELINE.md`, `AGENTS.md`, then the files listed above. Use a fresh output directory for every command; existing evidence should not be overwritten.

The unit suite needs Python 3.9+ and no model account. Live replay needs Anvil and Cast **1.7.1** plus Solidity **0.8.28**. Put them on PATH, or set `AUTO_PROVE_ANVIL`, `AUTO_PROVE_CAST`, and `AUTO_PROVE_SOLC` to their installed paths. Installation references are in `README.md` and `GENERAL_PIPELINE.md`. No external chain, wallet or model account is required for the following fixture checks.

### 1. Existing requirement violation

```sh
python3 -m general attack \
  general/fixtures/attacks/snapshot.json \
  general/fixtures/attacks/policy.json \
  general/fixtures/attacks/withdraw-collateral.json \
  --output runs/reproduced-attack-existing
```

Inspect `attack.json`, `report.html` and `replay/replay.json`. Expected, subject to your verification: `demonstrated_spec_requirement_violation`, complete transaction receipts and per-step observations, with acceptance still pending. A runtime failure must remain `inconclusive`, never be counted as a successful attack.

### 2. Incomplete specification versus intent

```sh
python3 -m general attack \
  general/fixtures/attacks/weak-snapshot.json \
  general/fixtures/attacks/weak-policy.json \
  general/fixtures/attacks/intent-gap.json \
  --output runs/reproduced-attack-intent
```

The weak synthetic specification contains a borrowing check while omitting a withdrawal protection. Expected: `demonstrated_intent_requirement_violation`; `all_requirement_checks.BorrowLimit` is `not_demonstrated` (no violation observed) while `CollateralBacking` is `demonstrated_violation`. Inspect the actual values and the original English quotation rather than relying on the status label.

The fixture's `approved` operational status is an internal, developer-authored example. It does not represent a production creator approval process.

### 3. Maintainer acceptance and persistence

Run this only as the challenge maintainer, after reviewing the condition and evidence:

```sh
python3 -m general accept-attack \
  general/fixtures/attacks/snapshot.json \
  general/fixtures/attacks/policy.json \
  general/fixtures/attacks/withdraw-collateral.json \
  --registry runs/reproduced-accepted-cases \
  --category contract_bug \
  --reason 'Internal fixture: reviewed explicit withdrawal requirement and replay evidence.' \
  --output runs/reproduced-attack-acceptance
```

Expected: fresh replay, one accepted-case JSON file and `attack_acceptance: accepted`. Repeat with a different output directory and different attribution/reasoning: exact-case deduplication should return `duplicate` without creating another case.

### 4. Original and source-patched regressions

```sh
python3 -m general regress-attacks \
  general/fixtures/attacks/snapshot.json \
  --registry runs/reproduced-accepted-cases \
  --output runs/reproduced-regress-original

python3 -m general regress-attacks \
  general/fixtures/attacks/fixed-source-snapshot.json \
  --registry runs/reproduced-accepted-cases \
  --output runs/reproduced-regress-source-patched
```

Expected for the original: `needs_attention`, with the case `still_violates_original_requirement`; the command intentionally exits nonzero. Expected for the source-patched fixture: `passed_replay` for this selected case. Check the receipts and state history to confirm the changed behavior.

The source-patched fixture preserves the old formal specification to isolate replay behavior. It **does not provide a regenerated model, checked proof or proof of correspondence for the changed code**. Passing that regression is not evidence that the revised contract is generally secure.

### 5. Required negative and revision checks

Verify stale snapshot/policy digests are rejected before replay; contributors cannot supply a predicate or RPC; pending requirements cannot be accepted; incomplete observations stay inconclusive; a violation at an intermediate step survives later recovery; changing attribution does not create duplicate cases; and removing an attacked formal property does not erase its original regression.

If a formal mapping changes while the selected concrete regression no longer fails, the result should require mapping review. Changing original intent or approved assumptions should require a separate reviewed challenge scope rather than silently reusing the registry.

These cases have unit coverage, but independent live/integration checks and hostile-input review remain necessary.

## What still needs building and verification

| Area | Remaining work |
| --- | --- |
| Operational-policy authoring | Agent-generated proposals plus creator review; stronger checks linking the operational condition to its Lean target and intended meaning |
| Public submission boundary | Protected snapshot/policy ownership, authenticated contributor identity, schema/API validation, size/rate limits and isolation review |
| Transaction coverage | Multi-contract dependencies, callback participants, richer ABI observations and additional scenario/environment controls |
| Formal connection | Link concrete state histories to generated models; keep exact Lean refutation and concrete observations distinct until that connection is established |
| Verification | Successful live replay, original/patched comparisons, malformed inputs, concurrency/corruption cases, resource limits and reproducible CI evidence |
| Regression governance | Reviewed requirement evolution, case migration, mapping changes and explicit decisions about deprecated requirements |
| Yukon integration | Direct contribution format and benchmark runner, version-linked discussion links, hosted replay artifacts and acceptance workflow |
| Rewards | Meaningful finding/reproduction/repair credit, semantic deduplication, payout review and analysis of collusion incentives |
| Evaluation | Additional contract families, safe/unsafe cases, held-out requirements, false-positive measurement and cost/budget limits |

The existing Yukon manifest still accepts proposer/reviewer prompt changes. **Direct transaction contributions are local CLI artifacts; they are not yet a live Yukon submission mode.** No new platform integration, public challenge, voting system, reward allocation or payout has been implemented.

## What to do next, in order

These are planned tasks, not completed work. Live verification is assigned to the maintainer or their chosen researcher; no additional execution is implied by this handoff.

### 1. Independently verify the current local loop

**Owner:** maintainer / verification researcher.

Run the commands in the inspection and testing section from a fresh checkout. Record the commit, runtime versions, command outcomes, receipts, state histories and requirement evaluations. Check both existing-specification and intent-gap examples, acceptance, duplicate handling, and original/source-patched regressions. Also verify that removing a requirement cannot erase its accepted case.

**Deliverable:** a verification report with reproducible, credential-free evidence and a list of failures or inconclusive checks. Label each expected outcome confirmed, failed or not run. This is the immediate next task; the current 49 passing unit tests do not replace it.

### 2. Fix discrepancies and make verification repeatable

**Owner:** implementation engineer, with the verification researcher reviewing results.

Fix issues discovered in step 1 without changing the original requirement merely to make a case pass. Add meaningful regression coverage for those issues. Include `test_attacks.py` in CI and add a model-free integration job with pinned replay dependencies. Ensure infrastructure failures remain distinguishable from rejected contributions.

**Deliverable:** a fresh checkout reproduces the reviewed outcomes, and CI saves the evidence needed to inspect failures. Historical evidence remains preserved.

### 3. Complete creator review and specification revision

**Owner:** specification engineer and challenge creator.

Build the missing path from source and English intent to proposed operational policies. Show the creator the requirement, intent quotation, assumptions, observed state fields, predicate and any Lean mapping before approval. Record decisions and create a new frozen version after a meaning change. For the source-patched example, regenerate and review the formal model and targets; the current fixture only isolates concrete replay behavior.

**Deliverable:** one reviewed case passes through proposal, concrete evidence, creator decision and specification revision. Its original regression survives into the new version. Model observations, concrete requirement failures and exact Lean refutations remain separately labeled.

### 4. Add direct contributions to an internal Yukon challenge

**Owner:** Yukon integration engineer and challenge maintainer.

Add a transaction-contribution mode alongside the existing prompt-improvement benchmark. The hosted runner must obtain the snapshot and policy from the maintainer, authenticate attribution through the platform, enforce input and resource limits, and publish version-linked evidence. Connect accepted findings to the maintainer-owned registry and discussion entry. Document how contributors obtain the current challenge version and submit an artifact.

**Deliverable:** one independent contributor submits through Yukon, receives a reproducible result, and can inspect the evidence and acceptance decision. Rejected or inconclusive entries remain visible with their reasons. No automatic monetary payout is required for this first internal test.

### 5. Test transfer and useful diversity

**Owner:** research team.

Add at least one different contract family using the same contribution format and runner. Include cases where no violation should be demonstrated, cases with a real requirement failure, and cases requiring creator clarification. Invite a small set of independently operated agents or model families. Track distinct supported findings, false objections, unresolved requirements, time/cost, and survival of historical cases.

**Deliverable:** evidence that the mechanism transfers beyond the public lending fixture. Keep developer-authored demonstrations separate from agent discoveries. Evaluate prompt improvements on held-out cases rather than rewarding memorization of the public examples.

### 6. Define monetary credit before a rewarded public pilot

**Owner:** challenge maintainer and Yukon rewards team.

Specify which reviewed contributions earn discovery, independent reproduction or repair credit. Define handling for copied findings, semantically equivalent cases, multiple accounts, shared contributions and disputes. Keep votes useful for prioritizing review; they must not override a valid counterexample or decide formal correctness. Separate finding acceptance from payout authorization.

**Deliverable:** written reward rules, reviewed failure scenarios, a bounded test budget and an auditable acceptance-to-reward record. Exact-case deduplication alone is insufficient for this step.

### Later scope

After the internal milestone, extend multi-contract and callback scenarios, richer observations, formal model/execution connections and reviewed requirement migration. A public pilot should have held-out evaluation, tested submission isolation and clear limits on its claims. Broad contract support and comprehensive security certification are not prerequisites for a narrowly scoped internal test, and are not established by it.

## First acceptance milestone

An independent reviewer can reproduce both types of requirement violation, accept one reviewed finding, recover its saved case in a fresh process, show that a specification change cannot hide it, and distinguish a selected source repair from formal proof and comprehensive security. After that, wire the reviewed contribution format into Yukon and test one external contributor end to end.
