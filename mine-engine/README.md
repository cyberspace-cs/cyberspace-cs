# mine-engine · 动态对抗审计考试的埋雷引擎（M0 + M1）

把「动态对抗考试 / Adaptive Verifier」落到**智能合约审计**垂直场景的最小可用引擎：
自动在**健康合约**上做一次最小化、可复现的程序变换（埋雷），用**差分 PoC**
证明雷确实是这次埋进去的，再把审计 Agent 的报告对 ground truth 判分。

范式对齐 **OpenDCAI/DataFlow**（https://github.com/OpenDCAI/DataFlow）：
`Pipeline -> Operator -> (Prompt)`，算子处理结构化记录、可串联、可替换后端。

## 闭环

```
健康 Vault ──埋雷算子──▶ VaultPlanted + ground truth
                              │
                  差分 PoC（forge test）
   健康版：攻击失败 / 埋雷版：攻击成功 / happy-path 全过
                              │
                  审计报告 ──▶ recall / precision / F1
```

## 目录结构

```
mine-engine/
├─ src/
│  ├─ Vault.sol                 # 健康基准体（正确 CEI，抗重入）
│  ├─ Attacker.sol              # 重入攻击合约（PoC 工具）
│  └─ planted/VaultPlanted.sol  # 埋雷版（算子的“黄金输出”）
├─ test/
│  ├─ Vault.t.sol               # 正常功能测试（4 项）
│  └─ VaultReentrancyPoC.t.sol  # 重入差分 PoC（健康失败 / 埋雷成功）
├─ engine/                      # DataFlow 风格 Python（零第三方依赖）
│  ├─ core/                     # Pipeline/Operator 基类 + Issue schema
│  ├─ generators/               # ArtifactGenerator：加载健康合约
│  ├─ operators/                # IssueOperator：重入埋雷（确定性源码变换）
│  ├─ validators/               # IssueValidator：forge 差分验证
│  └─ scorers/                  # ReportScorer：报告判分
├─ datasets/                    # 生成样本落盘（clean/planted/meta.json）
└─ run_demo.py                  # 一键演示完整闭环
```

## 运行

需要 [Foundry](https://book.getfoundry.sh/)（forge）。一键演示：

```shell
py run_demo.py
```

单独跑合约测试：

```shell
forge test
```

## M1 实测结果

- 算子生成的埋雷版与黄金版**归一化等价**（忽略注释/空白）；
- `forge test` **6/6 通过**：4 项 happy-path、健康版攻击失败、埋雷版攻击成功（资金被掏空）；
- 报告判分（ground truth = reentrancy）：

  | 报告策略 | recall | precision | F1 |
  |---|---|---|---|
  | 把所有类型全报一遍（作弊） | 1.0 | 0.083 | 0.154 |
  | 只报确实发现的重入（好审计） | 1.0 | 1.0 | 1.0 |
  | 什么都没发现（漏报） | 0.0 | 1.0 | 0.0 |

  precision 与 recall 同时计分，误报被惩罚，防止「全报一遍」刷分。

## 下一步（M2+）

- 扩充算子库：整数溢出、tx.origin、未检查 call、delegatecall、访问控制缺失等；
- 算子注册中心 + 难度/置信度元数据，支持多雷组合与「干扰雷」；
- 真实被测审计 Agent 接入（替换 run_demo 里的模拟报告）；
- 位置/证据级匹配，替代当前的类型集合匹配；
- 第二个领域 adapter：金融账套（共享同一套四组件接口）。
