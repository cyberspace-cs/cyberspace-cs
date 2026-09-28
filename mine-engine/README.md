# mine-engine · 动态对抗审计考试的埋雷引擎（M0–M3）

把「动态对抗考试 / Adaptive Verifier」落到**智能合约审计**垂直场景的最小可用引擎：
自动在**健康合约**上做一次最小化、可复现的程序变换（埋雷），用**差分 PoC**
证明雷确实是这次埋进去的，再把审计 Agent 的报告对 ground truth 判分。

范式对齐 **OpenDCAI/DataFlow**（https://github.com/OpenDCAI/DataFlow）：
`Pipeline -> Operator -> (Prompt)`，算子处理结构化记录、可串联、可替换后端。

## 闭环

```
健康合约 ──埋雷算子──▶ 埋雷版 + ground truth
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
│  ├─ Vault.sol                 # 健康：资金池（正确 CEI，抗重入）
│  ├─ Ownable.sol               # 健康：访问控制（onlyOwner）
│  ├─ Attacker.sol              # 重入攻击合约（PoC 工具）
│  └─ planted/
│     ├─ VaultPlanted.sol       # 埋雷：重入（SWC-107）黄金输出
│     └─ OwnablePlanted.sol     # 埋雷：访问控制缺失（SWC-105）黄金输出
├─ test/
│  ├─ Vault.t.sol               # Vault 正常功能（4 项）
│  ├─ Ownable.t.sol             # Ownable 正常功能（5 项）
│  ├─ VaultReentrancyPoC.t.sol  # 重入差分 PoC
│  └─ OwnableAccessControlPoC.t.sol  # 访问控制差分 PoC
├─ engine/                      # DataFlow 风格 Python（零第三方依赖）
│  ├─ core/                     # Pipeline/Operator 基类 + Issue schema
│  ├─ generators/               # ArtifactGenerator：加载健康合约
│  ├─ operators/
│  │  ├─ registry.py            # 算子注册中心（核心 IP：按类型动态取用）
│  │  ├─ reentrancy.py          # 重入埋雷（确定性源码变换）
│  │  └─ access_control.py      # 访问控制埋雷（删除身份校验）
│  ├─ validators/               # IssueValidator：forge 差分验证（领域无关）
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

## M2 实测结果

- **2 个健康合约**（Vault / Ownable）、**2 个埋雷算子**（重入 SWC-107 / 访问控制 SWC-105），
  经**算子注册中心**按类型动态编排；
- 算子生成的埋雷版与黄金版**归一化等价**（忽略注释/空白）；
- `forge test` **13/13 通过**：9 项 happy-path、4 项差分 PoC
  （健康版攻击失败 / 埋雷版攻击成功）；
- 报告判分（ground truth = reentrancy）：

  | 报告策略 | recall | precision | F1 |
  |---|---|---|---|
  | 把所有类型全报一遍（作弊） | 1.0 | 0.083 | 0.154 |
  | 只报确实发现的重入（好审计） | 1.0 | 1.0 | 1.0 |
  | 什么都没发现（漏报） | 0.0 | 1.0 | 0.0 |

  precision 与 recall 同时计分，误报被惩罚，防止「全报一遍」刷分。

## M3 批量生成

```shell
py batch_generate.py
```

- 遍历 `(健康合约 × 埋雷算子)` 组合，逐条做 Foundry 差分验证；
  通过则落盘 `datasets/sample-XXXX/`，失败自动丢弃并记录；
- 产出 `datasets/index.jsonl`（每行一个样本，含 contract/vuln/swc/severity/难度/路径/validated）；
- 当前 2 组合 **差分通过 2/2（有效率 100%）**；
- 固定 seed，两次运行 `index.jsonl` 的 SHA256 完全一致（**可复现**）；
- 新增算子只需在 `registry` 注册并在 `batch_generate.py` 的 `COMBOS` 加一行，即可线性扩充。

## 下一步（M6+）

- **M6 真实审计 Agent harness + 自动判分**：接 OpenAI 兼容 LLM、给工具
  （读文件/grep/forge test），标准化报告，跑 ≥2 模型 baseline + 全报对照；
- 扩算子：unchecked call（SWC-104）、tx.origin（SWC-115）、delegatecall（SWC-112）等；
- 位置/证据级匹配，替代当前的类型集合匹配；
- 埋雷–审计共演化；金融账套 adapter（共享同一套四组件接口）。
