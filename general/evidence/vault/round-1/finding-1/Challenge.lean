module
public import Model
public section
namespace AutoSpec
theorem req_Observation : (withdraw (init 1 20 20) 1 0 true).next.balance = 20 ∧ (withdraw (init 1 20 20) 1 0 true).paid = 0 := by sorry
end AutoSpec
