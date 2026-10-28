// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Wallet（健康基准体）：用 msg.sender 做 owner 授权
contract Wallet {
    address public owner;
    event Paid(address indexed to, uint256 amount);

    constructor() payable {
        owner = msg.sender;
    }

    function transferTo(address payable to, uint256 amount) external {
        require(msg.sender == owner, "not owner");
        require(address(this).balance >= amount, "insufficient");
        to.transfer(amount);
        emit Paid(to, amount);
    }

    function walletBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
