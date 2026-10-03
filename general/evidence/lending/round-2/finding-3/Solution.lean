module
public import Model
public section
namespace AutoSpec
theorem req_OtherClaimAvailability : ¬ (∀ (s : State) (borrower honest amount : Nat), borrower ≠ honest → s.debt honest = 0 → s.collateral honest ≤ s.pool → 0 < amount → withdrawAllowed s borrower amount → (withdraw s borrower amount true).collateral honest ≤ (withdraw s borrower amount true).pool) := by
  intro h
  have hd : (1 : Nat) ≠ 0 := by decide
  have hz : attackBorrowed.debt 0 = 0 := by decide
  have hp : attackBorrowed.collateral 0 ≤ attackBorrowed.pool := by decide
  have hpos : 0 < (100 : Nat) := by decide
  have ha : withdrawAllowed attackBorrowed 1 100 := by decide
  have hn : ¬ ((withdraw attackBorrowed 1 100 true).collateral 0 ≤ (withdraw attackBorrowed 1 100 true).pool) := by decide
  exact hn (h attackBorrowed 1 0 100 hd hz hp hpos ha)
end AutoSpec
