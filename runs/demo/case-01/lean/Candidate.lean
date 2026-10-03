import Escrow
namespace Candidate
open Escrow
-- Candidate SHA256: 0004924d9d291ddf73b4843e921385ee89cd180375df3756d6ef737ea44f6d6c
def policy : Policy := ⟨true, true, true, false, false, true, true, true⟩
-- This is a formal target, not a claim that English meaning was certified.
def preservesIntendedBehavior : Prop := ∀ (c : Config) (s : State) (who : Caller) (now : Nat) (ok : Bool),
  release policy c s who now ok = release intendedPolicy c s who now ok
theorem matchesReference : preservesIntendedBehavior := by intro c s who now ok; rfl
#print axioms matchesReference
end Candidate
