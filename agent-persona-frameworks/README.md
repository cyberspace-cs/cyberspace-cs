# Agent 角色 / 人设框架高星项目调研

> 🎯 方向：帮助 Agent 做角色模型 / 人设 / 角色扮演
> 📅 调研时间：2026年9月
> ⭐ 按 star 数排序，只收录高星优质项目

---

## 🏆 核心项目总览

| 项目 | ⭐ Star | 定位 | 核心亮点 |
| --- | --- | --- | --- |
| **agency-agents** | 20k+ | 300+ AI 专家角色库 | 一键安装到 Claude Code / Cursor |
| **Open Persona** | 5k+ | Agent 人设 Skill 包 | 4+5+3 模型，可进化的人格 |
| **PersonaNexus** | 3k+ | 声明式角色定义 | YAML 定义，多平台编译 |
| **CharacterGPT** | 2k+ | 角色重建框架 | 从小说提取角色人格 |
| **SimsChat** | 1.5k+ | 角色扮演 Agent | 68 个可定制角色 |
| **aevatar** | 1k+ | 多 Agent 平台 | 角色化多 Agent 协作 |

---

## 1. agency-agents — 300+ AI 专家角色库 ⭐⭐⭐⭐⭐

**GitHub**：https://github.com/msitarzewski/agency-agents
**⭐ Star**：20k+
**License**：MIT

### 是什么

把上百个经过打磨的专家 Agent 角色全部开源，让普通用户可以一键拥有一支 7×24 小时待命的虚拟专家团队。

### 核心亮点

- **300+ 预制角色**：CEO、律师、程序员、产品经理、增长黑客、财务顾问、市场策略师……
- **一键安装**：直接装到 Claude Code / Cursor / OpenCode
- **深度调教**：不是随便写两句"你是一个律师"，而是有专业框架的深度角色设定
- **MIT 协议**：完全免费，可自由修改二次开发

### 角色示例

```
📋 产品经理角色
├── 需求分析专家
├── 用户研究员
├── 产品策略师
└── 敏捷教练

💻 技术专家角色
├── 架构师
├── 前端工程师
├── 后端工程师
├── DevOps
└── 安全专家

📈 商业角色
├── CEO / 战略顾问
├── 营销总监
├── 增长黑客
├── 财务顾问
└── 投资人
```

### 为什么重要

- 解决了"AI 太通用，不够专业"的问题
- 一键安装，不用自己写几千字的 system prompt
- 社区持续贡献新角色

---

## 2. Open Persona — Agent 人设 Skill 包 ⭐⭐⭐⭐

**GitHub**：https://github.com/neiljo-gy/open-persona
**⭐ Star**：5k+
**定位**：元 Skill，用于创建、安装、更新、发布 Agent 人设

### 是什么

一个元 Skill（meta-skill），用于创建完整的 Agent 身份包。每个人设都是一个自包含的 Skill 包，包含：
- 人格（Personality）
- 声音/语气（Voice）
- 能力（Capabilities）
- 伦理边界（Ethical Boundaries）

### 4+5+3 模型

**4 层定义（Persona 是什么）**：
1. **Soul（灵魂）** — 核心人格、价值观、动机
2. **Body（身体）** — 声音、外貌、表达方式
3. **Faculty（能力）** — 技能、知识、工具
4. **Skill（技能）** — 具体可执行的任务能力

**5 个系统概念**：
- `evolution` — 人设可以进化
- `consistency` — 行为一致性
- `adaptation` — 适应用户
- `memory` — 记忆持久化
- `growth` — 成长学习

**3 个发布层级**：
- 个人用
- 团队共享
- 公开市场

### 为什么重要

- 把"写 system prompt"变成了"发布人设包"
- 有完整的结构，不是随便写几句话
- 可进化的人设，不是静态的

---

## 3. PersonaNexus — 声明式角色定义 ⭐⭐⭐⭐

**PyPI**：`personanexus`
**⭐ Star**：3k+

### 是什么

声明式 YAML 规范，用来定义 Agent 身份。

### 核心特性

- **声明式 YAML**：用 YAML 定义角色，不用写长 prompt
- **继承和组合**：从可复用的原型和特质 mixin 构建 Agent
- **构建时校验**：部署前 catch 配置错误
- **多目标编译**：YAML → system prompt / SOUL.md / 平台配置
- **人格框架映射**：OCEAN（大五人格）、DISC、荣格 16 型

### YAML 示例

```yaml
name: senior-architect
voice:
  tone: professional
  style: precise
personality:
  big_five:
    openness: 0.8
    conscientiousness: 0.9
    extraversion: 0.4
    agreeableness: 0.6
    neuroticism: 0.2
expertise:
  - system-design
  - distributed-systems
  - cloud-native
guardrails:
  - no-unsafe-decisions
  - evidence-based-recommendations
```

### 为什么重要

- 把人设变成了代码，可版本控制
- 组合模式，不用每个角色都从头写
- 支持心理学框架，更科学

---

## 4. CharacterGPT — 角色重建框架 ⭐⭐⭐⭐

**论文**：arXiv 2405.19778
**GitHub**：开源（论文配套代码）
**⭐ Star**：2k+

### 是什么

从小说/文本中自动重建角色人格的框架。

### 核心创新

**Character Persona Training (CPT)**：
- 从小说章节摘要中提取角色特质
- 增量更新角色人设
- 类似人类记忆巩固成图式（schema）的过程
- 让角色扮演更一致、更符合上下文

### 工作流程

```
小说文本 → 分章节摘要 → 提取角色特质 → 构建角色图式 → 生成一致人设
```

### 为什么重要

- 解决了"角色扮演 Agent 人设不一致"的经典问题
- 从真实文学作品学习，更有深度
- 学术 + 工程结合

---

## 5. SimsChat — 可定制角色扮演 Agent ⭐⭐⭐⭐

**GitHub**：https://github.com/Bernard-Yang/SimsChat
**论文**：arXiv 2406.17962
**⭐ Star**：1.5k+

### 是什么

可定制的角色扮演 Agent 框架，支持自由创建和定制角色。

### 核心数据

- **68 个预定义角色**
- **1,360 个多样化场景**
- **13,971 条多轮对话**

### 角色创建模型

从四个维度定义角色：
1. **Career（职业）**
2. **Aspiration（抱负）**
3. **Trait（特质）**
4. **Skill（技能）**

从这四个维度自动派生出：
- 个人特征
- 社会特征

### 为什么重要

- 有完整的数据集，不只是 prompt 模板
- 角色创建有方法论，不是拍脑袋
- 学术研究级的框架

---

## 6. aevatar — 多 Agent 角色平台 ⭐⭐⭐

**GitHub**：
- 核心框架：https://github.com/aevatarAI/aevatar-framework
- 平台：https://github.com/aevatarAI/aevatar-station
- 案例：https://github.com/aevatarAI/aevatar-gagents

**⭐ Star**：1k+

### 是什么

多 Agent 协作平台，每个 Agent 都有自己的角色和人格。

### 核心定位

- 角色化多 Agent 系统
- 每个 Agent 有自己的身份、记忆、能力
- Agent 之间可以协作完成复杂任务

---

## 📊 分类对比

| 类别 | 代表项目 | 特点 | 适合场景 |
| --- | --- | --- | --- |
| **角色库** | agency-agents | 300+ 预制角色，一键安装 | 快速给 Agent 加专业能力 |
| **人设框架** | Open Persona | 4层模型，可进化 | 构建自己的人设系统 |
| **声明式定义** | PersonaNexus | YAML 定义，版本控制 | 工程化人设管理 |
| **角色重建** | CharacterGPT | 从文本提取角色 | 小说改编、游戏 NPC |
| **角色扮演** | SimsChat | 完整数据集和方法论 | 角色扮演、对话游戏 |
| **多 Agent 平台** | aevatar | 多角色协作 | 团队 Agent 系统 |

---

## 🎯 选型建议

### 新手快速上手
→ **agency-agents**（一键安装，马上能用）

### 想构建自己的人设系统
→ **Open Persona + PersonaNexus**（框架 + 声明式）

### 做角色扮演 / 游戏 NPC
→ **SimsChat + CharacterGPT**（有数据有方法）

### 做多 Agent 协作
→ **aevatar**（多角色平台）

---

## 💡 设计模式总结

### 1. 预制 + 可定制
- 先给好的默认值，再允许修改
- 降低使用门槛，同时保留灵活性

### 2. 分层抽象
- 核心人格（不变）→ 表达方式（可调）→ 技能（可扩展）
- 类似面向对象的继承和多态

### 3. 人设即代码
- 用 YAML/JSON 定义，不是写长 prompt
- 可版本控制、可 review、可组合

### 4. 可进化 / 可成长
- 人设不是静态的，会根据交互学习
- 类似 Open Persona 的 evolution 概念

### 5. 心理学框架支撑
- 用 OCEAN / DISC / 16型人格 等成熟框架
- 让角色更科学、更一致

---

## 📚 参考链接

- agency-agents：https://github.com/msitarzewski/agency-agents
- Open Persona：https://hub.openclaw.ai/neiljo-gy/skills/open-persona
- PersonaNexus：https://pypi.org/project/personanexus/
- CharacterGPT：https://arxiv.org/pdf/2405.19778
- SimsChat：https://github.com/Bernard-Yang/SimsChat
- aevatar：https://github.com/aevatarAI

---

*调研整理时间：2026年9月21日*
*重点：Agent 角色 / 人设 / 角色扮演框架*
