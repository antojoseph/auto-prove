import Std

namespace Escrow

-- Sequential, abstract token accounting. This is not EVM semantics.
structure Config where
  amount : Nat
  deadline : Nat
deriving Repr, DecidableEq

inductive Caller where
  | beneficiary
  | other
deriving Repr, DecidableEq

structure State where
  funded : Bool := false
  released : Bool := false
  balance : Nat := 0
  paid : Nat := 0
  beneficiaryPaid : Nat := 0
  otherPaid : Nat := 0
deriving Repr, DecidableEq

structure Policy where
  anyCaller : Bool
  recipientIsBeneficiary : Bool
  inclusiveDeadline : Bool
  noDeadline : Bool
  payEntireBalance : Bool
  oneRelease : Bool
  rollbackFailure : Bool
  allCallersInScope : Bool
deriving Repr, DecidableEq

def intendedPolicy : Policy := ⟨true, true, true, false, false, true, true, true⟩

inductive Result where
  | reverted
  | paid (recipient : Caller) (value : Nat)
  | outsideClaimDomain
deriving Repr, DecidableEq

def release (p : Policy) (c : Config) (s : State) (caller : Caller)
    (now : Nat) (transferOk : Bool) : State × Result :=
  if !p.allCallersInScope && caller != .beneficiary then
    (s, .outsideClaimDomain)
  else if !s.funded || (!p.anyCaller && caller != .beneficiary) ||
      (!p.noDeadline && (if p.inclusiveDeadline then now < c.deadline else now ≤ c.deadline)) ||
      (p.oneRelease && s.released) then
    (s, .reverted)
  else
    let value := if p.payEntireBalance then s.balance else c.amount
    if s.balance < value then (s, .reverted)
    else if !transferOk then
      (if p.rollbackFailure then s else { s with released := true }, .reverted)
    else
      let recipient := if p.recipientIsBeneficiary then Caller.beneficiary else caller
      let next : State := { s with
        released := true
        balance := s.balance - value
        paid := s.paid + value
        beneficiaryPaid := s.beneficiaryPaid + (if recipient = .beneficiary then value else 0)
        otherPaid := s.otherPaid + (if recipient = .other then value else 0) }
      (next, .paid recipient value)

def fund (c : Config) (s : State) (isDepositor : Bool) (value : Nat)
    (transferOk : Bool) : State :=
  if !s.funded && isDepositor && value == c.amount && transferOk then
    { s with funded := true, balance := s.balance + value }
  else s

def donate (s : State) (value : Nat) (transferOk : Bool) : State :=
  if transferOk then { s with balance := s.balance + value } else s

-- A target predicate on states reachable in the intended model.
def Safe (c : Config) (s : State) : Prop :=
  s.paid ≤ c.amount ∧ s.otherPaid = 0 ∧ s.beneficiaryPaid = s.paid ∧
  (s.released = false → s.paid = 0) ∧ (s.released = true → s.paid = c.amount)

theorem initial_safe (c : Config) : Safe c {} := by
  simp [Safe]

theorem fund_preserves_safe (c : Config) (s : State) (who : Bool)
    (value : Nat) (ok : Bool) (h : Safe c s) : Safe c (fund c s who value ok) := by
  unfold fund
  split <;> simpa [Safe] using h

theorem donate_preserves_safe (c : Config) (s : State) (value : Nat)
    (ok : Bool) (h : Safe c s) : Safe c (donate s value ok) := by
  unfold donate
  split <;> simpa [Safe] using h

theorem intended_release_preserves_safe (c : Config) (s : State)
    (who : Caller) (now : Nat) (ok : Bool) (h : Safe c s) :
    Safe c (release intendedPolicy c s who now ok).1 := by
  simp only [release, intendedPolicy, Bool.not_true, Bool.false_and,
    Bool.not_false, Bool.true_and, Bool.or_false, Bool.false_eq_true,
    ite_false, ite_true]
  split
  · exact h
  · rename_i eligible
    split
    · exact h
    · split
      · exact h
      · have unpaid : s.paid = 0 := by
          have unreleased : s.released = false := by
            cases hr : s.released <;> simp_all
          exact h.2.2.2.1 unreleased
        rcases h with ⟨cap, others, beneficiaries, zero, full⟩
        simp_all [Safe]

inductive Action where
  | fund (isDepositor : Bool) (value : Nat) (transferOk : Bool)
  | donate (value : Nat) (transferOk : Bool)
  | release (caller : Caller) (now : Nat) (transferOk : Bool)
deriving Repr

def step (c : Config) (s : State) : Action → State
  | .fund who value ok => fund c s who value ok
  | .donate value ok => donate s value ok
  | .release who now ok => (release intendedPolicy c s who now ok).1

def observedStep (p : Policy) (c : Config) (s : State) : Action → State × Result
  | .fund who value ok => (fund c s who value ok, .reverted)
  | .donate value ok => (donate s value ok, .reverted)
  | .release who now ok => release p c s who now ok

-- Funding/donation observations use a neutral Result marker. Release retains
-- the outcome as well as state, so an excluded caller is visible even on revert.
def observe (p : Policy) (c : Config) (s : State) : List Action → List (State × Result)
  | [] => []
  | a :: tail =>
      let output := observedStep p c s a
      output :: observe p c output.1 tail

def run (c : Config) (s : State) (actions : List Action) : State :=
  actions.foldl (step c) s

theorem step_preserves_safe (c : Config) (s : State) (a : Action)
    (h : Safe c s) : Safe c (step c s a) := by
  cases a with
  | fund who value ok => exact fund_preserves_safe c s who value ok h
  | donate value ok => exact donate_preserves_safe c s value ok h
  | release who now ok => exact intended_release_preserves_safe c s who now ok h

theorem all_traces_safe (c : Config) (s : State) (actions : List Action)
    (h : Safe c s) : Safe c (run c s actions) := by
  induction actions generalizing s with
  | nil => exact h
  | cons a tail ih => exact ih (step c s a) (step_preserves_safe c s a h)

theorem payout_cap_for_every_trace (c : Config) (actions : List Action) :
    (run c {} actions).paid ≤ c.amount :=
  (all_traces_safe c {} actions (initial_safe c)).1

theorem only_beneficiary_for_every_trace (c : Config) (actions : List Action) :
    (run c {} actions).otherPaid = 0 :=
  (all_traces_safe c {} actions (initial_safe c)).2.1

theorem before_deadline_reverts (c : Config) (s : State) (who : Caller)
    (now : Nat) (ok : Bool) (h : now < c.deadline) :
    release intendedPolicy c s who now ok = (s, .reverted) := by
  simp [release, intendedPolicy, h]

theorem failed_transfer_keeps_state (c : Config) (s : State) (who : Caller)
    (now : Nat) : (release intendedPolicy c s who now false).1 = s := by
  simp [release, intendedPolicy]

theorem repeat_release_reverts (c : Config) (s : State) (who : Caller)
    (now : Nat) (ok : Bool) (h : s.released = true) :
    release intendedPolicy c s who now ok = (s, .reverted) := by
  simp [release, intendedPolicy, h]

-- Explicit illustrative witnesses, not claims about a deployed Solidity contract.
def exampleConfig : Config := ⟨100, 10⟩
def fundedExample : State := { funded := true, balance := 100 }

example : release intendedPolicy exampleConfig fundedExample .other 10 true =
    ({ funded := true, released := true, balance := 0, paid := 100,
       beneficiaryPaid := 100 }, .paid .beneficiary 100) := by decide

example : release intendedPolicy exampleConfig fundedExample .other 9 true =
    (fundedExample, .reverted) := by decide

example : release intendedPolicy exampleConfig fundedExample .other 10 false =
    (fundedExample, .reverted) := by decide

#print axioms payout_cap_for_every_trace
#print axioms only_beneficiary_for_every_trace
#print axioms before_deadline_reverts
#print axioms failed_transfer_keeps_state
#print axioms repeat_release_reverts
end Escrow
