import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: bf688c018841d5b17d431938f11334e44dadab5a1522eab4ddce2d71cddb21ad
def policy : Policy := ⟨true, true, true, false, false, false, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
def trace0 : List Action := [.fund true 100 true, .donate 100 true, .release .other 10 true, .release .beneficiary 11 true]
theorem mismatch0 : observe policy exampleConfig {} trace0 ≠ observe intendedPolicy exampleConfig {} trace0 := by decide
#print axioms mismatch0
end Candidate
