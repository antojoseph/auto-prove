# Reward rules for reviewed contributions (internal draft)

Status: written rules for a future bounded pilot. **No payout integration exists in this repository, and no monetary reward has been allocated or paid.** The current internal proxy score (`.yukon/rubric.json`, 60% AI-assessed coverage / 40% formally supported coverage) is a development metric, not these rules and not a payout mechanism.

These rules govern credit only. They never decide formal correctness (only the trusted checkers do), never resolve English ambiguity (only a recorded creator decision does), and never approve a contract. Every accepted finding still leaves `accepted: false`, `creator_approval: pending` and `contract_correspondence: not_proved`.

## What earns credit

| Credit class | Conditions |
| --- | --- |
| **Discovery credit** | The first reviewed contribution that demonstrates a violation of a maintainer-reviewed operational requirement (or an exact frozen Lean target) on the current challenge version. The finding must pass fresh trusted replay; an uploaded report is never credited. |
| **Reproduction credit** | An independent replay of an already-accepted case, from a distinct attribution and a distinct model family or toolchain, producing the trusted runner's receipts on the current version. Reproduction strengthens confidence; it never creates a second registry case (exact-case deduplication returns `duplicate`). |
| **Repair credit** | A source or specification revision that (a) keeps the original accepted case's condition and scenario, (b) passes the historical regression replay, (c) regenerates and re-reviews the formal mapping when it changes (`requires_mapping_review` must be resolved by a recorded creator decision), and (d) does not weaken or remove any other approved protection. A revision that makes a case pass by deleting the requirement earns no credit and reopens for review. |
| **Interpretation credit** | A creator-approved clarification that resolves an ambiguous intended protection into a new approved operational requirement, recorded through `propose-policy` / `review-policy`. |

Proof credit is already handled by the protected verifier: a formally supported proof or exact-target counterexample earns formal credit only when the trusted kernels accept it. Reasoning-only objections, vacuity, unapproved assumptions that bypass an intended threat, and unsupported coverage earn nothing.

## What never earns credit

- Copied or semantically equivalent findings. Exact duplication is detected by case identity; **semantic duplication is decided by human review**, not by the deduplication hash. A finding that re-demonstrates the same requirement violation on the same challenge version is a duplicate even with a different trace.
- Multiple accounts attributing the same discovery. Credit follows the case, not the account count; attribution is self-reported and cross-checked by the maintainer. Sybil behavior and collusion invalidate all credit from the colluding attributions for that case.
- Shared contributions: co-authors split one credit share, declared at submission time; post-hoc share changes require maintainer review.
- Attacks on stale snapshot/policy digests, submitter-supplied predicates or RPC endpoints, pending (unreviewed) requirements, and runtime failures reported as violations.
- A specification change that removes or weakens the attacked protection instead of fixing the defect.

## Review and disputes

- Maintainer acceptance (`accept-attack`, categories `contract_bug` / `spec_gap` / `model_gap`) is the only path into the accepted-case registry. Votes on the platform may prioritize which pending findings are reviewed first; **votes never override a reproducible counterexample, never grant review approval, and never decide credit**.
- A contributor may dispute an acceptance or a rejection by opening a version-linked discussion entry with the exact digests. The maintainer re-replays the case and records the decision with a reason. Disputes about intent meaning are resolved only by the creator; disputes about replay or proof results are resolved only by the trusted runner/verifier.
- Finding acceptance and payout authorization are separate steps. An accepted case can exist for an arbitrarily long period before any payout decision, and payout may be zero.

## Test budget

The internal pilot is bounded: at most one accepted case per requirement per challenge version for discovery credit; reproduction credit limited to two independent attributions per case; total credit-bearing contributions capped at twenty per challenge version. Infrastructure costs (replay, verifier containers) are borne by the maintainer's runner; contributor submissions are bounded by the existing schema limits (`maxSubmissionBytes: 65536`, 1-30 actions, 1-20 probes/requirements).

## Auditable acceptance-to-reward record

Every credit decision is recorded with:

- `case_id` and `origin_snapshot_digest` / `policy_digest` (the reviewed policy digest),
- the contributor attribution(s) and the submission digest,
- the maintainer decision (category and reason) and, where applicable, the creator review record digest,
- the credit class, share split, and the challenge version bound,
- the payout decision (initially: none), with its own reason and authorizer, stored separately from the finding record.

This record is append-only alongside the accepted-case registry; corrections are new entries that reference the original, never edits.

## Known limits

Exact-case deduplication is insufficient for semantic duplication; semantic-duplicate decisions are human and fallible. Self-reported attribution is not authenticated identity; platform authentication is required before any external pilot (Yukon integration). These rules have not been reviewed against a live adversarial population; the bounded internal pilot must precede any public, rewarded challenge.
