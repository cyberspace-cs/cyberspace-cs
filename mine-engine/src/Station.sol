// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Station（诱饵基准体）：故意用 low-level call，但返回值被正确 require 检查。
/// @notice 这是一个**健康**合约，没有任何漏洞。它出现 low-level call 是为了考验模型：
///         若一见 call 就报 "unchecked call"，会在这里产生误报（precision 下降）。
contract Station {
    mapping(address => uint256) public credit;
    event Claimed(address indexed to, uint256 amount);

    function fund() external payable {
        credit[msg.sender] += msg.value;
    }

    function claim(address payable to, uint256 amount) external {
        require(credit[msg.sender] >= amount, "insufficient");
        credit[msg.sender] -= amount;
        (bool ok, ) = to.call{value: amount}("");
        require(ok, "claim failed");
        emit Claimed(to, amount);
    }
}
