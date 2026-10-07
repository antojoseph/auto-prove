module
public import Std
@[expose] public section
namespace AutoSpec
structure State where
  collateral : Nat → Nat
  debt : Nat → Nat
  pool : Nat

def maxUint : Nat := 2 ^ 256 - 1

def empty : State :=
  { collateral := fun _ => 0, debt := fun _ => 0, pool := 0 }

def put (f : Nat → Nat) (who value : Nat) : Nat → Nat :=
  fun a => if a = who then value else f a

abbrev depositAllowed (s : State) (who amount : Nat) : Prop :=
  s.collateral who + amount ≤ maxUint ∧ s.pool + amount ≤ maxUint

def deposit (s : State) (who amount : Nat) : State :=
  if depositAllowed s who amount then
    { s with collateral := put s.collateral who (s.collateral who + amount), pool := s.pool + amount }
  else s

abbrev receiveAllowed (s : State) (amount : Nat) : Prop :=
  s.pool + amount ≤ maxUint

def receiveEth (s : State) (amount : Nat) : State :=
  if receiveAllowed s amount then
    { s with pool := s.pool + amount }
  else s

abbrev borrowAllowed (s : State) (who amount : Nat) : Prop :=
  s.debt who + amount ≤ s.collateral who / 2 ∧
  s.debt who + amount ≤ maxUint ∧
  amount ≤ s.pool

def borrowSimple (s : State) (who amount : Nat) (accepts : Bool) : State :=
  if borrowAllowed s who amount ∧ accepts = true then
    { s with debt := put s.debt who (s.debt who + amount), pool := s.pool - amount }
  else s

abbrev withdrawAllowed (s : State) (who amount : Nat) : Prop :=
  amount ≤ s.collateral who ∧ amount ≤ s.pool

def withdraw (s : State) (who amount : Nat) (accepts : Bool) : State :=
  if withdrawAllowed s who amount ∧ accepts = true then
    { s with collateral := put s.collateral who (s.collateral who - amount), pool := s.pool - amount }
  else s

def borrowWithWithdrawal (s : State) (who amount callbackAmount : Nat) (accepts : Bool) : State :=
  if borrowAllowed s who amount ∧ accepts = true then
    withdraw (borrowSimple s who amount true) who callbackAmount true
  else s

def attackStart : State := deposit (deposit empty 0 100) 1 100

def attackBorrowed : State := borrowSimple attackStart 1 50 true

def attackPost : State := withdraw attackBorrowed 1 100 true

def attackNestedPost : State := borrowWithWithdrawal attackStart 1 50 100 true

def attackUnderwater : State := withdraw attackBorrowed 1 1 true

def attackDrained : State := withdraw attackUnderwater 1 99 true
end AutoSpec
