import Std

/- Separate, hand-authored accounting abstraction: two pools, one ERC20 currency,
   one rebate recipient per pool. Fee collection is an input, not a modeled AMM swap.
   No theorem below claims EVM correspondence or creator semantic approval. -/
namespace Rebate

structure Account where
  collected : Nat := 0
  earned : Nat := 0
  paid : Nat := 0
  deriving DecidableEq, Repr

structure State where
  a : Account := {}
  b : Account := {}
  custody : Nat := 0
  deriving DecidableEq, Repr

inductive Pool where | a | b deriving DecidableEq, Repr
inductive Action where
  | collect (pool : Pool) (fee : Nat)
  | claim (pool : Pool) (amount : Nat)
  deriving Repr

def get (s : State) : Pool → Account | .a => s.a | .b => s.b

def put (s : State) (p : Pool) (x : Account) (balance : Nat) : State :=
  match p with
  | .a => { s with a := x, custody := balance }
  | .b => { s with b := x, custody := balance }

def credit (x : Account) (fee : Nat) : Account :=
  { x with collected := x.collected + fee, earned := x.earned + fee / 2 }

def pay (x : Account) (n : Nat) : Account := { x with paid := x.paid + n }

def step (fixed : Bool) (s : State) : Action → State
  | .collect p fee => put s p (credit (get s p) fee) (s.custody + fee)
  | .claim p n =>
    let x := get s p
    let permitted := if fixed then x.paid + n ≤ x.earned ∧ x.paid + n ≤ x.collected
                     else n ≤ x.earned
    if 0 < n ∧ n ≤ s.custody ∧ permitted then
      put s p (pay x n) (s.custody - n)
    else s

def SafeAccount (x : Account) : Prop := x.paid ≤ x.earned ∧ x.earned ≤ x.collected

def Safe (s : State) : Prop := SafeAccount s.a ∧ SafeAccount s.b ∧
  s.custody + s.a.paid + s.b.paid = s.a.collected + s.b.collected

theorem credit_safe (x : Account) (fee : Nat) (h : SafeAccount x) :
    SafeAccount (credit x fee) := by
  have hf : fee / 2 ≤ fee := Nat.div_le_self fee 2
  simp only [SafeAccount, credit] at *
  omega

theorem step_safe (s : State) (a : Action) (h : Safe s) : Safe (step true s a) := by
  rcases h with ⟨ha, hb, hc⟩
  cases a with
  | collect p f =>
    cases p <;> simp only [step, get, put, Safe]
    · exact ⟨credit_safe s.a f ha, hb, by simp only [credit]; omega⟩
    · exact ⟨ha, credit_safe s.b f hb, by simp only [credit]; omega⟩
  | claim p n =>
    cases p <;> simp only [step, get, ↓reduceIte]
    · split
      next hn =>
        simp only [put, Safe, SafeAccount, pay]
        simp only [SafeAccount] at ha hb
        exact ⟨⟨hn.2.2.1, ha.2⟩, hb, by omega⟩
      next => exact ⟨ha, hb, hc⟩
    · split
      next hn =>
        simp only [put, Safe, SafeAccount, pay]
        simp only [SafeAccount] at ha hb
        exact ⟨ha, ⟨hn.2.2.1, hb.2⟩, by omega⟩
      next => exact ⟨ha, hb, hc⟩

def run (fixed : Bool) (xs : List Action) : State := xs.foldl (step fixed) {}

theorem run_safe_from (xs : List Action) (s : State) (h : Safe s) :
    Safe (xs.foldl (step true) s) := by
  induction xs generalizing s with
  | nil => exact h
  | cons a xs ih => exact ih (step true s a) (step_safe s a h)

theorem repaired_all_traces_safe (xs : List Action) : Safe (run true xs) :=
  run_safe_from xs {} (by simp [Safe, SafeAccount])

theorem other_pool_unchanged (fixed : Bool) (s : State) (p q : Pool) (n : Nat) (h : p ≠ q) :
    get (step fixed s (.claim p n)) q = get s q := by
  cases p <;> cases q <;> simp_all [step, get, put]
  all_goals split <;> split <;> rfl

-- Same fee/claim amounts as the concrete Foundry replay: 99, 99, then 49 three times.
def attack : List Action := [.collect .a 99, .collect .b 99,
  .claim .a 49, .claim .a 49, .claim .a 49]

theorem seeded_attack : (run false attack).a.paid = 147 ∧
    (run false attack).custody = 51 ∧ (run false attack).a.collected = 99 := by decide

theorem repaired_attack : (run true attack).a.paid = 49 ∧
    (run true attack).custody = 149 := by decide

theorem repaired_preserves_other_reserve (xs : List Action) :
    (run true xs).b.collected - (run true xs).b.paid ≤ (run true xs).custody := by
  have h := repaired_all_traces_safe xs
  simp only [Safe, SafeAccount] at h
  omega

#print axioms repaired_all_traces_safe
#print axioms other_pool_unchanged
#print axioms seeded_attack
#print axioms repaired_attack
#print axioms repaired_preserves_other_reserve
end Rebate
