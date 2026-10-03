// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;
import "../src/TokenEscrow.sol";

interface Vm {
    function warp(uint256 timestamp) external;
    function prank(address sender) external;
    function expectRevert(bytes4 selector) external;
}

contract MockToken is IERC20Escrow {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    bool public fail;
    bool public fee;
    address public callbackTarget;
    bool public callbackBlocked;
    function mint(address to, uint256 value) external { balanceOf[to] += value; }
    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value; return true;
    }
    function configure(bool fail_, bool fee_, address callback_) external {
        fail = fail_; fee = fee_; callbackTarget = callback_;
    }
    function transfer(address to, uint256 value) external returns (bool) {
        if (fail) return false;
        if (callbackTarget != address(0)) {
            (bool success,) = callbackTarget.call(abi.encodeCall(TokenEscrow.release, ()));
            callbackBlocked = !success;
        }
        _move(msg.sender, to, value); return true;
    }
    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        if (fail) return false;
        require(allowance[from][msg.sender] >= value, "allowance");
        allowance[from][msg.sender] -= value; _move(from, to, value); return true;
    }
    function _move(address from, address to, uint256 value) internal {
        require(balanceOf[from] >= value, "balance");
        balanceOf[from] -= value; balanceOf[to] += fee ? value - 1 : value;
    }
}

contract TokenEscrowTest {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address private constant BOB = address(0xB0B);
    address private constant EVE = address(0xE0E);
    MockToken private token;
    TokenEscrow private escrow;
    function setUp() public {
        vm.warp(1); token = new MockToken();
        escrow = new TokenEscrow(token, BOB, 100, 10);
        token.mint(address(this), 1000); token.approve(address(escrow), 100);
    }
    function testUnfundedReleaseReverts() public {
        vm.warp(10); vm.expectRevert(TokenEscrow.NotFunded.selector); escrow.release();
    }
    function testFundingRequiresDepositorAndOccursOnce() public {
        vm.expectRevert(TokenEscrow.NotDepositor.selector); vm.prank(EVE); escrow.fund();
        escrow.fund(); vm.expectRevert(TokenEscrow.AlreadyFunded.selector); escrow.fund();
    }
    function testBeforeDeadlineAndExactBoundary() public {
        escrow.fund(); vm.warp(9); vm.expectRevert(TokenEscrow.TooEarly.selector); escrow.release();
        vm.warp(10); vm.prank(EVE); escrow.release();
        require(token.balanceOf(BOB) == 100 && token.balanceOf(EVE) == 0, "recipient");
    }
    function testDonationDoesNotIncreaseEntitlementOrEnableRepeat() public {
        escrow.fund(); token.mint(address(escrow), 200); vm.warp(10); escrow.release();
        require(token.balanceOf(BOB) == 100 && token.balanceOf(address(escrow)) == 200, "surplus");
        vm.expectRevert(TokenEscrow.AlreadyReleased.selector); escrow.release();
    }
    function testTransferFailureRollsBackAndAllowsRetry() public {
        escrow.fund(); vm.warp(10); token.configure(true, false, address(0));
        vm.expectRevert(TokenEscrow.TokenTransferFailed.selector); escrow.release();
        require(!escrow.released() && token.balanceOf(address(escrow)) == 100, "rollback");
        token.configure(false, false, address(0)); vm.prank(EVE); escrow.release();
        require(escrow.released() && token.balanceOf(BOB) == 100, "retry");
    }
    function testFundingFailureRollsBack() public {
        token.configure(true, false, address(0));
        vm.expectRevert(TokenEscrow.TokenTransferFailed.selector); escrow.fund();
        require(!escrow.funded() && token.balanceOf(address(this)) == 1000, "fund rollback");
    }
    function testFeeOnTransferFundingRejected() public {
        token.configure(false, true, address(0));
        vm.expectRevert(TokenEscrow.IncorrectFundingAmount.selector); escrow.fund();
        require(!escrow.funded() && token.balanceOf(address(escrow)) == 0, "fee rollback");
    }
    function testReentrantReleaseBlocked() public {
        escrow.fund(); vm.warp(10); token.configure(false, false, address(escrow)); escrow.release();
        require(token.callbackBlocked() && token.balanceOf(BOB) == 100, "reentry");
    }
    function testLateFundingAllowed() public {
        vm.warp(20); escrow.fund(); vm.prank(EVE); escrow.release();
        require(token.balanceOf(BOB) == 100, "late funding");
    }
    function testInvalidConfigurationRejected() public {
        vm.expectRevert(TokenEscrow.InvalidConfiguration.selector); new TokenEscrow(token, BOB, 0, 10);
        vm.expectRevert(TokenEscrow.InvalidConfiguration.selector); new TokenEscrow(token, address(0), 100, 10);
        vm.expectRevert(TokenEscrow.InvalidConfiguration.selector); new TokenEscrow(token, BOB, 100, 1);
    }
    function testFuzzAnyCallerCannotRedirectOrRepeat(address caller, uint64 timestamp, uint64 donation) public {
        escrow.fund(); token.mint(address(escrow), uint256(donation));
        vm.warp(10 + uint256(timestamp)); vm.prank(caller); escrow.release();
        require(token.balanceOf(BOB) == 100 && token.balanceOf(address(escrow)) == uint256(donation), "fuzz payout");
        vm.expectRevert(TokenEscrow.AlreadyReleased.selector); vm.prank(caller); escrow.release();
    }
}
