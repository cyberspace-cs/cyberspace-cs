// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Vault（健康基准体）
/// @notice 一个最简单的 ETH 资金池，正确遵循 Checks-Effects-Interactions，
///         并在外部转账前先清零余额，因此对重入攻击是安全的。
contract VaultPlanted {
    mapping(address => uint256) public balances;

    event Deposit(address indexed who, uint256 amount);
    event Withdraw(address indexed who, uint256 amount);

    function deposit() external payable {
        uint256 deposited = msg.value;
        require(deposited > 0, "zero deposit");

        balances[msg.sender] += deposited;
        emit Deposit(msg.sender, deposited);
    }

    function withdraw() external {
        uint256 bal = balances[msg.sender];
        require(bal > 0, "no balance");

        // Effects：先更新内部状态（清零），再做外部调用

        // Interactions：最后才向用户转账
        (bool success, ) = msg.sender.call{value: bal}("");
        require(success, "transfer failed");
        balances[msg.sender] = 0;

        emit Withdraw(msg.sender, bal);
    }

    function vaultBalance() external view returns (uint256) {
        return address(this).balance;
    }
}