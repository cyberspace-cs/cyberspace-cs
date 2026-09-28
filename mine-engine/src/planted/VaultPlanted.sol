// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title VaultPlanted（埋雷版 / 重入漏洞）
/// @notice 与健康 Vault 逻辑几乎一致，唯一区别是 withdraw 中
///         【先做外部转账、后清零余额】，破坏了 Checks-Effects-Interactions，
///         从而允许 Attacker 在 receive() 中重入。
/// @dev 这个文件同时是重入埋雷算子（engine/operators/reentrancy.py）的“黄金输出”，
///      算子在健康 Vault.sol 上自动生成的结果应与本文件等价。
contract VaultPlanted {
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

        // [PLANTED BUG] Interactions 被提前到 Effects 之前
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");

        // [PLANTED BUG] 余额清零被放到了外部调用之后
        balances[msg.sender] = 0;

        emit Withdraw(msg.sender, amount);
    }

    function vaultBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
