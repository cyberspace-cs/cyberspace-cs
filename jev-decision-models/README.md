# JEV 决策模型 — 高星开源项目调研

> ⚡ 核心：只输出决策，不生成文本的"System 1"快思考模型
> 🚀 比传统 LLM 快 40-200 倍，便宜 100 倍
> 📅 调研时间：2026年9月

---

## 🧠 什么是 JEV？

**JEV** 是 TypeSafe 推出的"决策模型"（Decision Model），和传统 LLM 完全不同：

| 维度 | 传统 LLM（System 2 慢思考） | JEV（System 1 快思考） |
| --- | --- | --- |
| **输出** | 自回归生成文本 | 只输出决策/分类/选择 |
| **速度** | 慢（逐 token 生成） | 快 40-200 倍（并行推理） |
| **成本** | 高 | 便宜 100 倍 |
| **幻觉** | 容易幻觉 | 几乎不会幻觉 |
| **训练方法** | 自回归 | RLCD（强化学习分类决策） |
| **适合场景** | 写文章、写代码、长文本 | 选按钮、选选项、做决策 |

### 核心原理

```
传统 LLM：输入 → 逐 token 生成 → 输出完整文本（慢）
JEV：输入 + 候选动作 → 直接选一个 → 输出决策（快）
```

**典型例子**：
- 网页 Agent：拿到 DOM → 直接选该点哪个元素（毫秒级）
- 客服：用户问题 → 直接分类到哪个工单类型
- 交易：市场数据 → 直接选买/卖/持有

---

## 🏆 开源复现项目总览

| 项目 | ⭐ Star | 定位 | 核心亮点 |
| --- | --- | --- | --- |
| **jev-ultrafast** | 10k+ | 浏览器 Agent | Browser Use 官方出品，动态动作空间 |
| **kev** | 5k+ | 0.5B 小模型 | jaredpalmer 出品，MacBook 可训练 |
| **NanoJev** | 3k+ | 完整训练流程 | nanoGPT 风格，并行决策+动态候选 |
| **openjev** | 2k+ | 浏览器端运行 | 纯前端，浏览器里跑决策模型 |
| **open-alternative-jev** | 1.5k+ | 基准测试 | 完整评估框架 |
| **fast-browser-use** | 1k+ | 开箱即用 Skill | APUS 出品，三平台支持 |
| **HA-Jev** | 500+ | Home Assistant 集成 | 智能家居决策 |

---

## 1. jev-ultrafast — 浏览器 Agent 官方实现 ⭐⭐⭐⭐⭐

**GitHub**：https://github.com/browser-use/jev-ultrafast
**⭐ Star**：10k+
**出品方**：Browser Use 团队

### 是什么

Browser Use 团队官方出品的超快速浏览器 Agent，用 JEV 做决策大脑。

### 核心亮点

- **动态索引动作空间**：不需要解析完整指令集，直接选元素
- **毫秒级决策**：选按钮速度从秒级降到毫秒级
- **Demo 效果**：
  - 打开网页查机票
  - 全程耗时仅 7 秒
  - 成本只要 $0.0039（约 3 分钱人民币）

### 工作流程

```
1. 读取页面 DOM
2. 生成候选动作列表
3. JEV 毫秒级选出最佳动作
4. 浏览器执行动作
5. 重复直到任务完成
```

### 为什么重要

- 证明了 JEV 在浏览器 Agent 场景的价值
- 开源可复现，社区可以直接用
- 把浏览器 Agent 的成本和速度打了两个数量级

---

## 2. kev — 0.5B 小模型，MacBook 可训练 ⭐⭐⭐⭐⭐

**GitHub**：https://github.com/jaredpalmer/kev
**⭐ Star**：5k+
**作者**：jaredpalmer（TanStack 创始人）

### 是什么

基于 Qwen2.5-0.5B 的超小 JEV 复现模型，你可以在自己的 MacBook 上训练和运行。

### 核心亮点

- **0.5B 参数**：超小，消费级硬件就能跑
- **MacBook 可训练**：不需要 GPU 服务器
- **LoRA 微调**：用 LoRA 高效适配决策任务
- **开源权重**：HuggingFace 上有预训练权重

### 硬件需求

| 场景 | 最低配置 |
| --- | --- |
| 推理 | 8GB 内存 |
| 训练 | 16GB 内存 + Apple Silicon |

### 为什么重要

- 证明了 JEV 不需要大模型，小模型就能做好决策
- 个人开发者也能玩得起
- 开源完整训练流程，可学习可复现

---

## 3. NanoJev — 完整训练流程 ⭐⭐⭐⭐

**GitHub**：https://github.com/TianyuCodings/NanoJev
**⭐ Star**：3k+

### 是什么

nanoGPT 风格的最小 JEV 复现项目，包含完整的训练流程。

### 核心亮点

- **并行决策**：一次推理选一个动作，不是逐 token 生成
- **动态候选项**：支持动态生成候选动作列表
- **完整训练流程**：从数据准备到模型训练到部署
- **极小代码量**：像 nanoGPT 一样，代码简洁易懂

### 技术特点

- 并行决策头（Parallel Decision Head）
- 动态候选空间（Dynamic Candidate Space）
- RLCD 训练方法（Reinforcement Learning for Classified Decisions）

### 为什么重要

- 教学价值极高，适合学习 JEV 原理
- 代码简洁，容易改和扩展
- 完整流程，不是半成品

---

## 4. openjev — 浏览器端运行 ⭐⭐⭐⭐

**GitHub**：https://github.com/TheoLeeCJ/openjev
**官网**：https://openjev.com/
**⭐ Star**：2k+

### 是什么

纯浏览器端运行的 JEV 复现，不需要服务器，打开网页就能用。

### 核心亮点

- **浏览器里跑**：WebAssembly + 量化模型
- **离线可用**：加载后不需要网络
- **零部署**：打开网页就能玩
- **和官方对比**：84.5% 接近官方 102 行测试子集

### 为什么重要

- 极低门槛，打开网页就能体验 JEV
- 证明了小模型可以在浏览器端跑
- 适合做前端 Agent 的决策层

---

## 5. open-alternative-jev — 基准测试框架 ⭐⭐⭐

**GitHub**：https://github.com/ikermoel/open-alternative-jev
**⭐ Star**：1.5k+

### 是什么

用开源模型复现 JEV 风格的 System One 决策层，附带完整基准测试。

### 核心亮点

- **完整基准测试**：标准化评估决策模型
- **多模型对比**：对比不同开源模型的决策能力
- **RLCD 复现**：完整复现 RLCD 训练方法
- **校准概率**：LCD 训练校准概率输出

### 为什么重要

- 有标准基准，不是自说自话
- 可以用来评估自己的决策模型
- 多模型对比，帮你选最合适的底座

---

## 6. fast-browser-use — 开箱即用 Agent Skill ⭐⭐⭐

**出品方**：APUS（麒麟合盛）
**⭐ Star**：1k+
**License**：MIT

### 是什么

全球首批针对 JEV 的独立开源复现，包装成开箱即用的 Agent Skill。

### 核心亮点

- **开箱即用**：不需要自己训练，直接装
- **三平台支持**：macOS / Linux / Windows
- **纯本地运行**：支持纯本地模型离线执行
- **GPU 可选**：有 GPU 更快，没 GPU 也能跑

### 为什么重要

- 企业级出品，不是个人玩具项目
- 开箱即用，不用折腾训练
- 本地离线，隐私安全

---

## 7. HA-Jev — Home Assistant 智能家居集成 ⭐⭐⭐

**GitHub**：https://github.com/AboveColin/HA-Jev
**⭐ Star**：500+

### 是什么

把 JEV 接入 Home Assistant，做智能家居的决策大脑。

### 核心亮点

- **传感器决策**：根据传感器数据做决策
- **自动化动作**：自动执行家居控制
- **Assist Agent**：语音助手的决策层
- **自定义集成**：HACS 一键安装

### 为什么重要

- 证明了 JEV 不只是网页 Agent，还能用在 IoT 场景
- 智能家居是天然的"决策问题"
- 开源社区已经在用了

---

## 📊 分类对比

| 类别 | 代表项目 | 特点 | 适合谁 |
| --- | --- | --- | --- |
| **浏览器 Agent** | jev-ultrafast | 官方实现，效果最好 | 做网页自动化 |
| **小模型训练** | kev | 0.5B，MacBook 可训 | 个人开发者 |
| **学习原理** | NanoJev | 代码简洁，完整流程 | 想学习 JEV 原理 |
| **前端体验** | openjev | 浏览器里跑 | 快速体验 |
| **基准测试** | open-alternative-jev | 标准化评估 | 做模型研究 |
| **开箱即用** | fast-browser-use | 企业级，三平台 | 直接用在产品里 |
| **智能家居** | HA-Jev | Home Assistant 集成 | IoT 场景 |

---

## 🎯 选型建议

### 想快速体验 JEV
→ **openjev**（打开网页就能玩）

### 想做浏览器 Agent
→ **jev-ultrafast**（官方实现，效果最好）

### 想学习 JEV 原理
→ **NanoJev**（代码简洁，完整训练流程）

### 想自己训练一个小模型
→ **kev**（0.5B，MacBook 就能训）

### 想直接用在产品里
→ **fast-browser-use**（开箱即用，三平台）

### 做智能家居 / IoT
→ **HA-Jev**（Home Assistant 集成）

---

## 💡 为什么 JEV 重要？

### 1. 快慢思考分层
- **System 1（快）**：JEV，做简单决策，毫秒级
- **System 2（慢）**：传统 LLM，做复杂推理，秒级
- 组合起来：快的做 90% 的简单决策，慢的只做 10% 的复杂推理
- 成本降 10 倍，速度升 10 倍

### 2. 决策 ≠ 生成
- 很多场景根本不需要生成长文本，只需要"选一个"
- 传统 LLM 用大炮打蚊子，既慢又贵
- JEV 把决策这件事做到了极致

### 3. 小模型足够
- 决策任务不需要大模型，0.5B 就够了
- 小模型可以跑在端侧，隐私安全
- 成本极低，可以大规模用

---

## 🚀 可借鉴的创业方向

| 方向 | 参考项目 | 切入点 |
| --- | --- | --- |
| 浏览器 Agent | jev-ultrafast | 网页自动化、RPA |
| 客服分类 | JEV 决策层 | 工单分类、意图识别 |
| 智能家居 | HA-Jev | IoT 决策大脑 |
| 金融交易 | jev-trader | 快速交易决策 |
| 内容审核 | JEV 分类 | 毫秒级内容分类 |
| 游戏 NPC | JEV 决策 | 快速反应决策 |

---

## 📚 参考链接

- 官方 JEV 介绍：TypeSafe AI
- jev-ultrafast：https://github.com/browser-use/jev-ultrafast
- kev：https://github.com/jaredpalmer/kev
- NanoJev：https://github.com/TianyuCodings/NanoJev
- openjev：https://openjev.com/
- open-alternative-jev：https://github.com/ikermoel/open-alternative-jev
- Awesome JEV 合集：https://aiproducthub.cn/status/52516.html

---

*调研整理时间：2026年9月21日*
*重点：JEV 决策模型开源复现项目*
