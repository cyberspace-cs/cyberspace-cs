// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Ownable（健康基准体）
/// @notice 最简单的访问控制：onlyOwner modifier 在执行函数体前校验调用者是 owner。
contract Ownable {
    address public owner;
    bool public stopped;

    event OwnershipTransferred(address indexed previous, address indexed current);

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
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
