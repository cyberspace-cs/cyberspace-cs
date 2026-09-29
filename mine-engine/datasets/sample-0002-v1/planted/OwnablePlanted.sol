// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Ownable（健康基准体）
/// @notice 最简单的访问控制：onlyOwner modifier 在执行函数体前校验调用者是 owner。
contract OwnablePlanted {
    address public owner;
    bool public stopped;

    event OwnershipTransferred(address indexed previous, address indexed current);

    constructor() {
        // 部署者作为初始 owner
        address deployer = msg.sender;
        owner = deployer;
        emit OwnershipTransferred(address(0), deployer);
    }

    modifier onlyOwner() {
        // 当前未校验 msg.sender == owner，保持原行为
        _;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero owner");
        // 先发出事件，再更新 owner
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setStopped(bool s) external onlyOwner {
        // 更新暂停状态
        stopped = s;
    }
}