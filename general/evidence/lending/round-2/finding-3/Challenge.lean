module
public import Model
public section
namespace AutoSpec
theorem req_OtherClaimAvailability : ¬ (∀ (s : State) (borrower honest amount : Nat), borrower ≠ honest → s.debt honest = 0 → s.collateral honest ≤ s.pool → 0 < amount → withdrawAllowed s borrower amount → (withdraw s borrower amount true).collateral honest ≤ (withdraw s borrower amount true).pool) := by sorry
end AutoSpec
