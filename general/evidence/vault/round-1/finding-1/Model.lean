module
public import Std
@[expose] public section
namespace AutoSpec
structure Vault where
  owner : Nat
  cap : Nat
  balance : Nat

structure Outcome where
  next : Vault
  success : Bool
  paidTo : Nat
  paid : Nat

inductive Action where
  | deposit (caller value : Nat)
  | withdraw (caller value : Nat) (payoutOk : Bool)
  | forced (value : Nat)

def init (creator limit prefunded : Nat) : Vault :=
  { owner := creator, cap := limit, balance := prefunded }

def deposit (s : Vault) (value : Nat) : Outcome :=
  if s.balance + value ≤ s.cap then
    { next := { s with balance := s.balance + value },
      success := true, paidTo := s.owner, paid := 0 }
  else
    { next := s, success := false, paidTo := s.owner, paid := 0 }

def forceEther (s : Vault) (value : Nat) : Outcome :=
  { next := { s with balance := s.balance + value },
    success := true, paidTo := s.owner, paid := 0 }

def withdraw (s : Vault) (caller value : Nat) (payoutOk : Bool) : Outcome :=
  if caller = s.owner ∧ value ≤ s.balance ∧ payoutOk = true then
    { next := { s with balance := s.balance - value },
      success := true, paidTo := s.owner, paid := value }
  else
    { next := s, success := false, paidTo := s.owner, paid := 0 }

def step (s : Vault) (a : Action) : Outcome :=
  match a with
  | .deposit _ value => deposit s value
  | .withdraw caller value payoutOk => withdraw s caller value payoutOk
  | .forced value => forceEther s value
end AutoSpec
