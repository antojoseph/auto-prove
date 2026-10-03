import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: ae88384d3b270f8314abe2daf4307acb1ddf75b60852720287e88ecd1c5b3275
def policy : Policy := ⟨true, false, true, false, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .other 10 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
