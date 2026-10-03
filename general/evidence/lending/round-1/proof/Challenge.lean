module
public import Model
public section
namespace AutoSpec
theorem req_DepositCredit : ∀ (s : State) (who amount : Nat), depositAllowed s who amount → (deposit s who amount).collateral who = s.collateral who + amount := by sorry
theorem req_BorrowCap : ∀ (s : State) (who amount : Nat), borrowAllowed s who amount → (borrow s who amount true).debt who ≤ (borrow s who amount true).collateral who / 2 := by sorry
theorem req_CollateralLock : ∀ (s : State) (who amount : Nat), s.debt who ≤ s.collateral who / 2 → withdrawAllowed s who amount → (withdraw s who amount true).debt who ≤ (withdraw s who amount true).collateral who / 2 := by sorry
theorem req_OtherClaimAvailability : ∀ (s : State) (borrower honest amount : Nat), borrower ≠ honest → s.debt honest = 0 → s.pool ≥ s.collateral honest → withdrawAllowed s borrower amount → (withdraw s borrower amount true).pool ≥ (withdraw s borrower amount true).collateral honest := by sorry
theorem req_AttackTrace : depositAllowed empty 0 100 ∧ depositAllowed (deposit empty 0 100) 1 100 ∧ borrowAllowed attackStart 1 50 ∧ withdrawAllowed attackBorrowed 1 100 ∧ attackBorrowed.debt 1 = 50 ∧ attackBorrowed.pool = 150 ∧ attackPost.debt 1 > attackPost.collateral 1 / 2 ∧ attackPost.pool < attackPost.collateral 0 := by sorry
end AutoSpec
