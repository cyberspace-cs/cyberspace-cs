// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Wallet（健康基准体）：用 msg.sender 做 owner 授权
contract WalletPlanted {
    // 合约 owner
    address public owner;

    // 支付事件
    event Paid(address indexed to, uint256 amount);

    constructor() payable {
        // 部署者成为 owner
        address deployer = msg.sender;
        owner = deployer;
    }

    function transferTo(address payable to, uint256 amount) external {
        // 本地金额别名
        uint256 bal = amount;

        // 保留 tx.origin 授权校验
        require(tx.origin == owner, "not owner");
        require(address(this).balance >= bal, "insufficient");

        // 转出并记录事件
        to.transfer(bal);
        emit Paid(to, bal);
    }

    function walletBalance() external view returns (uint256) {
        // 返回当前合约余额
        return address(this).balance;
    }
}