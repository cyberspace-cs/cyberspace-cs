# AuLE 代码实现方案 v0.1
## 借鉴 DataFlow 架构重构 mine-engine

> DataFlow（北大 OpenDCAI）核心抽象：Operator / Storage / LLMServing / PromptABC / PipelineABC。
> 我们轻量借鉴，不引入 pandas 重依赖，用 JSONL 当 Storage。

---

## 1. DataFlow 借鉴点

| DataFlow 概念 | 它怎么做 | 我们怎么借鉴 |
|---|---|---|
| OperatorABC | `__init__` + `run(storage, input_*_key, output_*_key)` + `get_desc()` | 统一算子基类，所有埋雷/评分/过滤算子继承 |
| FileStorage | pandas DataFrame，每步缓存 jsonl，支持 resume_step | 用 list[dict] + JSONL 文件缓存，每步落盘 |
| LLMServing | 算子不自己 new LLM，构造函数注入 | LLMClient 注入到需要 LLM 的算子 |
| PromptABC | Prompt 独立成类，`@PROMPT_REGISTRY.register()` | Prompt 模板类化，注册到全局 REGISTRY |
| prompt_restrict | 算子声明允许哪些 Prompt | 暂不做类型检查，简单映射即可 |
| PipelineABC | `__init__` 定义算子，`forward()` 串联 | 每个评测流程一个 Pipeline 类 |
| compile() + resume_step | DAG 预编译，从断点恢复 | 每步检查缓存文件存在就跳过 |
| draw_graph() | 可视化 DAG | 暂不做 |

---

## 2. 目标目录结构

```
mine-engine/
├── engine/
│   ├── core/
│   │   ├── operator.py       # OperatorABC 基类
│   │   ├── pipeline.py       # PipelineABC 基类
│   │   ├── storage.py        # JSONLStorage：读写 + 缓存 + resume
│   │   ├── serving.py        # LLMServing 抽象（包 LLMClient）
│   │   ├── prompt.py         # PromptABC + PROMPT_REGISTRY
│   │   └── registry.py       # OPERATOR_REGISTRY
│   ├── operators/
│   │   ├── reentrancy.py     # 继承 OperatorABC
│   │   ├── access_control.py
│   │   ├── tx_origin.py
│   │   ├── variation.py     # LLM 变体改写
│   │   └── business_logic.py # 新：业务逻辑雷（利息计算错误）
│   ├── prompts/
│   │   ├── audit_prompts.py  # AuditPrompt / ConservativePrompt / AggressivePrompt
│   │   └── exploit_prompts.py # PoC 生成 prompt
│   ├── agents/
│   │   ├── audit_agent.py
│   │   ├── exploit_agent.py
│   │   └── level3_agent.py
│   ├── scorers/
│   │   ├── report_score.py
│   │   └── level3_score.py
│   └── validators/
│       ├── foundry_diff.py
│       └── dedup.py
├── pipelines/
│   ├── level1_detect.py      # Level 1：生成→Diff→AI Filter→Detect 评分
│   ├── level2_exploit.py     # Level 2：生成→PoC 生成→Foundry 验证→评分
│   └── level3_audit.py       # Level 3：多文件仓库→端到端审计→四维评分
├── src/                      # Solidity 合约
├── test/                     # Foundry PoC
├── run_level1.py
├── run_level2.py
├── run_level3.py
└── datasets/                 # 生成的 JSONL 数据集
```

---

## 3. 核心接口设计

### 3.1 OperatorABC

```python
class OperatorABC:
    name = "base"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, storage, **keys):
        """storage: JSONLStorage; keys: input_*_key / output_*_key"""
        raise NotImplementedError

    def get_desc(self, lang="zh"):
        return self.name
```

### 3.2 JSONLStorage

```python
class JSONLStorage:
    def __init__(self, path, cache_dir="./cache"):
        self.records = []
        self.path = path
        self.cache_dir = cache_dir

    def step(self):
        """返回自己的一个引用，算子间共享同一份 records"""
        return self

    def write(self, step_name, records):
        """每步落盘缓存，支持 resume"""
        p = Path(self.cache_dir) / f"{step_name}.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
```

### 3.3 PipelineABC

```python
class PipelineABC:
    def __init__(self):
        self.operators = []

    def add(self, op):
        self.operators.append(op)
        return op

    def forward(self, storage, resume_step=0):
        for i, op in enumerate(self.operators):
            if i < resume_step:
                continue
            op.run(storage)
```

---

## 4. 三个 Pipeline

### Level 1 Detect Pipeline
```
健康合约 → ReentrancyInjector → AccessControlInjector → TxOriginInjector
→ VariationOperator(LLM改写) → FoundryDiff → DedupFilter
→ AIFilter(便宜模型做题) → AuditAgent(4模型) → ReportScorer
```

### Level 2 Exploit Pipeline
```
Level 1 数据集 → ExploitAgent(4模型写PoC) → FoundryCompile+Run
→ exploit_success/fail/compile_fail/no_code → 打穿率统计
```

### Level 3 Audit Pipeline
```
StakingVaultPlanted + Ownable → Level3AuditAgent(4模型)
→ Level3Scorer(四维打分) → 总分排名
```

---

## 5. 实施顺序

1. **core 层**（operator/storage/serving/prompt/registry）—— 1 天
2. **迁移现有算子**到 OperatorABC —— 0.5 天
3. **写三个 Pipeline 类**替换手写脚本 —— 1 天
4. **加业务逻辑算子**（business_logic.py：利息计算错误）—— 0.5 天
5. **跑 baseline 验证** —— 0.5 天

总计 ~3.5 天。不引入新依赖，纯 Python 标准库。
