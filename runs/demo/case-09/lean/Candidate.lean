import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 683b469bf51c0a49add09ed66c1937cf8cf7dde642db450d566797b51f8a7e7d
def policy : Policy := ⟨true, true, true, false, false, true, true, false⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .release .other 10 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
