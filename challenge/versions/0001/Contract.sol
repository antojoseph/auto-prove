// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;
contract MilestoneEscrow {
    mapping(address => uint256) public deposited;
    mapping(address => uint256) public released;
    function deposit() external payable { deposited[msg.sender] += msg.value; }
    function release(address payer, uint256 amount) external {
        require(amount <= deposited[payer]);
        released[payer] += amount;
        (bool ok,) = msg.sender.call{value: amount}(""); require(ok);
    }
}
