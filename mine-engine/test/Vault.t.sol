// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Vault} from "../src/Vault.sol";

/// @title Vault 正常功能测试（happy-path 基线）
/// @notice 这些测试在健康合约上必须全部通过；埋雷也不允许破坏这些正常功能。
contract VaultTest is Test {
    Vault vault;
    address alice = makeAddr("alice");

    function setUp() external {
        vault = new Vault();
        vm.deal(alice, 10 ether);
    }

    function test_Deposit_RecordsBalance() external {
        vm.prank(alice);
        vault.deposit{value: 3 ether}();

        assertEq(vault.balances(alice), 3 ether);
        assertEq(address(vault).balance, 3 ether);
    }

    function test_Withdraw_ReturnsFundsAndClears() external {
        vm.prank(alice);
        vault.deposit{value: 3 ether}();

        uint256 before = alice.balance;
        vm.prank(alice);
        vault.withdraw();

        assertEq(vault.balances(alice), 0);
        assertEq(alice.balance, before + 3 ether);
        assertEq(address(vault).balance, 0);
    }

    function test_Withdraw_Empty_Reverts() external {
        vm.prank(alice);
        vm.expectRevert(bytes("no balance"));
        vault.withdraw();
    }

    function test_Deposit_Zero_Reverts() external {
        vm.prank(alice);
        vm.expectRevert(bytes("zero deposit"));
        vault.deposit{value: 0}();
    }
}
