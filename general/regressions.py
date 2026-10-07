"""Model-free integration gates; run after building general/verifier image."""
from pathlib import Path
from .core import freeze, theorem_source, write, counterexample_snapshot
from .backend import verify


def run(output):
    output = Path(output)
    if output.exists(): raise ValueError('Use a new regression output directory')
    output.mkdir(parents=True)
    prop = {'id':'Identity','requirement':'Checker test only', 'intent_basis':'Developer regression',
            'statement':'∀ n : Nat, ident n = n', 'explanation':'Transport fixture, not security coverage', 'proof':'by intro n; rfl'}
    candidate = dict(status='supported', summary='Verification regression', threat_model=[],
                     model_body='def ident (n : Nat) : Nat := n', properties=[prop],
                     assumptions=[], unresolved_questions=[], execution_gaps=['Not a security specification'])
    data = dict(id='CheckerRegression',intent='Exercise trusted verifier gates',contract_source='contract Empty {}')
    snapshot = freeze(data,candidate)
    cases = [('valid',theorem_source(snapshot['material']['specification'],{'Identity':'by intro n; rfl'}),'proved'),
             ('sorry',theorem_source(snapshot['material']['specification'],{'Identity':'by sorry'}),'rejected'),
             ('wrong-target','module\npublic import Model\npublic section\nnamespace AutoSpec\ntheorem req_Identity : True := by trivial\nend AutoSpec\n','rejected'),
             ('custom-axiom','module\npublic import Model\npublic section\nnamespace AutoSpec\naxiom fabricated : ∀ n : Nat, ident n = n\ntheorem req_Identity : ∀ n : Nat, ident n = n := fabricated\nend AutoSpec\n','rejected'),
             ('equivalent-body-replacement','module\npublic import Std\n@[expose] public section\nnamespace AutoSpec\ndef ident (n : Nat) : Nat := n + 0\ntheorem req_Identity : ∀ n : Nat, ident n = n := by intro n; simp [ident]\nend AutoSpec\n','rejected')]
    results=[]
    for name, source, expected in cases:
        print('Checking '+name,flush=True)
        actual=verify(snapshot,source,output/name)
        results.append(dict(name=name,expected=expected,result=actual))
    # Both versions prove the inequality, but the function's meaning differs.
    # Comparator must reject this even though the theorem name/type text match.
    candidate['properties']=[dict(prop,statement='∀ n : Nat, ident n ≤ n',proof='by intro n; exact Nat.le_refl n')]
    bound_target=freeze(data,candidate)
    changed='module\npublic import Std\n@[expose] public section\nnamespace AutoSpec\ndef ident (_n : Nat) : Nat := 0\ntheorem req_Identity : ∀ n : Nat, ident n ≤ n := by intro n; exact Nat.zero_le n\nend AutoSpec\n'
    result=verify(bound_target,changed,output/'changed-definition')
    results.append(dict(name='changed-definition',expected='rejected',result=result))
    # Genuine refutation of a frozen false target, not an arbitrary true lemma.
    bad = dict(prop,statement='ident 1 = 0',proof='by sorry')
    candidate['properties']=[bad]; false_target=freeze(data,candidate)
    negative=counterexample_snapshot(false_target,'Identity')
    result=verify(negative,theorem_source(negative['material']['specification'],{'Identity':'by decide'}),output/'counterexample')
    results.append(dict(name='counterexample',expected='proved',result=result))
    passed=all(row['expected']==row['result']['status'] for row in results)
    write(output/'regressions.json',dict(passed=passed,cases=results))
    if not passed: raise RuntimeError('A verifier regression failed; inspect logs')
    print('All seven independent verification gates passed',flush=True)
    return results


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
