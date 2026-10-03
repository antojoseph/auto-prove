module
public import Model
public section
namespace AutoSpec
theorem req_BorrowCap : ¬ (∀ (s : State) (who amount callbackAmount : Nat), borrowAllowed s who amount → (borrowWithWithdrawal s who amount callbackAmount true).debt who ≤ (borrowWithWithdrawal s who amount callbackAmount true).collateral who / 2) := by sorry
end AutoSpec
