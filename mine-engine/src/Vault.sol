// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Vault（健康基准体）
/// @notice 一个最简单的 ETH 资金池，正确遵循 Checks-Effects-Interactions，
///         并在外部转账前先清零余额，因此对重入攻击是安全的。
contract Vault {
    mapping(address => uint256) public balances;

    event Deposit(address indexed who, uint256 amount);
    event Withdraw(address indexed who, uint256 amount);

    function deposit() external payable {
        require(msg.value > 0, "zero deposit");
        balances[msg.sender] += msg.value;
        emit Deposit(msg.sender, msg.value);
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "no balance");

        // Effects：先更新内部状态（清零），再做外部调用
        balances[msg.sender] = 0;

        // Interactions：最后才向用户转账
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        emit Withdraw(msg.sender, amount);
    }

    function vaultBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
