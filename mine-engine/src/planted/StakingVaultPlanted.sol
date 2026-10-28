// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Ownable} from "../Ownable.sol";

/// @title StakingVaultPlanted（Level 3 难题版）
/// @notice 真雷 2 个：
///   ① borrow：先 call 再设余额为 0（重入，教科书）
///   ② interestOf：利息计算除以 100 而不是 10000（业务逻辑错误，interestRate=500 即 5%，
///      但代码算成 500/100=5 即 500%）——单看每行都"合理"，数字错了
///   ③ setInterestRate：缺 onlyOwner（权限雷）
/// 诱饵 3 个：
///   A sweep：low-level call 但有 require（安全）
///   B emergencyWithdraw：用 call 但有 returns check（安全）
///   C pause：只有 owner 能调但已经被 owner 调过一次（看起来危险实际安全）
contract StakingVaultPlanted is Ownable {
    mapping(address => uint256) public deposits;
    mapping(address => uint256) public lastInterest;
    uint256 public interestRate; // basis points: 500 = 5%
    bool public paused;

    event Deposit(address indexed user, uint256 amount);
    event Withdraw(address indexed user, uint256 amount);
    event InterestPaid(address indexed user, uint256 amount);
    event Paused(bool);

    function deposit() external payable {
        require(!paused, "paused");
        deposits[msg.sender] += msg.value;
        emit Deposit(msg.sender, msg.value);
    }

    // 真雷①：先 call 再设余额 0（重入）
    function withdraw() external {
        uint256 amount = deposits[msg.sender];
        require(amount > 0, "no deposit");
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        deposits[msg.sender] = 0;
        emit Withdraw(msg.sender, amount);
    }

    // 真雷②：利息计算除以 100 而不是 10000（业务逻辑错误）
    function interestOf(address user) public view returns (uint256) {
        return deposits[user] * interestRate / 100; // BUG: 应该是 /10000
    }

    function claimInterest() external {
        uint256 amount = interestOf(msg.sender);
        require(amount > 0, "no interest");
        lastInterest[msg.sender] = block.timestamp;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
        emit InterestPaid(msg.sender, amount);
    }

    // 真雷③：缺 onlyOwner
    function setInterestRate(uint256 rate) external {
        interestRate = rate;
    }

    // 诱饵 A：low-level call 但有 require
    function sweep(address payable to) external {
        require(msg.sender == owner, "not owner");
        (bool ok, ) = to.call{value: address(this).balance}("");
        require(ok, "sweep failed");
    }

    // 诱饵 B：call 但检查了返回数据
    function emergencyWithdraw(address to, uint256 amount) external {
        require(msg.sender == owner, "not owner");
        (bool ok, bytes memory ret) = to.call{value: amount}("");
        require(ok, "emergency failed");
        require(ret.length == 0, "unexpected returndata");
    }

    // 诱饵 C：pause 函数，任何人都能调，但 paused 已经是 true，再调无效果
    function togglePause() external {
        paused = !paused;
        emit Paused(paused);
    }

    function poolBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
