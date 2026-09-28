// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "../src/Ownable.sol";
import {OwnablePlanted} from "../src/planted/OwnablePlanted.sol";

/// @title 访问控制差分 PoC
/// @notice 同一个“非 owner 试图接管”的动作，两版结果必须相反：
///   - 健康 Ownable：非 owner 调用被 onlyOwner 拒绝（revert），owner 不变；
///   - 埋雷 OwnablePlanted：校验被删，非 owner 成功接管。
contract OwnableAccessControlPoCTest is Test {
    address attacker = makeAddr("attacker");
    address rogueTarget = makeAddr("rogue-target");

    function test_AccessControl_Clean_NonOwnerReverts() external {
        Ownable target = new Ownable();
        address originalOwner = target.owner();

        vm.prank(attacker);
        vm.expectRevert(bytes("not owner"));
        target.transferOwnership(rogueTarget);

        // owner 未被篡改
        assertEq(target.owner(), originalOwner);
    }

    function test_AccessControl_Planted_NonOwnerSucceeds() external {
        OwnablePlanted target = new OwnablePlanted();

        vm.prank(attacker);
        target.transferOwnership(rogueTarget);

        // 非 owner 成功把 owner 改成指定地址
        assertEq(target.owner(), rogueTarget);
    }
}
