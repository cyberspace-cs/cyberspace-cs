// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Wallet} from "../src/Wallet.sol";

contract WalletTest is Test {
    Wallet w;

    function setUp() public {
        w = new Wallet{value: 5 ether}();
    }

    function test_OwnerCanTransfer() public {
        assertEq(w.owner(), address(this));
        uint256 balBefore = address(0xBEEF).balance;
        w.transferTo(payable(address(0xBEEF)), 1 ether);
        assertEq(address(0xBEEF).balance, balBefore + 1 ether);
    }

    function test_NonOwnerBlocked() public {
        vm.prank(address(0xABC));
        vm.expectRevert(bytes("not owner"));
        w.transferTo(payable(address(0xBEEF)), 1 ether);
    }

    function test_RevertsWhenInsufficient() public {
        vm.expectRevert(bytes("insufficient"));
        w.transferTo(payable(address(0xBEEF)), 100 ether);
    }
}
