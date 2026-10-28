# JEV 决策模型 — Agent 集成实战指南

> 🎯 目标：把 JEV 快决策模型集成到我们自己的 Agent 里
> ⚡ 核心：System 1（快）+ System 2（慢）双层架构
> 📅 2026年9月

---

## 🧠 核心思路：快慢双层 Agent

### 为什么要用 JEV？

传统 Agent 全靠 LLM，所有决策都走"慢思考"：
- ❌ 慢：每一步都要等 LLM 生成 token
- ❌ 贵：每一步都要花 token 钱
- ❌ 浪费：90% 的决策都是简单选择，根本不需要深度推理

**JEV 分层架构**：
```
用户输入
    ↓
┌─────────────────────────┐
│  System 1: JEV 快决策层  │  ← 90% 的简单决策在这里搞定
│  （0.5B 小模型，毫秒级）  │
└─────────────┬───────────┘
              ↓ 遇到复杂问题
┌─────────────────────────┐
│  System 2: LLM 慢推理层  │  ← 只有 10% 的复杂问题才走这里
│  （GPT/Claude/DeepSeek） │
└─────────────────────────┘
```

### 效果对比

| 指标 | 纯 LLM | JEV + LLM 混合 | 提升 |
| --- | --- | --- | --- |
| **平均响应时间** | 2-5 秒 | 200-500 毫秒 | **快 10 倍** |
| **单次任务成本** | $0.05 | $0.005 | **便宜 10 倍** |
| **浏览器操作步数** | 平均 15 步 | 平均 8 步 | **少 47%** |
| **简单决策准确率** | 92% | 95% | **更高** |

---

## 🏗️ 完整架构设计

### 1. 整体架构图

```
┌─────────────────────────────────────────────────┐
│                   用户输入层                      │
└─────────────────────┬───────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│              JEV 路由器（快决策）                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ 意图识别  │  │ 工具选择  │  │ 动作分类  │        │
│  │ (0.5B)   │  │ (0.5B)   │  │ (0.5B)   │        │
│  └─────────┘  └─────────┘  └─────────┘        │
└─────────────┬───────────────────┬─────────────┘
              ↓ 简单              ↓ 复杂
┌─────────────────────┐  ┌─────────────────────┐
│  直接执行动作         │  │  LLM 深度推理         │
│  （毫秒级）           │  │ （秒级）             │
│  - 点击按钮          │  │  - 多步规划          │
│  - 选择选项          │  │  - 复杂推理          │
│  - 简单分类          │  │  - 代码生成          │
└─────────────────────┘  └──────────┬──────────┘
                                    ↓
                            ┌───────────────┐
                            │ 执行结果反馈   │
                            └───────────────┘
```

### 2. 三大核心 JEV 模型

| 模型 | 参数量 | 作用 | 速度 |
| --- | --- | --- | --- |
| **意图识别模型** | 0.5B | 判断用户想做什么 | 50ms |
| **工具选择模型** | 0.5B | 该用哪个工具/函数 | 30ms |
| **动作选择模型** | 1.5B | 浏览器里点哪个元素 | 100ms |

---

## 🛠️ 怎么落地？三种方案

### 方案一：直接用现成的（最快上手）

**适合：快速验证效果，不想自己训练**

| 项目 | 星数 | 用法 |
| --- | --- | --- |
| **jev-ultrafast** | 10k+ | 直接拿来做浏览器 Agent |
| **fast-browser-use** | 1k+ | 开箱即用 Skill，三平台支持 |
| **openjev** | 2k+ | 浏览器端直接跑，零部署 |

**快速上手步骤**：

```bash
# 1. 克隆 jev-ultrafast
git clone https://github.com/browser-use/jev-ultrafast.git
cd jev-ultrafast

# 2. 安装依赖
pip install -r requirements.txt

# 3. 跑 Demo
python demo.py --url "https://example.com" --task "查机票"
```

**效果**：直接得到一个超快的浏览器 Agent

---

### 方案二：微调自己的小模型（性价比最高）

**适合：想定制化，有自己的数据**

**基于 kev（jaredpalmer 出品）**：
- 底座：Qwen2.5-0.5B
- 硬件：MacBook 16GB 就能训
- 时间：1-2 小时就能训完一个决策模型

**训练流程**：

```python
# 1. 准备数据（格式：输入 + 候选选项 + 正确答案）
training_data = [
    {
        "input": "用户说：帮我查北京到上海的机票",
        "candidates": ["查机票", "查酒店", "查火车", "发消息"],
        "label": 0  # 选第 0 个
    },
    # ... 1000-5000 条数据
]

# 2. 用 LoRA 微调
from peft import LoraConfig

lora_config = LoraConfig(
    r=8,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
)

# 3. 训练（用 RLCD 方法）
# RLCD = Reinforcement Learning for Classified Decisions
# 不是 SFT，而是把决策当分类问题来训

# 4. 推理
def fast_decision(input_text, candidates):
    # 输入文本 + 候选选项，直接输出选第几个
    # 毫秒级返回
    return model.predict(input_text, candidates)
```

**为什么选 0.5B？**
- ✅ 决策任务不需要大模型
- ✅ 推理快，CPU 都能跑
- ✅ 训练便宜，消费级硬件就行
- ✅ 可以本地部署，隐私安全

---

### 方案三：纯推理不训练（最轻量）

**适合：不想训练，直接用提示工程**

**思路**：不用训练模型，直接用小模型 + 好的提示词，让它做决策。

```python
# 用 Qwen2.5-1.5B + 分类提示词
SYSTEM_PROMPT = """
你是一个快速决策助手。用户会给你一个任务和几个候选选项。
你只需要输出选项的编号（1, 2, 3, ...），不要输出其他任何内容。

候选选项：
1. {option_1}
2. {option_2}
3. {option_3}

用户任务：{user_task}

请直接输出选项编号：
"""

def fast_decision(user_task, candidates):
    prompt = SYSTEM_PROMPT.format(
        option_1=candidates[0],
        option_2=candidates[1],
        option_3=candidates[2],
        user_task=user_task
    )
    
    # 用小模型推理，max_new_tokens=1，只输出一个数字
    result = model.generate(prompt, max_new_tokens=1)
    return int(result.strip()) - 1
```

**效果**：虽然不如训练过的 JEV 快，但比用 GPT-4 快 5-10 倍，成本低 100 倍。

---

## 🚀 怎么和我们的 Agent 集成？

### 集成点 1：工具路由（最实用）

**问题**：Agent 有几十上百个工具，每次都要 LLM 选，慢且贵。

**JEV 方案**：
```python
# 原来：每次都问 LLM
# response = llm.chat("用户想查天气，应该用哪个工具？", tools_list)
# 耗时：2 秒，成本：$0.001

# 现在：JEV 快选
# tool_index = jev_decision("用户想查天气", tools_list)
# 耗时：50ms，成本：$0.00001

# 准确率：差不多 95%
# 只有 5% 的情况选错了，再 fallback 到 LLM
```

**实现**：
```python
class JEVToolRouter:
    def __init__(self):
        self.jev_model = load_jev_model("tool-select-0.5b")
        self.fallback_llm = load_llm()
    
    def select_tool(self, user_input, available_tools):
        # 1. 先用 JEV 快速选
        candidates = [tool.description for tool in available_tools]
        tool_index = self.jev_model.predict(user_input, candidates)
        
        # 2. 置信度低于阈值，再 fallback 到 LLM
        confidence = self.jev_model.confidence()
        if confidence < 0.8:
            tool_index = self.fallback_llm.select_tool(user_input, available_tools)
        
        return available_tools[tool_index]
```

---

### 集成点 2：浏览器操作（效果最明显）

**问题**：浏览器 Agent 每一步都要 LLM 决定点哪个元素，慢且贵。

**JEV 方案**（jev-ultrafast 已经实现了）：
```python
# 原来：每一步都问 LLM
# element = llm.choose_element(page_dom, task)
# 耗时：2 秒，成本：$0.002

# 现在：JEV 直接选元素
# element = jev_choose_element(page_elements, task)
# 耗时：100ms，成本：$0.00005

# 一个 10 步的任务：
# 原来：20 秒，$0.02
# 现在：1 秒，$0.0005
```

---

### 集成点 3：意图识别（入口优化）

**问题**：用户说一句话，先要判断是什么意图，再分发到对应的 Agent。

**JEV 方案**：
```python
# 意图分类：10 个常用意图
INTENTS = [
    "查天气", "查日历", "发消息", "写邮件",
    "查代码", "改代码", "写文档", "查资料",
    "做表格", "其他"
]

# JEV 毫秒级分类
intent = jev_classify(user_message, INTENTS)

# 95% 是这 10 个里面的，直接分发
# 只有 5% 的"其他"才走 LLM 深度理解
```

---

## ⚡ 和传统 LLM 的核心区别

| 维度 | 传统 LLM | JEV 决策模型 | 优化点 |
| --- | --- | --- | --- |
| **推理方式** | 自回归逐 token 生成 | 并行分类，一次出结果 | **快 40-200 倍** |
| **输出格式** | 自由文本 | 固定选项编号 | 不需要解码，直接拿结果 |
| **训练方法** | SFT（监督微调） | RLCD（分类决策强化学习） | 把决策当分类问题训 |
| **模型大小** | 7B-70B | 0.5B-1.5B | 小模型快且便宜 |
| **成本** | $0.002/千 token | $0.00005/次决策 | **便宜 100 倍** |
| **幻觉** | 容易幻觉 | 几乎不会幻觉 | 因为只能选预设选项 |
| **适用场景** | 复杂推理、生成 | 简单决策、选择 | 分层用，各干各的 |

---

## 🔧 优化技巧

### 1. 动态候选空间

**问题**：候选选项太多，模型选不准。

**优化**：先过滤，再选择
```python
# 第一步：粗筛（从 100 个工具里筛出 10 个相关的）
shortlist = keyword_filter(user_input, all_tools, top_k=10)

# 第二步：精排（JEV 从 10 个里选 1 个）
best_tool = jev_predict(user_input, shortlist)
```

### 2. 置信度阈值 + Fallback

**问题**：JEV 有时候不确定，选错了。

**优化**：不确定就交给 LLM
```python
prediction = jev_model.predict(input, candidates)
confidence = prediction.confidence

if confidence > 0.9:
    # 很确定，直接用
    return prediction.choice
else:
    # 不确定，交给 LLM
    return llm_deep_reasoning(input, candidates)
```

### 3. 蒸馏：用大模型教小模型

**问题**：没有训练数据。

**优化**：用 GPT-4 生成数据
```python
# 1. 让 GPT-4 回答 10000 个决策问题
# 2. 把这些问题和答案作为训练数据
# 3. 训练 0.5B 的小模型
# 4. 小模型就能达到大模型 90% 的效果
```

**这就是"模型蒸馏"**：大模型当老师，小模型当学生。

### 4. 缓存：相同问题直接返回

**问题**：很多决策是重复的。

**优化**：加缓存
```python
@lru_cache(maxsize=10000)
def fast_decision(input_hash, candidates_hash):
    return jev_model.predict(input, candidates)
```

---

## 🎯 我们的 DIY 路线图

### 第一阶段：快速验证（1 周）
- [ ] 克隆 jev-ultrafast，跑通 Demo
- [ ] 集成到我们的 DIY Agent Harness
- [ ] 做工具路由的 JEV 版本
- [ ] 对比效果：速度、成本、准确率

### 第二阶段：微调自己的模型（2 周）
- [ ] 收集我们自己的工具选择数据（1000-5000 条）
- [ ] 用 Qwen2.5-0.5B + LoRA 微调
- [ ] 训练自己的工具路由模型
- [ ] 测试准确率，调优

### 第三阶段：浏览器 Agent 集成（2 周）
- [ ] 集成 jev-ultrafast 的动作选择
- [ ] 做浏览器自动化的快慢分层
- [ ] 对比纯 LLM 的效果提升

### 第四阶段：全 Agent 分层（长期）
- [ ] 意图识别用 JEV
- [ ] 工具路由用 JEV
- [ ] 动作选择用 JEV
- [ ] 只有复杂推理才走 LLM

---

## 📚 参考项目

- jev-ultrafast：https://github.com/browser-use/jev-ultrafast
- kev：https://github.com/jaredpalmer/kev
- NanoJev：https://github.com/TianyuCodings/NanoJev
- openjev：https://openjev.com/

---

*整理时间：2026年9月21日*
*目标：把 JEV 决策模型集成到 DIY Agent Harness*
