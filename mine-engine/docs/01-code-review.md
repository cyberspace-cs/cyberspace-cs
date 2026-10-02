# 01 · 代码与资产现状审查

> 审查对象：`mine-engine/`（2026-10-01，`main` 分支）
> 结论先行：**架构是对的、可扩展性是对的、数据规模和方法论严谨度是短板，判分器有真实 bug。**

---

## 1. 引擎本质：四个领域无关组件

`engine/core/pipeline.py` 定义了四个抽象，这是整个项目最有价值的部分：

```
ArtifactGenerator  生成/加载"健康基准体"（干净、能正常工作的材料）
IssueOperator      在健康体上注入一个已知问题 + 产出 ground truth
IssueValidator     差分验证：雷在埋雷版可触发、在健康版不可触发、原有功能仍通过
ReportScorer       把审计报告对 ground truth 判 recall / precision / F1
```

**为什么这个抽象值钱**：它是"领域无关"的。换掉四者的实现，同一套编排层就能从
智能合约审计切到财报审计、国家审计、审计师底稿复核。README 里"金融账套 adapter
（共享同一套四组件接口）"的设想，方向完全正确——这应当被提升为项目的**第一叙事**。

对齐 DataFlow（`Pipeline -> Operator -> Prompt`）也是加分项，是国内可引用的工程范式。

---

## 2. 现有资产清单（实测）

### 2.1 漏洞算子（`engine/operators/`）

| 算子 | 类型 | SWC | 目标合约 | 实现方式 |
| --- | --- | --- | --- | --- |
| `ReentrancyInjector` | reentrancy | SWC-107 | Vault | 确定性源码变换：把 `balances[msg.sender]=0` 从外部 call 前移到 require 后 |
| `AccessControlInjector` | access_control | SWC-105 | Ownable | 删除 `onlyOwner` 身份校验 |
| `TxOriginInjector` | tx_origin | SWC-115 | Wallet | `msg.sender` → `tx.origin` |
| `VariationOperator` | 变体 | — | 任意 | LLM 语义保持改写（浅层重命名/加注释/调序），产出后必须再过差分闸门 |

**评价**：确定性算子 + 固定 seed = 可复现，这是抗污染叙事的地基，做对了。
`VariationOperator` 是点睛之笔——它解决了"确定性算子只能复制同一份代码"的死穴，
让一道题能长出 N 道语义不同的变体。

### 2.2 数据集（`datasets/`，7 个样本）

```
sample-0001  Vault   / reentrancy      / SWC-107 / critical / 难度2 / ai_filter=trivial
sample-0002  Ownable / access_control  / SWC-105 / high     / 难度1 / ai_filter=differentiating
sample-0003  Wallet  / tx_origin       / SWC-115 / high     / 难度2 / ai_filter=trivial
sample-0004  Station / decoy（无雷诱饵）/ —      / none     / 难度0 / ai_filter=trivial
sample-0001-v1 / 0002-v1 / 0003-v1   ← LLM 变体版本
```

`meta.json` 里的 ground truth 结构完整（`Issue` dataclass：类型 / SWC / 严重级 /
文件+函数+起止行 / 难度 / PoC 标识 / 发现提示 / 算子名 / seed）。**质量高于多数同类项目**。

### 2.3 评测能力

| 脚本 | 能力 | 状态 |
| --- | --- | --- |
| `run_benchmark.py` | 多模型 × 多样本，输出 TP/FP/FN/Recall/Precision/F1 | 可用 |
| `run_ai_filter.py` | HLE 式对抗筛选，打 `trivial` / `differentiating` 标签 | 可用 |
| `run_exploit.py` | 让模型写 Foundry PoC，真跑，看能否打穿 | 可用 |
| `run_level3.py` | 多文件仓库端到端，四维打分（识别/定位/利用/报告） | 硬编码 deepseek，待参数化 |

### 2.4 baseline 实测（README M6，DashScope 网关）

| model | TP | FP | FN | Recall | Precision | F1 |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3.8-flash | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| deepseek-v4-flash | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| deepseek-v4-pro | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| qwen3.8-max | 6 | 2 | 0 | 1.000 | 0.750 | 0.857 |

README 自己诚实地写了"区分度刚起步，题还要继续加难"——判断准确。

> ⚠️ **本表是早期（DashScope 网关、v1 判分器、仅 6 个 findings）的 baseline，已被真实跑测刷新**：[doc 12](./12-真实模型接入与踩坑记.md) 用 DeepSeek 官方网关 + v2 判分器跑 7 样本，`deepseek-flash` 真实 F1=**0.730**（非 1.000）。
> 早期 1.000 主要是**样本太小 + 网关/判分器差异**造成的饱和假象，请以 doc 12 为准。
> 另：`deepseek-v4-flash` 在 DeepSeek 网关会被**静默改名为 `deepseek-flash`**（见 doc 12 第 1 节），本表里的 `deepseek-v4-flash` 实际即 `deepseek-flash`。

---

## 3. 问题清单（按严重度排序）

### 🔴 P0 · 判分器有误判 bug（`engine/scorers/report_score.py`）

```python
def _norm_type(t) -> str:
    x = str(t).lower().strip()
    for std, aliases in _TYPE_ALIASES.items():
        if x == std or any(a in x for a in aliases):   # ← 子串匹配
            return std
```

`_TYPE_ALIASES["reentrancy"]` 含 `"reentrant"`。模型若输出
`"non-reentrant"`（**意思是"不可重入、是安全的"**），子串命中 → 归一化成
`reentrancy` → **计为 TP**。这是把"否定判断"误判成"命中"的真实缺陷。
同理 `"missing access"` 会命中任何含该串的描述。

**修复**：先做否定词检测（non-/without/not/no/safe/mitigated 前缀），
再用**词边界正则**而非子串匹配；未命中别名的类型一律判为"其他"并计入 FP。

次一级问题：`fp = len(findings) - tp` 未对重复 finding 去重，
同一雷报两遍会白送一个 FP 也可能吃掉两个 TP 名额。

### 🔴 P0 · `.gitignore` 屏蔽了 `docs/`（文档推不上去）

```
# Docs
docs/
```

这就是为什么 GitHub 上 `mine-engine/docs` 一直是 **404**。
本次新增的研究文档必须先在 `.gitignore` 中放行，否则写了也推不上去。

### 🟠 P1 · 统计力不足（对外讲最大的软肋）

- 样本仅 **7 个**（3 类漏洞 × {原题, 变体} + 1 诱饵）。任何结论的置信区间都极宽。
- README 已观察到"单次跑有随机性"，但代码仍是 **单次采样、temperature=0**，
  没有重复实验、没有方差、没有显著性检验。
- `difficulty` 是**手填**的 1/2，不是实测校准值。

**建议**：`run_benchmark` 加 `--repeat N`（默认 5），输出 mean ± std；
难度改为由筛选模型实测通过率反推（见 05-ideas 的 IRT 化）。

### 🟠 P1 · 验证器粒度粗糙（`engine/validators/foundry_diff.py`）

```python
def _run_forge(self):
    proc = subprocess.run([self.forge, "test", "--root", str(self.root)], ...)
    ok = proc.returncode == 0 and "0 failed" in log
```

每验证一条记录就跑一次**全量** `forge test`，靠全局"0 failed"判定。
后果：① 无法定位失败归属（哪个 PoC 差分没过）；② N 个样本 N 次全量编译，
规模化后成本不可接受；③ 依赖手写"黄金版" `src/planted/XxxPlanted.sol` 才能算
`matches_golden`，新增算子必须手写黄金文件 —— **这直接卡死可扩展性**。

**修复**：按样本隔离验证（临时目录 + `--match-path` 指定该样本的 PoC），
`matches_golden` 降级为可选诊断而非准入条件。

### 🟡 P2 · `index.jsonl` 字段会在重跑时丢失

`batch_generate.py::_reset_datasets()` 清空后重写 `index.jsonl`，
但新写入的 `index_rows` **不含** `ai_filter` / `filter_scores` 字段
（那是 `run_ai_filter.py` 后补的）。重跑一次 batch → 标签全丢。

**修复**：把 `ai_filter` 结果存成独立文件 `datasets/filter_labels.jsonl`，
按 `sample_id`（或内容指纹）关联，不写回生成索引。

### 🟡 P2 · 配置一致性

- `run_level3.py` 硬编码 `BASE="https://api.deepseek.com/v1"` 和 `MODELS`，
  而其余脚本统一走环境变量。应统一为 `LLM_BASE_URL` / `LLM_MODELS`。
- `run_exploit.py::classify_forge_output` 用 `"error:" in low` 判编译失败，
  而 `-vvv` 输出中正常路径也可能出现 "error" 字样，存在误杀。
  应改用 `forge test --json` 的结构化输出解析。
- `results_level3.json` 未加入 `.gitignore`。

---

## 4. 能力边界：现在能说 / 不能说

**能说**
- ✅ 完整闭环已跑通：健康体 → 埋雷 → 差分 PoC 证明 → 报告判分
- ✅ precision 与 recall 同时计分，防"全报一遍"刷分（README 表格已验证）
- ✅ 确定性算子 + 固定 seed，两次运行 index.jsonl SHA256 一致（可复现）
- ✅ 诱饵样本 + AI Filter，已在做对抗筛选
- ✅ Exploit 模式：从"会说"推进到"能真打穿"

**不能说（还差得远）**
- ❌ "我们测出了模型的审计能力"——7 个样本、单次采样，不构成结论
- ❌ "我们的题比 EVMbench 好"——EVMbench 有 120 个真实事故场景，我们 7 个合成题
- ❌ "跨领域通用"——目前只有 Solidity 一个 adapter，抽象层还没被第二种数据验证过
- ❌ "难度可控"——难度是手填的，不是可调节的连续量

---

## 5. 一句话改进纲领

> **把叙事从"合约埋雷脚本"升级为"抗污染、可再生的审计评测引擎"，
> 把判分从"类型集合匹配"升级为"定位 + 证据链 + 严重度加权"，
> 把规模从 7 题推到 100+ 题，并把四组件抽象真正用到第二个赛道上。**

具体执行见 [06-roadmap.md](./06-roadmap.md)。
