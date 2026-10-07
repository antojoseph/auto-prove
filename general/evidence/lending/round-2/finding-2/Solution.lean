module
public import Model
public section
namespace AutoSpec
theorem req_BorrowCap : ¬ (∀ (s : State) (who amount callbackAmount : Nat), borrowAllowed s who amount → (borrowWithWithdrawal s who amount callbackAmount true).debt who ≤ (borrowWithWithdrawal s who amount callbackAmount true).collateral who / 2) := by
  intro h
  have ha : borrowAllowed attackStart 1 50 := by decide
  have hn : ¬ ((borrowWithWithdrawal attackStart 1 50 100 true).debt 1 ≤ (borrowWithWithdrawal attackStart 1 50 100 true).collateral 1 / 2) := by decide
  exact hn (h attackStart 1 50 100 ha)
end AutoSpec
