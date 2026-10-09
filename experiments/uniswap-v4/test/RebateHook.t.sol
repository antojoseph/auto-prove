// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Deployers} from "v4-core/test/utils/Deployers.sol";
import {Hooks} from "v4-core/src/libraries/Hooks.sol";
import {IHooks} from "v4-core/src/interfaces/IHooks.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {PoolId, PoolIdLibrary} from "v4-core/src/types/PoolId.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {MockERC20} from "solmate/src/test/utils/mocks/MockERC20.sol";
import {RebateHook} from "../src/RebateHook.sol";
import {DemoRouter} from "../src/DemoRouter.sol";

contract RebateHookTest is Deployers {
    using PoolIdLibrary for PoolKey;
    RebateHook hook;
    DemoRouter demoRouter;
    PoolKey poolA;
    PoolKey poolB;
    address constant BOB = address(0xB0B);

    function setUp() public {
        deployFreshManagerAndRouters();
        deployMintAndApprove2Currencies();
        demoRouter = new DemoRouter(manager);
        MockERC20(Currency.unwrap(currency0)).approve(address(demoRouter), type(uint256).max);
        MockERC20(Currency.unwrap(currency1)).approve(address(demoRouter), type(uint256).max);
    }

    function fixture(bool repaired) internal {
        address addr = address(uint160(Hooks.AFTER_SWAP_FLAG | Hooks.AFTER_SWAP_RETURNS_DELTA_FLAG));
        RebateHook impl = new RebateHook(manager, address(demoRouter), repaired);
        // Foundry-only placement at the required hook flag address; no network deployment.
        vm.etch(addr, address(impl).code);
        hook = RebateHook(addr);
        (poolA,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(addr), 100, SQRT_PRICE_1_1);
        (poolB,) = initPoolAndAddLiquidity(currency0, currency1, IHooks(addr), 500, SQRT_PRICE_1_1);
    }

    function swapIn(PoolKey memory pool, uint256 amount, bool zeroForOne) internal returns (uint256 fee) {
        Currency output = zeroForOne ? currency1 : currency0;
        uint256 beforeFee = hook.collected(pool.toId(), output);
        demoRouter.swap(pool, SwapParams(zeroForOne, -int256(amount), zeroForOne ? MIN_PRICE_LIMIT : MAX_PRICE_LIMIT));
        return hook.collected(pool.toId(), output) - beforeFee;
    }

    function testSeededAttackDrainsOtherPoolReserve() public {
        fixture(false);
        uint256 feeA = swapIn(poolA, 10_000, true);
        uint256 feeB = swapIn(poolB, 10_000, true);
        uint256 reward = feeA / 2;
        assertGt(reward * 3, feeA);
        for (uint256 i; i < 3; i++) hook.claim(poolA.toId(), currency1, reward);
        assertEq(hook.paid(poolA.toId(), currency1), reward * 3);
        assertGt(hook.claimed(poolA.toId(), currency1, address(this)), reward);
        assertLt(currency1.balanceOf(address(hook)), feeB); // B's backing was consumed
        assertEq(hook.paid(poolB.toId(), currency1), 0);
        emit log_named_uint("pool A fees", feeA);
        emit log_named_uint("pool B fees", feeB);
        emit log_named_uint("A paid after repeated claims", reward * 3);
        emit log_named_uint("remaining shared custody", currency1.balanceOf(address(hook)));
    }

    function testRepairRejectsSameAttackAndPreservesPoolBClaim() public {
        fixture(true);
        uint256 feeA = swapIn(poolA, 10_000, true);
        uint256 feeB = swapIn(poolB, 10_000, true);
        hook.claim(poolA.toId(), currency1, feeA / 2);
        uint256 custody = currency1.balanceOf(address(hook));
        vm.expectRevert(RebateHook.InvalidClaim.selector);
        hook.claim(poolA.toId(), currency1, feeA / 2);
        assertEq(currency1.balanceOf(address(hook)), custody);
        assertEq(hook.paid(poolA.toId(), currency1), feeA / 2);
        hook.claim(poolB.toId(), currency1, feeB / 2);
        assertEq(hook.paid(poolB.toId(), currency1), feeB / 2);
    }

    function testFuzzRepairBoundsSplitClaims(uint128 input, uint128 split, bool direction) public {
        fixture(true);
        uint256 amount = bound(uint256(input), 1000, 1e12);
        uint256 fee = swapIn(poolA, amount, direction);
        Currency output = direction ? currency1 : currency0;
        uint256 reward = fee / 2;
        uint256 first = bound(uint256(split), 0, reward);
        if (first > 0) hook.claim(poolA.toId(), output, first);
        if (reward > first) hook.claim(poolA.toId(), output, reward - first);
        assertEq(hook.claimed(poolA.toId(), output, address(this)), reward);
        assertEq(output.balanceOf(address(hook)), fee - reward);
        vm.expectRevert(RebateHook.InvalidClaim.selector);
        hook.claim(poolA.toId(), output, 1);
    }

    function testFeeRoundingAndCurrencyIsolation() public {
        fixture(true);
        uint256 fee = swapIn(poolA, 10_000, true);
        assertEq(fee, 99);
        assertEq(hook.earned(poolA.toId(), currency1, address(this)), 49);
        assertEq(hook.earned(poolA.toId(), currency0, address(this)), 0);
        uint256 reverseFee = swapIn(poolA, 10_000, false);
        assertGt(reverseFee, 0);
        assertEq(hook.earned(poolA.toId(), currency0, address(this)), reverseFee / 2);
    }

    function testAnotherUserCannotClaimMyCredit() public {
        fixture(true);
        swapIn(poolA, 10_000, true);
        vm.expectRevert(RebateHook.InvalidClaim.selector);
        vm.prank(BOB);
        hook.claim(poolA.toId(), currency1, 1);
    }

    function testAdditionalSwapsAddCreditAfterClaim() public {
        fixture(true);
        uint256 first = swapIn(poolA, 10_000, true) / 2;
        hook.claim(poolA.toId(), currency1, first);
        uint256 second = swapIn(poolA, 20_000, true) / 2;
        hook.claim(poolA.toId(), currency1, second);
        assertEq(hook.claimed(poolA.toId(), currency1, address(this)), first + second);
    }

    function testUntrustedRouterCannotSpoofRebateRecipient() public {
        fixture(true);
        vm.expectRevert();
        swapRouter.swap(poolA, SwapParams(true, -10_000, MIN_PRICE_LIMIT),
            _swapSettings(), abi.encode(BOB));
        assertEq(hook.collected(poolA.toId(), currency1), 0);
    }

    function _swapSettings() private pure returns (PoolSwapTest.TestSettings memory) {
        return PoolSwapTest.TestSettings(false, false);
    }

    function testFailedTransferRollsBackClaimAndCanRetry() public {
        fixture(true);
        uint256 reward = swapIn(poolA, 10_000, true) / 2;
        uint256 custody = currency1.balanceOf(address(hook));
        vm.mockCall(Currency.unwrap(currency1),
            abi.encodeWithSignature("transfer(address,uint256)", address(this), reward), abi.encode(false));
        vm.expectRevert();
        hook.claim(poolA.toId(), currency1, reward);
        assertEq(hook.claimed(poolA.toId(), currency1, address(this)), 0);
        assertEq(hook.paid(poolA.toId(), currency1), 0);
        assertEq(currency1.balanceOf(address(hook)), custody);
        vm.clearMockedCalls();
        hook.claim(poolA.toId(), currency1, reward);
        assertEq(hook.claimed(poolA.toId(), currency1, address(this)), reward);
    }

    function testTwoUsersHaveSeparateEntitlements() public {
        fixture(true);
        uint256 aliceCredit = swapIn(poolA, 10_000, true) / 2;
        MockERC20(Currency.unwrap(currency0)).mint(BOB, 20_000);
        vm.startPrank(BOB);
        MockERC20(Currency.unwrap(currency0)).approve(address(demoRouter), type(uint256).max);
        demoRouter.swap(poolA, SwapParams(true, -20_000, MIN_PRICE_LIMIT));
        uint256 bobCredit = hook.earned(poolA.toId(), currency1, BOB);
        hook.claim(poolA.toId(), currency1, bobCredit);
        vm.expectRevert(RebateHook.InvalidClaim.selector);
        hook.claim(poolA.toId(), currency1, 1);
        vm.stopPrank();
        hook.claim(poolA.toId(), currency1, aliceCredit);
        assertEq(hook.paid(poolA.toId(), currency1), bobCredit + aliceCredit);
    }

    function testExactOutputAndForgedUnlockRejected() public {
        fixture(true);
        vm.expectRevert(bytes("exact input only"));
        demoRouter.swap(poolA, SwapParams(true, 10_000, MIN_PRICE_LIMIT));
        vm.expectRevert(bytes("manager only"));
        demoRouter.unlockCallback(abi.encode(BOB, poolA, SwapParams(true, -10_000, MIN_PRICE_LIMIT)));
    }

    function testDirectCallbackAndZeroClaimsRejected() public {
        fixture(true);
        vm.expectRevert(RebateHook.OnlyManager.selector);
        hook.afterSwap(address(demoRouter), poolA, SwapParams(true, -10_000, MIN_PRICE_LIMIT),
            BalanceDelta.wrap(0), abi.encode(address(this)));
        vm.expectRevert(RebateHook.InvalidClaim.selector);
        hook.claim(poolA.toId(), currency1, 0);
    }
}
import {PoolSwapTest} from "v4-core/src/test/PoolSwapTest.sol";
