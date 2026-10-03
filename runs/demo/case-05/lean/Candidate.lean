import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: d6d1f981446c65f345fd063e0b1c53907b3ce44efd9d7a66be129bd2cdd81fbf
def policy : Policy := ⟨true, true, false, true, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .beneficiary 9 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
