// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title OwnablePlanted（埋雷版 / 访问控制缺失 SWC-105）
/// @notice 与健康 Ownable 唯一区别：onlyOwner modifier 中的身份校验被删掉，
///         modifier 只剩 `_;`，于是所有“仅 owner”函数任何人都能调用。
/// @dev 本文件是 access control 埋雷算子（engine/operators/access_control.py）的黄金输出。
contract OwnablePlanted {
    address public owner;
    bool public stopped;

    event OwnershipTransferred(address indexed previous, address indexed current);

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    modifier onlyOwner() {
        // [PLANTED BUG] 身份校验 require(msg.sender == owner) 被删除
        _;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero owner");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setStopped(bool s) external onlyOwner {
        stopped = s;
    }
}
