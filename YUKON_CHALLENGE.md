# Yukon internal challenge: intent-grounded smart-contract specifications

**Objective:** improve a reusable pipeline that receives Solidity source and English intent, generates meaningful security specifications, and supplies proofs, checked attacks, or explicit unresolved results. The same submission must work across new inputs without a bespoke family verifier.

**Primary audience:** contract security researchers, formal-methods researchers and agent developers. Creators supply code, intended protections and approved threat assumptions. Solvers improve the reusable proposer/adversary prompts. A creator sees a requirement-to-target mapping, assumptions, actual Lean statements, transaction evidence, proof/refutation status, changes between revisions and unresolved questions.

**First internal test:** use the public synthetic LendingPool and OwnerVault inputs. LendingPool contains a collateral withdrawal vulnerability. OwnerVault supplies different access-control and cap requirements. These two public examples are smoke tests, not sufficient hidden evaluation or evidence of broad generalization.

**Submission surface:** `prompts/general_proposer.txt` and `prompts/general_reviewer.txt`. Trusted orchestration supplies the same model, settings, schemas, bounded rounds and checking resources to each submission. Creators can add contract/intent cases without providing a reference Lean model. The fixed schemas and pure-model subset can produce unsupported results for complex contracts.

**Evaluation:** report semantic coverage separately from formal and concrete evidence. The proposed internal scoring harness uses a fixed independent assessor and creator-authored English rubric. Its numeric score is explicitly an AI-judged proxy, unsuitable for unsupervised prize payouts. Give zero credit for unsupported coverage, unapproved assumptions that bypass an intended threat, vacuity or unrelated tautologies. Evidence credit is contingent on the assessor mapping it to a meaningful requirement and the trusted checker supporting it. A contract bug is a useful result when reported honestly with an attack; a false safety claim must not receive proof credit.

**Before a public competition:** curate held-out safe/unsafe contracts and their intended protections; audit the rubric and assessor against trivial/assumption-based submissions; review the real cost and token budget per entry; choose the fixed model/settings; build historical concrete attack replay; review threat isolation for public submissions; and use creator review where English is ambiguous. Do not equate no new attacks after two rounds with completeness or safety.

**Platform readiness:** local CLI benchmark discovery returned missing/invalid Yukon authentication. Registry import also needs the benchmark repository installed under the Yukon GitHub App and coordination with the Yukon team. This draft has not been imported or launched on Yukon. It is intended for internal review and testing first.

**Success for next week:** one independently reviewed contract-and-intent example passes through the full pipeline; an attack exposes a missing requirement or a real code bug; its formal/concrete evidence is reproducible; the revision is frozen and checked without weakening the intended protection; a second contract uses the same machinery; and the report preserves all unsupported results and pending creator decisions.

## Runnable internal draft

`benchmark.json` is a schema-1 GitHub Actions manifest. `.yukon/setup.sh` builds the verifier; `.yukon/run.sh` runs both public smoke cases with a fixed account/model and a separate protected assessor prompt. Set `AUTO_PROVE_MODEL` to a model available to your authenticated Codex CLI account before running locally. The manual-only `benchmark.yml` workflow requires a dedicated `BENCHMARK_AUTH_JSON` repository secret and `AUTO_PROVE_MODEL` repository variable, neither of which this change configures. No scheduled run or external registry publication occurs here.

The creator-authored English rubric in `.yukon/rubric.json` gives the first proxy score: 60% AI-assessed meaningful coverage and 40% formally supported coverage. Formal evidence points require the assessor's mapping to an actual property and a trusted checked proof or exact-property counterexample. The assessor can still be wrong or fooled; the numeric result is for internal comparison, with pending creator approval explicitly included in score metrics. The public fixtures permit overfitting. The workflow intentionally has no public prize or payout integration.

The protected runner uses fixed schemas, orchestration, targets, axiom policy and assessor. Only the two generation/attack prompts are editable. Keep authentication outside the mounted proof inputs; no author or solver credentials belong in the repository. The first hosted run still needs account configuration, platform import and grading review.

## Community design: many agents, one persistent challenge

The two-role prototype is a minimal test of the checking mechanism, not the final solver topology. Yukon can expose the same immutable contract + intent to many independent agents and model families. Contributors propose formal requirements, attack existing statements, reproduce evidence and suggest repairs. Each contribution names the specification version it addresses; accepted revisions create a new frozen version and retain the earlier attacks as regression cases.

A discussion entry should include: the English protection; proposed Lean statement and referenced definitions; the threat or missing assumption; transaction trace or formal witness; checker/replay status; and the contributor's reasoning. Replies can offer alternative interpretations, defend or rebut a statement, and independently reproduce an attack. Diversity in models, tools, strategies and assumptions is useful when it produces distinct validated evidence.

Voting prioritizes unresolved statements and attacks for review. It must not act as a proof rule: popularity does not establish intent fidelity, and one reproducible counterexample can reopen a statement with overwhelming support. Duplicate accounts, colluding agents and copied findings must not gain correctness authority or multiply rewards. Creator decisions resolve ambiguities about intended policy; mechanical checks resolve the exact formal claims.

Potential incentives: reward the first meaningful supported attack, independent reproduction that strengthens confidence, a missing requirement confirmed by the creator, or a specification improvement that adds coverage without dropping earlier protections. Shared credit can recognize proposal, critique and repair. The initial internal proxy score is not an implementation of these economic rules.

Track useful diversity through unique supported attack classes, critical requirement coverage, unresolved assumptions, survival of old regression cases, independent model reproductions, time/cost to find a new issue and creator decisions—not raw agent count or vote count. Stopping after a budget or a period with no new findings means provisional convergence, never a security guarantee.

Board integration, version-linked contribution APIs, voting and reward allocation remain product design work. This change supplies local contribution artifacts and checking tools; it does not post to Yukon discussion boards or implement a live voting service.

The next local draft implements version-bound transaction submissions, maintainer-owned operational policies, state observations after each call and accepted-case regression storage. See [DESIGN_HANDOFF.md](DESIGN_HANDOFF.md) for the current implementation, reproduction commands and verification gaps. The existing platform manifest still accepts prompt changes; direct transaction contributions have not been integrated into Yukon.

## Direct transaction contributions: local mode and Yukon integration status

The transaction-contribution loop is implemented and live-verified locally (see `scripts/verify_attacks.sh` and `DESIGN_HANDOFF.md`): contributors submit a `transaction-attack-v1` JSON artifact naming the snapshot/policy digests, a requirement ID, reasoning and a bounded trace; the maintainer replays it with `python3 -m general attack`, records creator decisions with `propose-policy`/`review-policy`, accepts findings into the maintainer-owned registry with `accept-attack`, and replays historical cases with `regress-attacks`. A second contract family (MilestoneEscrow) exercises safe, violating and creator-clarification cases.

**Interim Yukon protocol (works with the current platform, no schema change):**

1. The challenge discussion entry for a challenge version publishes the current snapshot digest and reviewed-policy digest (maintainer artifacts, never solver-supplied).
2. A contributor posts the English protection, requirement ID, the transaction trace and reasoning as a version-linked discussion entry. The trace is data; the runner never executes contributor code.
3. The maintainer runs `general attack` / `accept-attack` and publishes the replay receipts, requirement evaluation and acceptance decision back to the entry. Rejected and inconclusive results stay visible with reasons.
4. Credit follows the rules in [REWARDS.md](REWARDS.md). Votes prioritize review order only.

**Hosted submission mode (requires Yukon platform work; not implemented):** the manifest schema would need a second submission surface besides `editablePaths` that uploads the contribution JSON, authenticates attribution server-side, enforces the existing size/shape limits, obtains snapshot and policy from the maintainer's pinned commit, runs the replay in the GitHub Actions runner, and publishes version-linked evidence. Local CLI benchmark discovery currently returns missing/invalid Yukon authentication, and registry import needs the repository installed under the Yukon GitHub App plus Yukon-team coordination; both remain blockers for any hosted run, including the first independent external contributor.

**Challenge staging site:** https://auto-prove-challenge.vercel.app (`web/` in this repository) presents the challenge to internal participants Yukon-style — staged under the slug `spec.prove` with the platform's public light theme: record cards, an evidence ledger in the promoted-results table format, per-step replay charts with "Fig." captions, and the terminal setup block. It includes a browser-side contribution composer that mirrors the CLI validators and computes snapshot/policy/submission digests client-side (verified to match the Python digests). It is a read-only static page: it hosts no checking, accepts no submissions, writes no registry, and must never be described as a live Yukon challenge or hosted verification — the status chip says `staged · internal pilot`. Refresh its evidence bundle with `python3 web/build_data.py` and redeploy from `web/`.
