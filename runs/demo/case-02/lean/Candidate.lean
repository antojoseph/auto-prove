import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 49d85f33f04e77736123a3572dc482cbf73a3d7fbcb420f5320b3cb690ba785f
def policy : Policy := ⟨false, true, true, false, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .other 10 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
