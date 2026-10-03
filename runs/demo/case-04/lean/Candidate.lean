import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 67f7a594473012351f3c4cf2b37552a73666fc4b2f77a67b19e8110a3b06abef
def policy : Policy := ⟨true, true, false, false, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .beneficiary 10 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
