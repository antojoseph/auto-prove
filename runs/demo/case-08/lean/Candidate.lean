import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 6b1e28948af0600ca1c1648983c613e1a01754f45ccc9969c6cc361fdd09dcbd
def policy : Policy := ⟨true, true, true, false, false, true, false, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .beneficiary 10 false, .release .beneficiary 11 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
