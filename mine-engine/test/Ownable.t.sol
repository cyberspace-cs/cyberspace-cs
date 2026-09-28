// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "../src/Ownable.sol";

/// @title Ownable 正常功能测试（happy-path 基线）
contract OwnableTest is Test {
    Ownable ownable;
    address deployer = address(this);
    address bob = makeAddr("bob");

    function setUp() external {
        ownable = new Ownable();
    }

    function test_Deployer_IsOwner() external view {
        assertEq(ownable.owner(), deployer);
    }

    function test_Owner_CanTransferOwnership() external {
        ownable.transferOwnership(bob);
        assertEq(ownable.owner(), bob);
    }

    function test_Owner_CanSetStopped() external {
        ownable.setStopped(true);
        assertTrue(ownable.stopped());
    }

    function test_TransferToZero_Reverts() external {
        vm.expectRevert(bytes("zero owner"));
        ownable.transferOwnership(address(0));
    }

    function test_NonOwner_CannotTransfer() external {
        vm.prank(bob);
        vm.expectRevert(bytes("not owner"));
        ownable.transferOwnership(makeAddr("carol"));
    }
}
