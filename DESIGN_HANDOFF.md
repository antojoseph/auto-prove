# Transaction-grounded specification review: design and handoff

Status: **local implementation with independently reproduced live transaction replay, creator-review records, a regenerated repaired-source revision with kernel-checked evidence, and a second contract family. Platform (Yukon) submission integration and public/agent-discovered evaluation remain unbuilt.**

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
| `general/review.py` | Operational-policy proposals (all requirements pending), creator review packets showing English, intent quotation, probes, predicate, assumptions and Lean mapping, and recorded approve/reject decisions |
| `general/evm.py` | Bounded trace validation, scalar ABI decoding and trusted state captures during replay |
| `general/__main__.py` | `attack`, `accept-attack`, `regress-attacks`, `propose-policy`, `review-policy`, and `run --attack-registry` commands |
| `general/pipeline.py` | Optional replay of accepted cases in every revision round; results passed to proposer/reviewer history |
| `general/fixtures/attacks/` | Synthetic examples: existing requirement violation, incomplete specification/intent gap, a source-patched comparison, a draft policy and its creator decisions |
| `general/fixtures/escrow/` | Second contract family (MilestoneEscrow): safe trace, real double-release failure, and an ambiguous intent requirement requiring creator clarification |
| `general/evidence/lending-fixed/`, `general/evidence/escrow/` | Credential-free recorded evidence: regenerated repaired-lending snapshot, kernel-checked observations, exact-target refutations, preserved candidates/findings/proofs |
| `test_attacks.py` | Nineteen unit tests for validation, adjudication, regression, creator-review and second-family fixture behavior; EVM replay is mocked |

Acceptance reruns the scenario; it does not trust an uploaded report. Pending operational requirements cannot enter the accepted registry. Exact duplicate cases with different attribution or explanation share an identity and do not create multiple registry entries. This is limited deduplication, **not a solution to semantic duplicates, Sybil behavior or collusion**.

`attack_acceptance: accepted` accepts a finding. The report still leaves contract `accepted: false`, `creator_approval: pending` and `contract_correspondence: not_proved`.

The creator-review path (`propose-policy` / `review-policy`) records explicit approve/reject decisions per requirement with reasons. A rejected requirement is excluded from the reviewed operational policy and retained in the review record; a fully rejected proposal produces no usable policy. Approving an operational requirement is an interpretation for transaction checking only — it is never contract approval, semantic approval, or a model/EVM equivalence claim.

## Verification status

**Unit suite:** `python3 -m unittest test_attacks test_general test_app test_engine` — **54 tests pass** (35 original, 14 transaction-contribution tests, 5 creator-review and second-family tests; replay mocks where noted).

**Live replay:** `bash scripts/verify_attacks.sh` runs eight credential-free stages on a disposable local Anvil: both original attack fixtures, acceptance with exact-case deduplication, original and source-patched regressions, stale-digest rejection before replay, an injected runtime failure that stays `inconclusive`, and the MilestoneEscrow family (safe trace, double-release failure, blocked pre-review acceptance, creator approve/reject, accepted case, unrepaired regression). The earlier `[Errno 1] Operation not permitted` failure did not reproduce on macOS arm64 with Anvil/Cast 1.7.1 and solc 0.8.28; it appears to have been specific to the previous execution environment.

**Docker verifier:** `python3 -m general.regressions --output runs/reproduced-general-gates` — all seven protected proof gates pass (real proof accepted; sorry, substituted target, custom axiom, equivalent-body replacement and meaning-changing definition rejected; genuine refutation accepted).

**Regenerated repaired-source revision** (`general/evidence/lending-fixed/`): frozen revision `cbc67ee8…`; full-file verify honestly `rejected` (four real proofs plus an intentional `sorry` on the open `OtherClaimAvailability` target); individually kernel-checked: four `supported_model_observation` results including the repaired `CollateralLock` and `BorrowCap`, plus a `supported_model_counterexample` refuting `OtherClaimAvailability` over arbitrary states. The historical regression against the revision reports `requires_mapping_review` (mapping changed), resolved by a recorded creator review of the revised policy; the concrete replay of the original accepted case no longer demonstrates the violation.

**Second family** (`general/fixtures/escrow/`): safe trace `not_demonstrated`; double-release `demonstrated_spec_requirement_violation` (Released 200 over Deposited 100, balance drained below the other payer's backing); ambiguous intent requirement demonstrated as `proposed` with acceptance blocked until the creator decision (recorded approve/reject); accepted case replays as `still_violates_original_requirement` on the unrepaired snapshot; kernel-checked `supported_model_counterexample` for `ReleasedWithinDeposit`.

**Incomplete:** hosted Yukon submission mode, authenticated attribution, agent-discovered (non-developer) findings, semantic-duplicate review in practice, hostile-input live review beyond the recorded unit coverage, and multi-contract/callback transaction coverage. The general verifier workflow now includes `test_attacks.py`, and `transaction-attacks.yml` runs the live loop in CI with pinned runtimes.

## How to inspect and test

Use the branch containing this handoff, currently `general-intent-pipeline` in `antojoseph/auto-prove`. Start with this document, `GENERAL_PIPELINE.md`, `AGENTS.md`, then the files listed above. Use a fresh output directory for every command; existing evidence should not be overwritten.

The unit suite needs Python 3.9+ and no model account. Live replay needs Anvil and Cast **1.7.1** plus Solidity **0.8.28**. Put them on PATH, or set `AUTO_PROVE_ANVIL`, `AUTO_PROVE_CAST`, and `AUTO_PROVE_SOLC` to their installed paths. Installation references are in `README.md` and `GENERAL_PIPELINE.md`. No external chain, wallet or model account is required for the following fixture checks. `bash scripts/verify_attacks.sh` runs every stage below with assertions; each stage can also be run by hand.

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

These cases have unit coverage, and the stale-digest and runtime-failure cases are also asserted live by `scripts/verify_attacks.sh`. Independent hostile-input review beyond that coverage remains necessary.

### 6. Creator review records

```sh
python3 -m general propose-policy \
  general/fixtures/attacks/snapshot.json general/fixtures/attacks/draft-policy.json \
  --output runs/reproduced-policy-proposal
python3 -m general review-policy \
  general/fixtures/attacks/snapshot.json runs/reproduced-policy-proposal/proposal.json \
  general/fixtures/attacks/creator-decisions.json --output runs/reproduced-policy-review
```

Expected: a review packet showing each requirement's English, intent quotation, observed state fields, predicate, assumptions and mapped Lean target; then a recorded approve/reject decision. The reviewed policy (`reviewed-policy.json`) is the operational policy used for the reviewed attack/acceptance chain; the record keeps `accepted: false` and `creator_approval: pending`.

### 7. Second contract family: MilestoneEscrow

```sh
python3 -m general attack general/fixtures/escrow/snapshot.json general/fixtures/escrow/draft-policy.json \
  general/fixtures/escrow/attack-safe.json --output runs/reproduced-escrow-safe   # exits 1: not_demonstrated
python3 -m general attack general/fixtures/escrow/snapshot.json general/fixtures/escrow/draft-policy.json \
  general/fixtures/escrow/attack-double-release.json --output runs/reproduced-escrow-double-release
```

Expected: the safe trace is `not_demonstrated`; the double release is `demonstrated_proposed_requirement_violation` while the requirement is pending review, and acceptance is blocked. `attack-other-payer.json` challenges the ambiguous registered-seller intent requirement the same way. Then run the propose/review flow for the escrow policy (approve `ReleaseWithinDeposit`, reject the proposed `OtherPayerBacking` reading), attack with the reviewed policy (`demonstrated_spec_requirement_violation`), accept, and re-run `regress-attacks` against the unrepaired snapshot (`still_violates_original_requirement`). `general/evidence/escrow/` holds the kernel-checked `ReleasedWithinDeposit` refutation.

These are developer-authored demonstrations, not agent discoveries; they exercise the same contribution format and runner on a different contract family, including a case with no violation and a case requiring creator clarification.

## What still needs building and verification

| Area | Remaining work |
| --- | --- |
| Operational-policy authoring | Agent-generated proposals (the current drafts are developer/maintainer-authored); stronger checks linking the operational condition to its Lean target and intended meaning |
| Public submission boundary | Protected snapshot/policy ownership, authenticated contributor identity, schema/API validation, size/rate limits and isolation review |
| Transaction coverage | Multi-contract dependencies, callback participants, richer ABI observations and additional scenario/environment controls |
| Formal connection | Link concrete state histories to generated models; keep exact Lean refutation and concrete observations distinct until that connection is established |
| Verification | Malformed-input live runs beyond unit coverage, concurrency/corruption cases, resource limits, hostile-input review |
| Regression governance | Reviewed requirement evolution, case migration, mapping changes and explicit decisions about deprecated requirements |
| Yukon integration | Hosted transaction-contribution mode, authenticated attribution, version-linked discussion links, hosted replay artifacts and acceptance workflow (interim maintainer-mediated protocol documented in YUKON_CHALLENGE.md; platform import and auth remain blockers) |
| Rewards | Written rules exist in REWARDS.md; semantic-duplicate review in practice, payout review with a live population, and collusion-incentive analysis remain |
| Evaluation | Agent-discovered findings on additional contract families, safe/unsafe held-out cases, false-positive measurement and cost/budget limits |

The existing Yukon manifest still accepts proposer/reviewer prompt changes. **Direct transaction contributions are local CLI artifacts; they are not yet a live Yukon submission mode.** No new platform integration, public challenge, voting system, reward allocation or payout has been implemented.

## What to do next, in order

Status is recorded per step; earlier completed steps remain reproducible.

### 1. Independently verify the current local loop — **completed 2026-10-05**

**Owner:** maintainer / verification researcher.

Run the commands in the inspection and testing section from a fresh checkout. Record the commit, runtime versions, command outcomes, receipts, state histories and requirement evaluations. Check both existing-specification and intent-gap examples, acceptance, duplicate handling, and original/source-patched regressions. Also verify that removing a requirement cannot erase its accepted case.

**Deliverable:** a verification report with reproducible, credential-free evidence and a list of failures or inconclusive checks. Label each expected outcome confirmed, failed or not run. **Recorded report:** `runs/reproduced-verification-2026-10-05/report.md` — every fixture outcome confirmed by live replay; the prior `Operation not permitted` failure did not reproduce. `scripts/verify_attacks.sh` now encodes the checks with assertions, and CI runs them.

### 2. Fix discrepancies and make verification repeatable — **completed 2026-10-05**

No discrepancies were found in step 1. `test_attacks.py` is included in `general-verifier.yml`; `transaction-attacks.yml` runs `scripts/verify_attacks.sh` as a model-free live-integration job with pinned Anvil/Cast 1.7.1 and checksum-verified solc 0.8.28. Infrastructure failures remain `inconclusive` and are asserted distinct from rejected contributions.

### 3. Complete creator review and specification revision — **completed for the internal fixture path**

The proposal → creator decision → concrete evidence → revision chain is implemented (`propose-policy` / `review-policy`) and exercised end to end on the internal fixture: reviewed policy → live attack → accepted case → regenerated repaired-source revision (frozen, kernel-checked observations and refutation recorded in `general/evidence/lending-fixed/`) → historical regression reporting `requires_mapping_review` → recorded creator review of the revised mapping → final concrete attack `not_demonstrated`. Model observations, concrete requirement failures and exact Lean refutations remain separately labeled. The decisions recorded so far are internal-fixture reviews by the repo maintainer; **they do not constitute production creator approval of any contract** — a real creator must record their own decisions per challenge.

### 4. Add direct contributions to an internal Yukon challenge — **submission mode implemented; platform import pending**

The contribution mode is now the benchmark's real submission surface: `editablePaths: ["submission"]` (heesch pattern), a fail-closed backend verifier (`general/contribution_benchmark.py`) that replays contributions on a disposable local Anvil and kernel-checks formal refutations (nanoda + con-ron), maintainer-owned `challenge/` version files produced through the recorded propose/review flow, a pinned-runtime `setup.sh`/`run.sh`, and a secret-free hosted workflow (`benchmark.yml`). The staging site presents it at https://auto-prove-challenge.vercel.app. Remaining for the deliverable (one independent external contributor end to end): `yukon login <api-key>` (currently missing/invalid auth), Yukon GitHub App installation on the repository, and registry import with the Yukon team.

### 5. Test transfer and useful diversity — **second family completed with developer fixtures; agent-discovered diversity open**

The MilestoneEscrow family runs through the same contribution format and runner with all three case types: no violation demonstrated (`attack-safe`), a real requirement failure (double release, accepted and surviving regression), and a creator-clarification case (ambiguous registered-seller intent, demonstrated as `proposed`, acceptance blocked, approve/reject decision recorded). All demonstrations are developer-authored and kept separate from agent discoveries; inviting independently operated agents/model families on held-out cases remains open.

### 6. Define monetary credit before a rewarded public pilot — **rules written; pilot not run**

Written rules exist in REWARDS.md: credit classes and conditions, semantic-duplicate and multi-account handling, dispute procedure, bounded test budget, and an auditable acceptance-to-reward record. Reviewing the rules against a live adversarial population, and any actual payout, remain open. No payout has been implemented or authorized.

### Later scope

After the internal milestone, extend multi-contract and callback scenarios, richer observations, formal model/execution connections and reviewed requirement migration. A public pilot should have held-out evaluation, tested submission isolation and clear limits on its claims. Broad contract support and comprehensive security certification are not prerequisites for a narrowly scoped internal test, and are not established by it.

## First acceptance milestone — **reproduced 2026-10-05**

An independent reviewer can reproduce both types of requirement violation, accept one reviewed finding, recover its saved case in a fresh process, show that a specification change cannot hide it, and distinguish a selected source repair from formal proof and comprehensive security. All of these are reproduced by `scripts/verify_attacks.sh` and the recorded revision evidence; the remaining milestone clause is wiring the reviewed contribution format into a hosted Yukon mode and testing one external contributor end to end, which stays platform-blocked (see YUKON_CHALLENGE.md).
