// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Vault} from "../src/Vault.sol";
import {VaultPlanted} from "../src/planted/VaultPlanted.sol";
import {Attacker} from "../src/Attacker.sol";

interface IVault {
    function deposit() external payable;
    function withdraw() external;
}

/// @title 重入差分 PoC
/// @notice 同一个攻击，在两个版本上必须给出相反结果，才能证明“雷确实是这次埋进去的”：
///   - 健康 Vault：攻击回滚、他人资金分文不少；
///   - 埋雷 VaultPlanted：攻击成功、资金被掏空。
contract VaultReentrancyPoCTest is Test {
    address alice = makeAddr("alice");

    /// 先让一个无辜用户 alice 往目标里存 5 ETH，作为被觊觎的资金
    function _seedVictimFunds(address target) internal {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        IVault(target).deposit{value: 5 ether}();
    }

    function test_Reentrancy_Clean_AttackFails() external {
        Vault vault = new Vault();
        _seedVictimFunds(address(vault));

        Attacker attacker = new Attacker(address(vault));
        vm.deal(address(this), 1 ether);

        // 重入时第二次取款回滚，使第一次的外部 call 返回 false，
        // 健康 Vault 的 require(ok, "transfer failed") 兜底，整个攻击交易 revert
        vm.expectRevert(bytes("transfer failed"));
        attacker.attack{value: 1 ether}();

        // 攻击回滚后，alice 的 5 ETH 原封不动
        assertEq(address(vault).balance, 5 ether, "clean vault must keep victim funds");
        assertEq(vault.balances(alice), 5 ether);
    }

    function test_Reentrancy_Planted_AttackSucceeds() external {
        VaultPlanted vault = new VaultPlanted();
        _seedVictimFunds(address(vault));

        Attacker attacker = new Attacker(address(vault));
        vm.deal(address(this), 1 ether);
        attacker.attack{value: 1 ether}();

        // 埋雷版被掏空：vault 余额为 0
        assertEq(address(vault).balance, 0, "planted vault must be drained");
        // attacker 拿走全部 6 ETH（自己本金 1 + alice 的 5）
        assertEq(address(attacker).balance, 6 ether, "attacker drains all funds");
    }
}
