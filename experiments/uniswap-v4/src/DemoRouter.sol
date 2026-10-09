// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {IPoolManager} from "v4-core/src/interfaces/IPoolManager.sol";
import {IUnlockCallback} from "v4-core/src/interfaces/callback/IUnlockCallback.sol";
import {PoolKey} from "v4-core/src/types/PoolKey.sol";
import {SwapParams} from "v4-core/src/types/PoolOperation.sol";
import {BalanceDelta} from "v4-core/src/types/BalanceDelta.sol";
import {Currency} from "v4-core/src/types/Currency.sol";
import {CurrencySettler} from "v4-core/test/utils/CurrencySettler.sol";

/// @notice Test-only router. No slippage protection; never use with real funds.
contract DemoRouter is IUnlockCallback {
    using CurrencySettler for Currency;
    IPoolManager public immutable manager;
    constructor(IPoolManager manager_) { manager = manager_; }

    function swap(PoolKey calldata key, SwapParams calldata params) external returns (BalanceDelta) {
        require(Currency.unwrap(key.currency0) != address(0), "ERC20 only");
        require(params.amountSpecified < 0, "exact input only");
        return abi.decode(manager.unlock(abi.encode(msg.sender, key, params)), (BalanceDelta));
    }

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        require(msg.sender == address(manager), "manager only");
        (address payer, PoolKey memory key, SwapParams memory params) = abi.decode(data, (address, PoolKey, SwapParams));
        BalanceDelta delta = manager.swap(key, params, abi.encode(payer));
        _settle(key.currency0, payer, delta.amount0());
        _settle(key.currency1, payer, delta.amount1());
        return abi.encode(delta);
    }

    function _settle(Currency currency, address payer, int128 delta) private {
        if (delta < 0) currency.settle(manager, payer, uint256(-int256(delta)), false);
        if (delta > 0) manager.take(currency, payer, uint256(uint128(delta)));
    }
}
