// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

interface IERC20Escrow {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
}

/// @notice Research prototype: one fixed entitlement, not a production deployment.
/// @dev Assumes the fixed token moves exactly the requested amount and does not
/// rebase. The Lean model abstracts external calls; callback behavior has tests.
contract TokenEscrow {
    IERC20Escrow public immutable token;
    address public immutable depositor;
    address public immutable beneficiary;
    uint256 public immutable amount;
    uint256 public immutable deadline;
    bool public funded;
    bool public released;

    error InvalidConfiguration();
    error NotDepositor();
    error AlreadyFunded();
    error NotFunded();
    error TooEarly();
    error AlreadyReleased();
    error TokenTransferFailed();
    error IncorrectFundingAmount();

    event Funded(address indexed depositor, uint256 amount);
    event Released(address indexed caller, address indexed beneficiary, uint256 amount);

    constructor(IERC20Escrow token_, address beneficiary_, uint256 amount_, uint256 deadline_) {
        if (address(token_).code.length == 0 || beneficiary_ == address(0) ||
            amount_ == 0 || deadline_ <= block.timestamp) revert InvalidConfiguration();
        token = token_;
        depositor = msg.sender;
        beneficiary = beneficiary_;
        amount = amount_;
        deadline = deadline_;
    }

    /// @notice Funding is permitted at or after the deadline as well as before it.
    function fund() external {
        if (msg.sender != depositor) revert NotDepositor();
        if (funded) revert AlreadyFunded();
        funded = true;
        uint256 beforeBalance = token.balanceOf(address(this));
        _callToken(abi.encodeCall(IERC20Escrow.transferFrom, (depositor, address(this), amount)));
        if (token.balanceOf(address(this)) != beforeBalance + amount) revert IncorrectFundingAmount();
        emit Funded(depositor, amount);
    }

    /// @notice Anyone may trigger release. The recipient is always beneficiary.
    function release() external {
        if (!funded) revert NotFunded();
        if (released) revert AlreadyReleased();
        if (block.timestamp < deadline) revert TooEarly();
        // Effects precede interaction, blocking repeat release during a callback.
        // Any failure reverts this flag together with the token's state.
        released = true;
        _callToken(abi.encodeCall(IERC20Escrow.transfer, (beneficiary, amount)));
        emit Released(msg.sender, beneficiary, amount);
    }

    function _callToken(bytes memory data) private {
        (bool success, bytes memory result) = address(token).call(data);
        if (!success || (result.length != 0 && (result.length != 32 || !abi.decode(result, (bool))))) {
            revert TokenTransferFailed();
        }
    }
}
