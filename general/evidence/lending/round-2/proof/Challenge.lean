module
public import Model
public section
namespace AutoSpec
theorem req_DepositCredit : ∀ (s : State) (who amount : Nat), depositAllowed s who amount → (deposit s who amount).collateral who = s.collateral who + amount := by sorry
theorem req_BorrowCheckBeforeCall : ∀ (s : State) (who amount : Nat), borrowAllowed s who amount → (borrowSimple s who amount true).debt who ≤ s.collateral who / 2 := by sorry
theorem req_BorrowCap : ∀ (s : State) (who amount callbackAmount : Nat), borrowAllowed s who amount → (borrowWithWithdrawal s who amount callbackAmount true).debt who ≤ (borrowWithWithdrawal s who amount callbackAmount true).collateral who / 2 := by sorry
theorem req_CollateralLock : ∀ (s : State) (who amount : Nat), 0 < amount → withdrawAllowed s who amount → (withdraw s who amount true).debt who ≤ (withdraw s who amount true).collateral who / 2 := by sorry
theorem req_OtherClaimAvailability : ∀ (s : State) (borrower honest amount : Nat), borrower ≠ honest → s.debt honest = 0 → s.collateral honest ≤ s.pool → 0 < amount → withdrawAllowed s borrower amount → (withdraw s borrower amount true).collateral honest ≤ (withdraw s borrower amount true).pool := by sorry
end AutoSpec
