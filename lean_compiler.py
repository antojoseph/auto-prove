"""Render only schema-validated policy choices, never execute model-supplied code."""
from __future__ import annotations
import hashlib, json, os, re, shutil, subprocess
from pathlib import Path
from engine import ROOT, validate_candidate


def lean_binary():
    if os.environ.get("ESCROW_LEAN"):
        return os.environ["ESCROW_LEAN"]
    bundled=ROOT / ".tools/lean-4.22.0-darwin_aarch64/bin/lean"
    if bundled.is_file():
        return str(bundled)
    return shutil.which("lean") or str(bundled)


def lean_action(a):
    ok = str(a["transfer_ok"]).lower()
    if a["kind"] == "fund": return f".fund {str(a['caller']=='alice').lower()} {a['amount']} {ok}"
    if a["kind"] == "donate": return f".donate {a['amount']} {ok}"
    who = ".beneficiary" if a["caller"] == "bob" else ".other"
    return f".release {who} {a['time']} {ok}"


def render(candidate, findings):
    validate_candidate(candidate)
    p = candidate["policy"]
    values = [p["caller"]=="anyone", p["recipient"]=="beneficiary", p["unlock"]=="at_or_after",
              p["unlock"]=="always", p["payout"]=="all_balance", p["repeat"]=="once",
              p["failure"]=="rollback", p["scope"]=="arbitrary_callers"]
    digest=hashlib.sha256(json.dumps(candidate,sort_keys=True).encode()).hexdigest()
    lines=["import Escrow", "namespace Candidate", "open Escrow", f"-- Candidate SHA256: {digest}",
           "def policy : Policy := ⟨"+", ".join(str(v).lower() for v in values)+"⟩",
           "-- This is a formal target, not a claim that English meaning was certified.",
           "def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),",
           "  release policy c s who now ok = release intendedPolicy c s who now ok"]
    for i,f in enumerate(findings):
        if not f["validated"]: continue
        actions=", ".join(lean_action(a) for a in f["trace"])
        lines += [f"def trace{i} : List Action := [{actions}]",
                  f"theorem mismatch{i} : observe policy exampleConfig {{}} trace{i} ≠ observe intendedPolicy exampleConfig {{}} trace{i} := by decide",
                  f"#print axioms mismatch{i}"]
    if not any(f["validated"] for f in findings) and values == [True,True,True,False,False,True,True,True]:
        lines += ["theorem matchesReference : preservesIntendedBehavior := by intro c s who now ok; rfl",
                  "#print axioms matchesReference"]
    return "\n".join(lines+["end Candidate", ""])


def verify(candidate, evaluation, output_dir):
    output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/"lean/Escrow.lean",output_dir/"Escrow.lean")
    (output_dir/"Candidate.lean").write_text(render(candidate,evaluation["findings"]))
    executable=lean_binary()
    if not Path(executable).is_file():
        return dict(status="unavailable", kernel_checked=False, error="See README.md: set ESCROW_LEAN to pinned Lean 4.22.0")
    env=dict(os.environ,LEAN_PATH=str(output_dir.resolve()),ELAN_TOOLCHAIN="leanprover/lean4:v4.22.0")
    version=subprocess.run([executable,"--version"],capture_output=True,text=True,timeout=15,env=env)
    if "version 4.22.0," not in version.stdout:
        return dict(status="wrong_toolchain",kernel_checked=False,error="Requires exactly Lean 4.22.0")
    commands=[[executable,"-DwarningAsError=true","-o","Escrow.olean","Escrow.lean"],
              [executable,"-DwarningAsError=true","Candidate.lean"]]
    log=[]
    try:
        for command in commands:
            result=subprocess.run(command,cwd=output_dir,env=env,capture_output=True,text=True,timeout=45)
            log.append(result.stdout+result.stderr)
            if result.returncode:
                (output_dir/"lean-check.log").write_text("\n".join(log))
                return dict(status="failed",kernel_checked=False,error=log[-1][:3000])
        output="\n".join(log)
        (output_dir/"lean-check.log").write_text(output)
        axioms=[]
        for group in re.findall(r"depends on axioms: \[([^\]]*)\]",output):
            axioms.extend(a.strip() for a in group.split(",") if a.strip())
        # propext is Lean's standard propositional-extensionality axiom. No proof
        # placeholders, unchecked native_decide certificates or custom axioms.
        forbidden=set(axioms)-{"propext"}
        if forbidden: return dict(status="forbidden_axioms",kernel_checked=False,axioms=sorted(forbidden))
        return dict(status="checked",kernel_checked=True,axioms=sorted(set(axioms)),
                    validated_witnesses=sum(f["validated"] for f in evaluation["findings"]),
                    reference_equivalence_proved="matchesReference" in output,
                    scope="Abstract transition model and generated witness/target claims only; human semantic review and EVM correspondence remain separate.")
    except subprocess.TimeoutExpired:
        return dict(status="timeout",kernel_checked=False,error="Lean check exceeded 45 seconds")
