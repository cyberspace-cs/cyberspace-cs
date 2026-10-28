// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title WalletPlanted（埋雷黄金版）：把 owner 授权从 msg.sender 改成 tx.origin（SWC-115）。
/// @notice 埋雷点：require(tx.origin == owner)，任何由 owner EOA 发起、
///         经过攻击者合约中转的调用都会被放行。
contract WalletPlanted {
    address public owner;
    event Paid(address indexed to, uint256 amount);

    constructor() payable {
        owner = msg.sender;
    }

    function transferTo(address payable to, uint256 amount) external {
        require(tx.origin == owner, "not owner");
        require(address(this).balance >= amount, "insufficient");
        to.transfer(amount);
        emit Paid(to, amount);
    }

    function walletBalance() external view returns (uint256) {
        return address(this).balance;
    }
}
