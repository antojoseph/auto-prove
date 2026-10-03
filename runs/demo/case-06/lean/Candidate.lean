import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 7ac1b7a0520020f4d25b663a518ffe00b5b0c909fc0441e93aa525b47a53fa2e
def policy : Policy := ⟨true, true, true, false, true, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .donate 100 true, .release .beneficiary 10 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
