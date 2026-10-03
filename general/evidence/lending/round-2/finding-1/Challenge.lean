module
public import Model
public section
namespace AutoSpec
theorem req_CollateralLock : ¬ (∀ (s : State) (who amount : Nat), 0 < amount → withdrawAllowed s who amount → (withdraw s who amount true).debt who ≤ (withdraw s who amount true).collateral who / 2) := by sorry
end AutoSpec
