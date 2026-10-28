// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "../Ownable.sol";

/// @title LendingPoolPlanted（埋雷版，组合雷）
/// @notice 两个雷：
///   ① withdraw：先 call 转账再把余额设为 0（重入，DAO 经典模式）
///   ② setInterestRate：删掉 onlyOwner，任何人都能改利率
/// sweep 保持 require（诱饵，实际安全）。
contract LendingPoolPlanted is Ownable {
    mapping(address => uint256) public deposits;
    uint256 public interestRate;

    event Deposit(address indexed user, uint256 amount);
    event Withdraw(address indexed user, uint256 amount);
    event InterestRateSet(uint256 rate);

    function deposit() external payable {
        deposits[msg.sender] += msg.value;
        emit Deposit(msg.sender, msg.value);
    }

    // 埋雷①：先 call 再设余额为 0（重入）
    function withdraw() external {
        uint256 amount = deposits[msg.sender];
        require(amount > 0, "no deposit");
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        deposits[msg.sender] = 0;
        emit Withdraw(msg.sender, amount);
    }

    // 埋雷②：删掉 onlyOwner，任何人都能改利率
    function setInterestRate(uint256 rate) external {
        interestRate = rate;
        emit InterestRateSet(rate);
    }

    /// @dev 诱饵：low-level call 但有 require，实际安全。
    function sweep(address payable to) external {
        require(msg.sender == owner, "not owner");
        (bool ok, ) = to.call{value: address(this).balance}("");
        require(ok, "sweep failed");
    }

    function poolBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
