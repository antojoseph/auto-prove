module
public import Model
public section
namespace AutoSpec
theorem req_CollateralLock : ¬ (∀ (s : State) (who amount : Nat), 0 < amount → withdrawAllowed s who amount → (withdraw s who amount true).debt who ≤ (withdraw s who amount true).collateral who / 2) := by
  intro h
  have hp : 0 < (100 : Nat) := by decide
  have ha : withdrawAllowed attackBorrowed 1 100 := by decide
  have hn : ¬ ((withdraw attackBorrowed 1 100 true).debt 1 ≤ (withdraw attackBorrowed 1 100 true).collateral 1 / 2) := by decide
  exact hn (h attackBorrowed 1 100 hp ha)
end AutoSpec
