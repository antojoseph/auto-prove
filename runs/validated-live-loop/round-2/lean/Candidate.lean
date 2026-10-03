import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: d4e77b045daea3afa5af1173926288e0e81f42b4e112f3d5bb2706f8602fb89a
def policy : Policy := ⟨true, true, true, false, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
theorem matchesReference : preservesIntendedBehavior := by intro c s who now ok; rfl
#print axioms matchesReference
end Candidate
