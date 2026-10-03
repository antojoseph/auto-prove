"""Deterministic replay of a bounded escrow specification language.

The reference interpretation is a manually authored research fixture. Matching it
does not establish that arbitrary natural language has been faithfully translated.
"""
from __future__ import annotations
from dataclasses import dataclass, replace, asdict
from collections import deque
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INTENT = json.loads((ROOT / "intent/creator.json").read_text())
REFERENCE = dict(caller="anyone", recipient="beneficiary", unlock="at_or_after",
                 payout="committed", repeat="once", failure="rollback",
                 scope="arbitrary_callers")
CHOICES = {k: tuple(v["enum"]) for k, v in json.loads(
    (ROOT / "schemas/candidate.json").read_text())["properties"]["policy"]["properties"].items()}
ACTORS = ("alice", "bob", "eve")


def validate_candidate(c):
    if not isinstance(c, dict) or set(c) != {"name", "policy", "requirement_mapping", "assumptions", "unresolved_questions"}:
        raise ValueError("Candidate must have exactly the schema fields")
    p = c["policy"]
    if not isinstance(c["name"], str) or not isinstance(p, dict) or set(p) != set(CHOICES):
        raise ValueError("Invalid name or policy fields")
    for k, v in p.items():
        if not isinstance(v, str) or v not in CHOICES[k]:
            raise ValueError(f"Unsupported policy value for {k}")
    mappings = c["requirement_mapping"]
    if not isinstance(mappings, list) or any(not isinstance(m, dict) or set(m) != {"requirement_id", "formal_meaning"}
        or not all(isinstance(x, str) for x in m.values()) for m in mappings):
        raise ValueError("Invalid requirement mappings")
    if sorted(m["requirement_id"] for m in mappings) != [f"R{i}" for i in range(1, 8)]:
        raise ValueError("Map each R1-R7 requirement exactly once")
    for k in ("assumptions", "unresolved_questions"):
        if not isinstance(c[k], list) or any(not isinstance(s, str) for s in c[k]):
            raise ValueError(f"Invalid {k}")
    return c


def validate_trace(trace):
    if not isinstance(trace, list) or not 1 <= len(trace) <= 12:
        raise ValueError("A trace must contain 1-12 steps")
    previous = 0
    for a in trace:
        if not isinstance(a, dict) or set(a) != {"kind", "caller", "time", "amount", "transfer_ok"}:
            raise ValueError("Invalid trace fields")
        if a["kind"] not in ("fund", "donate", "release") or a["caller"] not in ACTORS:
            raise ValueError("Invalid action or actor")
        if any(type(a[k]) is not int or not 0 <= a[k] <= 10**9 for k in ("time", "amount")):
            raise ValueError("Time and amount must be bounded nonnegative integers")
        if type(a["transfer_ok"]) is not bool or a["time"] < previous:
            raise ValueError("Invalid transfer flag or decreasing timestamp")
        if a["kind"] == "release" and a["amount"] != 0:
            raise ValueError("A release has no caller-selected amount")
        previous = a["time"]
    return trace


@dataclass(frozen=True)
class State:
    funded: bool = False
    released: bool = False
    balance: int = 0
    paid: int = 0
    bob: int = 0
    alice: int = 0
    eve: int = 0
    releases: int = 0


def step(s, a, p, amount=100, deadline=10):
    """Outcome plus poststate, including candidate quantification exclusions."""
    kind = a["kind"]
    if kind == "fund":
        if s.funded or a["caller"] != "alice" or a["amount"] != amount or not a["transfer_ok"]:
            return "revert", s
        return "ok", replace(s, funded=True, balance=s.balance + amount)
    if kind == "donate":
        if not a["transfer_ok"]:
            return "revert", s
        return "ok", replace(s, balance=s.balance + a["amount"])
    if p["scope"] == "beneficiary_only" and a["caller"] != "bob":
        return "outside_claim_domain", s
    unlocked = p["unlock"] == "always" or (a["time"] >= deadline if p["unlock"] == "at_or_after" else a["time"] > deadline)
    permitted = p["caller"] == "anyone" or a["caller"] == "bob"
    if not s.funded or not permitted or not unlocked or (p["repeat"] == "once" and s.released):
        return "revert", s
    value = amount if p["payout"] == "committed" else s.balance
    if s.balance < value:
        return "revert", s
    if not a["transfer_ok"]:
        return "revert", s if p["failure"] == "rollback" else replace(s, released=True)
    recipient = "bob" if p["recipient"] == "beneficiary" else a["caller"]
    fields = dict(released=True, balance=s.balance-value, paid=s.paid+value,
                  releases=s.releases+1, **{recipient: getattr(s, recipient)+value})
    return "ok", replace(s, **fields)


def replay(trace, p, amount=100, deadline=10):
    validate_trace(trace)
    expected = actual = State()
    rows = []
    requirements = set()
    for index, a in enumerate(trace):
        before_expected, before_actual = expected, actual
        eo, expected = step(expected, a, REFERENCE, amount, deadline)
        ao, actual = step(actual, a, p, amount, deadline)
        diffs = set()
        if eo != ao or expected != actual:
            if a["kind"] == "release":
                if ao == "outside_claim_domain": diffs.add("R7")
                if a["time"] < deadline and ao == "ok": diffs.add("R2")
                if eo == "ok" and ao != "ok": diffs.add("R2")
                if ao == "ok" and actual.releases > 1: diffs.add("R4")
                if actual.alice or actual.eve: diffs.add("R3")
                if actual.paid > amount: diffs.add("R4")
                if ao == "ok" and actual.paid-before_actual.paid != amount: diffs.add("R6")
                if not a["transfer_ok"] and actual != before_actual: diffs.add("R5")
            # Carry the first semantic disagreement through later observations.
            if not diffs: diffs.update(requirements)
        requirements.update(diffs)
        rows.append(dict(index=index, action=a, intended=dict(outcome=eo, state=asdict(expected)),
                         candidate=dict(outcome=ao, state=asdict(actual)), differences=sorted(diffs)))
    return dict(mismatch=bool(requirements), requirements=sorted(requirements), steps=rows)


def action(kind, caller="eve", time=10, amount=0, transfer_ok=True):
    return dict(kind=kind, caller=caller, time=time, amount=amount, transfer_ok=transfer_ok)


def search(p, amount=100, deadline=10, depth=4):
    """Bounded breadth-first search, with state-pair deduplication. No unbounded claim."""
    times = sorted(set((0, max(0, deadline-1), deadline, deadline+1)))
    alphabet = [action("fund", "alice", t, amount) for t in times]
    alphabet += [action("donate", "eve", t, amount) for t in times]
    alphabet += [action("release", who, t, transfer_ok=ok) for t in times for who in ACTORS for ok in (True, False)]
    queue = deque([(State(), State(), [], 0)])
    seen = set()
    checked = 0
    witnesses = {}
    while queue:
        ref, cand, trace, previous = queue.popleft()
        if len(trace) >= depth: continue
        for a in alphabet:
            if a["time"] < previous: continue
            ro, rn = step(ref, a, REFERENCE, amount, deadline)
            co, cn = step(cand, a, p, amount, deadline)
            extended = trace+[a]
            checked += 1
            if (ro, rn) != (co, cn):
                report = replay(extended, p, amount, deadline)
                for rid in report["requirements"]:
                    witnesses.setdefault(rid, extended)
            key = (rn, cn, a["time"], len(extended))
            if key not in seen:
                seen.add(key); queue.append((rn, cn, extended, a["time"]))
    return dict(depth=depth, transitions_checked=checked, witnesses=witnesses,
                status="bounded_mismatch_found" if witnesses else "no_mismatch_in_bounded_search")


def evaluate_review(candidate, review):
    validate_candidate(candidate)
    if not isinstance(review, dict) or set(review) != {"candidate_name", "findings", "unresolved_questions", "summary"}:
        raise ValueError("Invalid review fields")
    if review["candidate_name"] != candidate["name"] or not isinstance(review["summary"], str):
        raise ValueError("Review targets a different candidate")
    if not isinstance(review["unresolved_questions"], list) or any(not isinstance(q, str) for q in review["unresolved_questions"]):
        raise ValueError("Invalid unresolved questions")
    if not isinstance(review["findings"], list): raise ValueError("Invalid findings")
    findings = []
    for f in review["findings"]:
        if not isinstance(f, dict) or set(f) != {"requirement_id", "explanation", "trace"} or not isinstance(f["explanation"], str):
            raise ValueError("Invalid finding")
        if f["requirement_id"] not in [f"R{i}" for i in range(1, 8)]: raise ValueError("Unknown requirement")
        r = replay(f["trace"], candidate["policy"])
        findings.append(dict(**f, replay=r, validated=f["requirement_id"] in r["requirements"]))
    extra = sorted(set(candidate["assumptions"])-set(INTENT["approved_environment_assumptions"]))
    missing = sorted(set(INTENT["approved_environment_assumptions"])-set(candidate["assumptions"]))
    bounded = search(candidate["policy"])
    observed = set(bounded["witnesses"])
    supported = {f["requirement_id"] for f in findings if f["validated"]}
    return dict(candidate_name=candidate["name"], findings=findings, bounded_check=bounded,
        validated_findings=len([f for f in findings if f["validated"]]),
        unsupported_findings=len([f for f in findings if not f["validated"]]),
        detected_requirements=sorted(supported), missed_bounded_requirements=sorted(observed-supported),
        extra_assumptions=extra, missing_assumptions=missing,
        unresolved_questions=candidate["unresolved_questions"]+review["unresolved_questions"],
        accepted=False,
        disposition="mismatch_found" if observed or supported else "awaiting_creator_review",
        human_approval="pending",
        limitation="Replay validates witnesses against a hand-authored reference interpretation. It does not certify English-to-Lean fidelity or Solidity/EVM correspondence.")
