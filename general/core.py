"""General specification artifacts. No contract-family switches or reference model."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from pathlib import Path

VERSION = "general-pipeline-v1"
TOOLCHAIN = "4.35.0-rc2"
AXIOMS = ["propext", "Quot.sound", "Classical.choice"]
MAX_TEXT = 100_000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read(path):
    return json.loads(Path(path).read_text())


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise ValueError("Invalid or oversized " + label)
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", value):
        raise ValueError("Invalid identifier")
    return value


def validate_input(data):
    if not isinstance(data, dict):
        raise ValueError("Input must be an object")
    identifier(data["id"])
    text(data["intent"], "creator intent")
    text(data["contract_source"], "contract source")
    assumptions = data.get("approved_assumptions", [])
    if not isinstance(assumptions, list) or len(assumptions) > 50:
        raise ValueError("Invalid approved assumptions")
    for assumption in assumptions:
        text(assumption, "approved assumption")
    # Never execute source, prose or user-provided paths on the host.
    return copy.deepcopy(data)


def lean_tokens(source):
    """Discard comments/strings while retaining newlines; reject malformed comments.

    This restricts reviewed model syntax, not a substitute for execution isolation.
    Contributor proofs are arbitrary Lean and always compile in Docker.
    """
    out = []; i = 0; depth = 0
    while i < len(source):
        if depth:
            if source.startswith("/-", i): depth += 1; i += 2
            elif source.startswith("-/", i): depth -= 1; i += 2
            else:
                out.append("\n" if source[i] == "\n" else " "); i += 1
        elif source.startswith("/-", i): depth = 1; i += 2
        elif source.startswith("--", i):
            end = source.find("\n", i)
            if end == -1: break
            out.append("\n"); i = end + 1
        elif source[i] == '"':
            i += 1
            while i < len(source) and source[i] != '"':
                i += 2 if source[i] == "\\" else 1
            if i >= len(source): raise ValueError("Unclosed Lean string")
            i += 1; out.append('""')
        else: out.append(source[i]); i += 1
    if depth: raise ValueError("Unclosed Lean comment")
    return "".join(out)


FORBIDDEN = set("module import namespace section end open export public private protected theorem lemma axiom opaque constant instance attribute syntax macro macro_rules elab elab_rules initialize builtin_initialize unsafe partial extern implemented_by set_option run_elab run_tac native_decide sorry admit IO Lean Meta Command Tactic do by deriving".split())


def validate_model(source):
    tokens = lean_tokens(text(source, "model definitions"))
    words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", tokens))
    if words & FORBIDDEN or re.search(r'\w+!\s*"', tokens) or any(ch in tokens for ch in ["#", "@", "`", ";"]):
        raise ValueError("Unsupported model syntax; use pure def/abbrev/structure/inductive terms")
    # Only these top-level commands are permitted. Indented fields/constructors
    # are permitted; theorem proof syntax and command extensions are excluded.
    names = []
    for line in tokens.splitlines():
        if not line.strip() or line[0].isspace(): continue
        match = re.match(r"(?:def|abbrev|structure|inductive)\s+([A-Za-z][A-Za-z0-9_]*)\b", line)
        if not match: raise ValueError("Unsupported top-level model command")
        names.append(match.group(1))
    if not names or len(names) != len(set(names)):
        raise ValueError("Model needs unique declarations")
    return names


def validate_statement(source):
    tokens = lean_tokens(text(source, "target statement"))
    if "\n" in source or ":=" in tokens or re.search(r'\w+!\s*"', tokens) or any(ch in tokens for ch in ["#", "@", "`", ";"]):
        raise ValueError("A target must be one Lean type expression")
    words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", tokens))
    if words & FORBIDDEN:
        raise ValueError("Unsupported target expression")
    return source


def specification(candidate):
    """Freeze meaning artifacts separately from revisable proof attempts."""
    required = {"status", "summary", "threat_model", "model_body", "properties", "assumptions", "unresolved_questions", "execution_gaps"}
    if not isinstance(candidate, dict) or set(candidate) != required:
        raise ValueError("Candidate has unexpected or missing fields")
    if candidate["status"] not in ("supported", "unsupported"):
        raise ValueError("Invalid candidate status")
    text(candidate['summary'], 'candidate summary')
    for key in ('threat_model', 'assumptions', 'unresolved_questions', 'execution_gaps'):
        if not isinstance(candidate[key], list) or len(candidate[key]) > 50:
            raise ValueError('Invalid ' + key)
        for value in candidate[key]: text(value, key)
    spec = copy.deepcopy(candidate)
    if candidate["status"] == "unsupported": return spec
    validate_model(spec["model_body"])
    if not isinstance(spec["properties"], list) or not 1 <= len(spec["properties"]) <= 20:
        raise ValueError("Need 1-20 formal properties")
    ids = []
    for prop in spec["properties"]:
        if set(prop) != {"id", "requirement", "intent_basis", "statement", "explanation", "proof"}:
            raise ValueError("Invalid property fields")
        ids.append(identifier(prop["id"]))
        validate_statement(prop["statement"])
        text(prop["requirement"], "English requirement")
        text(prop["intent_basis"], "requirement provenance")
        text(prop["explanation"], "formal mapping")
        text(prop.pop("proof"), "proof attempt")
    if len(ids) != len(set(ids)): raise ValueError("Duplicate property identifier")
    return spec


def model_source(spec):
    return "module\npublic import Std\n@[expose] public section\nnamespace AutoSpec\n" + spec["model_body"] + "\nend AutoSpec\n"


def theorem_source(spec, proofs=None):
    lines = ["module", "public import Model", "public section", "namespace AutoSpec"]
    for prop in spec["properties"]:
        proof = "by sorry" if proofs is None else text(proofs[prop["id"]], "proof attempt")
        lines.append("theorem req_" + prop["id"] + " : " + prop["statement"] + " := " + proof)
    return "\n".join(lines) + "\nend AutoSpec\n"


def proof_term(value, expected):
    """Accept a term or a standard one-theorem file; never change the target.

    Agents sometimes return the complete module in the proof field. Unwrap
    only the fixed Model-import wrapper with the exact expected statement.
    The resulting term still compiles in isolation and requires kernel checks.
    """
    value = text(value, 'proof attempt')
    if not value.lstrip().startswith('module'): return value
    match = re.fullmatch(r'\s*module\s+public import Model\s+public section\s+namespace AutoSpec\s+theorem [A-Za-z][A-Za-z0-9_]*\s*:\s*(.*?)\s*:=\s*(.*?)\s+end AutoSpec\s*', value, re.S)
    if not match or re.sub(r'\s+', '', lean_tokens(match.group(1))) != re.sub(r'\s+', '', lean_tokens(expected)):
        raise ValueError('Standalone proof does not use the expected one-theorem Model wrapper and target')
    return text(match.group(2), 'unwrapped proof term')


def freeze(data, candidate):
    data = validate_input(data)
    spec = specification(candidate)
    if spec["status"] == "unsupported": raise ValueError("Cannot freeze an unsupported model")
    material = {"version": VERSION, "toolchain": TOOLCHAIN, "axioms": AXIOMS,
                "input": data, "specification": spec,
                "model_source": model_source(spec), "challenge_source": theorem_source(spec)}
    return {"digest": digest(material), "material": material,
            "creator_approval": "pending", "contract_correspondence": "not_proved"}


def validate_snapshot(snapshot):
    if snapshot.get("digest") != digest(snapshot["material"]):
        raise ValueError("Frozen specification changed")
    m = snapshot["material"]
    if m["version"] != VERSION or m["toolchain"] != TOOLCHAIN or m["axioms"] != AXIOMS:
        raise ValueError("Unsupported snapshot policy")
    validate_input(m["input"])
    candidate = copy.deepcopy(m["specification"])
    for prop in candidate["properties"]: prop["proof"] = "by sorry"
    spec = specification(candidate)
    if m["model_source"] != model_source(spec) or m["challenge_source"] != theorem_source(spec):
        raise ValueError("Frozen sources differ from the reviewed specification")
    if snapshot.get("creator_approval") != "pending" or snapshot.get("contract_correspondence") != "not_proved":
        raise ValueError("This pipeline does not grant semantic approval or contract correspondence")
    return snapshot


def counterexample_snapshot(snapshot, property_id):
    """Only proof of the EXACT frozen target's negation refutes that target."""
    validate_snapshot(snapshot)
    original = snapshot["material"]["specification"]
    prop = next((p for p in original["properties"] if p["id"] == property_id), None)
    if prop is None: raise ValueError("Unknown property")
    candidate = copy.deepcopy(original)
    candidate["properties"] = [dict(prop, statement="¬ (" + prop["statement"] + ")", proof="by sorry")]
    result = freeze(snapshot["material"]["input"], candidate)
    result["refutes_digest"] = snapshot["digest"]
    result["refutes_property"] = property_id
    return result


def review_check(snapshot, review):
    validate_snapshot(snapshot)
    if review["candidate_digest"] != snapshot["digest"]:
        raise ValueError("Reviewer evidence addresses a different candidate")
    ids = {p["id"] for p in snapshot["material"]["specification"]["properties"]}
    if len(review["findings"]) > 20: raise ValueError("Too many findings")
    for finding in review["findings"]:
        if finding["kind"] not in ("spec_gap", "contract_bug", "model_gap", "ambiguity"):
            raise ValueError("Unknown finding kind")
        if finding["property_id"] and finding["property_id"] not in ids:
            raise ValueError("Finding references unknown property")
        if finding["evidence_kind"] not in ("model_counterexample", "model_observation", "reasoning_only"):
            raise ValueError("Unknown evidence kind")
        if finding["evidence_kind"] == "model_counterexample":
            if not finding["property_id"]: raise ValueError("Counterexample needs a target")
            text(finding["proof"], "counterexample proof")
        elif finding["evidence_kind"] == "model_observation":
            validate_statement(finding["observation_statement"])
            text(finding["proof"], "observation proof")
    return copy.deepcopy(review)


def observation_snapshot(snapshot, finding):
    validate_snapshot(snapshot)
    candidate = copy.deepcopy(snapshot['material']['specification'])
    candidate['properties'] = [{
        'id': 'Observation', 'requirement': finding['reasoning'],
        'intent_basis': 'Adversary observation; interpretation pending',
        'statement': validate_statement(finding['observation_statement']),
        'explanation': 'A fact about the frozen model; English relevance is not proved.',
        'proof': 'by sorry'}]
    result = freeze(snapshot['material']['input'], candidate)
    result['observes_digest'] = snapshot['digest']
    return result
