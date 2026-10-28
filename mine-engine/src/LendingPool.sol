// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "./Ownable.sol";

/// @title LendingPool（健康基准体，多文件）
/// @notice 健康版：withdraw 先把余额设为 0 再转账（CEI 模式，防重入）；
///         setInterestRate 有 onlyOwner；sweep 有 require 检查。
contract LendingPool is Ownable {
    mapping(address => uint256) public deposits;
    uint256 public interestRate;

    event Deposit(address indexed user, uint256 amount);
    event Withdraw(address indexed user, uint256 amount);
    event InterestRateSet(uint256 rate);

    function deposit() external payable {
        deposits[msg.sender] += msg.value;
        emit Deposit(msg.sender, msg.value);
    }

    function withdraw() external {
        uint256 amount = deposits[msg.sender];
        require(amount > 0, "no deposit");
        // Checks-Effects-Interactions: 先把余额设为 0，再转账
        deposits[msg.sender] = 0;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        emit Withdraw(msg.sender, amount);
    }

    function setInterestRate(uint256 rate) external onlyOwner {
        interestRate = rate;
        emit InterestRateSet(rate);
    }

    /// @dev 诱饵：low-level call 看起来危险，但前面有 require，实际安全。
    function sweep(address payable to) external {
        require(msg.sender == owner, "not owner");
        (bool ok, ) = to.call{value: address(this).balance}("");
        require(ok, "sweep failed");
    }

    function poolBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
