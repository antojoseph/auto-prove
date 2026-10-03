module
public import Model
public section
namespace AutoSpec
theorem req_Observation : (receiveEth empty 100).pool = 100 ∧ (receiveEth empty 100).collateral 2 = 0 := by decide
end AutoSpec
