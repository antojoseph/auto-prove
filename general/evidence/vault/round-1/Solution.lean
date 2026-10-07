module
public import Model
public section
namespace AutoSpec
theorem req_InitialAuthority : ∀ (creator limit prefunded : Nat), (init creator limit prefunded).owner = creator ∧ (init creator limit prefunded).cap = limit := by
  intro creator limit prefunded
  simp [init]
theorem req_ImmutableAuthorityAndCap : ∀ (s : Vault) (a : Action), (step s a).next.owner = s.owner ∧ (step s a).next.cap = s.cap := by
  intro s a
  cases a with
  | deposit caller value =>
      by_cases h : s.balance + value ≤ s.cap
      · simp [step, deposit, h]
      · simp [step, deposit, h]
  | withdraw caller value payoutOk =>
      by_cases h : caller = s.owner ∧ value ≤ s.balance ∧ payoutOk = true
      · simp [step, withdraw, h]
      · simp [step, withdraw, h]
  | forced value =>
      simp [step, forceEther]
theorem req_OwnerOnlyWithdrawal : ∀ (s : Vault) (caller value : Nat) (payoutOk : Bool), caller ≠ s.owner → (withdraw s caller value payoutOk).success = false ∧ (withdraw s caller value payoutOk).next = s ∧ (withdraw s caller value payoutOk).paid = 0 := by
  intro s caller value payoutOk h
  have hguard : ¬ (caller = s.owner ∧ value ≤ s.balance ∧ payoutOk = true) := by
    intro hs
    exact h hs.1
  simp [withdraw, hguard]
theorem req_OwnerIsRecipient : ∀ (s : Vault) (caller value : Nat) (payoutOk : Bool), (withdraw s caller value payoutOk).paid > 0 → caller = s.owner ∧ (withdraw s caller value payoutOk).paidTo = s.owner := by
  intro s caller value payoutOk h
  by_cases hg : caller = s.owner ∧ value ≤ s.balance ∧ payoutOk = true
  · constructor
    · exact hg.1
    · simp [withdraw, hg]
  · simp [withdraw, hg] at h
theorem req_DepositCap : ∀ (s : Vault) (value : Nat), (deposit s value).success = true → (deposit s value).next.balance ≤ s.cap := by
  intro s value h
  by_cases hc : s.balance + value ≤ s.cap
  · simpa [deposit, hc] using hc
  · simp [deposit, hc] at h
theorem req_FailedPayoutRollback : ∀ (s : Vault) (caller value : Nat), (withdraw s caller value false).success = false ∧ (withdraw s caller value false).next = s ∧ (withdraw s caller value false).paid = 0 := by
  intro s caller value
  simp [withdraw]
end AutoSpec
