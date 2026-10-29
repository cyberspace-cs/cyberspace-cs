# cyberspace-cs · 飞书式 IM 教学项目（单条已读回执）

> 从零到一实现一个 **飞书 / 钉钉 B 端风格** 的即时消息系统：扩散读 + 会话红点水位线 + **单条消息已读回执**。
> 代码逐条对应「大厂 IM 系统设计对比」，是面试时横向对比 Redis+MySQL 选型的最佳样本。

- GitHub：https://github.com/cyberspace-cs/cyberspace-cs （**本 IM 项目位于 `im/` 子目录**，与原仓库其它项目共存）
- Gitee：https://gitee.com/buleboy8065/cyberspace-cs （独立仓库，IM 项目在根目录）
- 线上演示（部署后）：http://taoxie.vip/im/
- **系统设计与成本账**：见 [DESIGN.md](DESIGN.md)（六条链路、Redis/MySQL 逐 key 设计、内存与写入放大测算）

---

## 1. 这个项目和「大厂对比」怎么对应

你整理的对比表里，**飞书 / 钉钉（B 端办公 IM）** 这一段，就是本项目的实现目标：

| 对比项 | 本项目的落地 |
| --- | --- |
| MySQL 角色 | `messages`（单副本扩散读）、`user_conv_read`（会话水位线）、`user_msg_read`（单条回执明细，7 天归档冷存储） |
| Redis 角色 | `Set msg:{msgId}:readers`（已读 uid）、`Bitmap`（批量统计已读人数）、`String`（latest_seq / read_seq 水位线）、`List`（离线消息环）、`Set`（网关路由） |
| 核心矛盾 | 单条回执写入量巨大（每条被读都写一行） |
| 一致性 | 回执尽量准；**超大群 / 高峰期可降级**，优先保消息收发主链路 |

一句话区分（面试口述）：
> **C 端微信**用「水位线」做红点，**只存用户读到的最大 seq**；**B 端飞书**额外给「每一条消息」记谁读了（已读回执）；**直播大群**直接放弃服务端精确未读数，改客户端拉取。

---

## 2. 快速开始（本地 Docker 一键起）

```bash
cd im                          # GitHub 仓库需先进入 im/ 子目录（Gitee 仓库在根目录，无需 cd）
docker compose up -d          # 起 MySQL8 + Redis7 + IM 服务
curl -X POST http://localhost:8080/api/seed   # 灌入演示数据（4 用户 + 单聊 + 群聊）
# 浏览器打开 http://localhost:8080/ ，分别在两个窗口选不同身份登录即可体验
```

端到端冒烟测试（需服务已启动，验证飞书式已读回执全链路）：

```bash
cd im
go run ./cmd/smoke            # Alice 发群消息 → Bob/Carol 收到 → 已读 → Alice 收回报执
```

**50 人规模「未读数快速获取」基准测试**（需服务已启动）：

```bash
curl -X POST "http://localhost:8080/api/seed_big?n=50"   # 灌入 50 人压测群
go run ./cmd/bench_unread     # 对比「水位线减法 O(1)」vs「朴素 COUNT(*) O(n)」，并测 SCARD/SMEMBERS
```

实测结论（50 人群、会话 4001 条消息）：49 人批量取未读，水位线 6.3 ms vs COUNT 31 ms（≈4.9×）；
未读越大差距越大（未读 4001 条时 ≈7.2×），水位线耗时恒定不随消息数增长。

### 界面：还原飞书桌面客户端风格

前端（`web/`）刻意对齐**飞书桌面客户端浅色主题**，设计令牌与飞书一致：

| 飞书元素 | 本项目实现 |
| --- | --- |
| 最左深色拉丝导航栏（消息/通讯录/云文档/日历/会议/设置） | `.rail` 深底白字，当前页蓝色高亮 |
| 会话列表（头像 + 名称 + 最后一条消息预览 + 红点未读） | 红点由 `latest_seq - read_seq` 水位线驱动 |
| 聊天主区（标题 + 成员头像 + 群成员抽屉） | 点击右上「成员」图标开右抽屉 |
| **单条已读回执**（自己消息下方「已读 X/Y」+ 读者头像，可点开看谁已读/未读） | 飞书招牌能力，点开弹窗区分已读/未读成员 |
| 品牌色 `#3370FF`、主文字 `#1F2329`、未读红 `#F54A45` | CSS 变量 `--fs-brand` 等 |

> 体验方式：用**两个浏览器窗口**分别登录 Alice(1001) 与 Bob(1002)；Alice 在群里发消息，Bob 打开会话即触发「已读」，Alice 立刻看到自己消息下方的「已读 1/3」与 Bob 头像，点开可看完整已读/未读名单。

### 对外接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/users` | 全部用户（uid/name/avatar） |
| GET | `/api/conversations?uid=` | 会话列表，带未读水位线 + 最后一条消息预览 |
| GET | `/api/messages?conv_id=&before_seq=&limit=` | 按 seq 拉历史（扩散读） |
| GET | `/api/members?conv_id=` | 会话成员（用于头像、回执详情） |
| GET | `/api/receipt?conv_id=&msg_id=` | 某条消息已读回执快照（读者 / 已读人数 / 应读人数） |
| POST | `/api/seed` | 灌入演示数据 |
| WS | `/ws` | 登录、收发消息、已读回执、未读水位线推送 |

手动构建运行：

```bash
cd im
export MYSQL_DSN='root:rootpass@tcp(127.0.0.1:3306)/im?parseTime=true&charset=utf8mb4&loc=Local'
export REDIS_ADDR=127.0.0.1:6379
go run ./cmd/server
```

---

## 3. 架构总览

```mermaid
sequenceDiagram
    participant A as Alice(发送者)
    participant S as IM 服务
    participant DB as MySQL
    participant R as Redis
    participant B as Bob(接收者)

    A->>S: send 消息
    S->>DB: 事务内分配 seq（FOR UPDATE），消息单副本落库
    S->>R: 更新 conv latest_seq 水位线
    S->>B: Pub/Sub 推送 message（在线）/ 离线消息环（离线）
    Note over S,B: 扩散读：每人从同一份消息取，不复制

    B->>S: read 读到 seq=N
    S->>DB: 推进 user_conv_read.read_seq（红点消失）
    S->>R: 把 Bob 加入 msg:{id}:readers（Set）+ Bitmap 置位
    S->>DB: 写 user_msg_read 回执明细（审计/冷归档）
    S->>A: 推送 receipt（谁读了 / X/Y 已读）← 飞书招牌
```

---

## 4. 数据模型

### MySQL（持久化基准源）
| 表 | 作用 | 关键字段 |
| --- | --- | --- |
| `users` | 用户 | uid, name, avatar |
| `conversations` | 会话 | conv_id, type(1单聊/2群), **latest_seq** |
| `conversation_members` | 成员关系 | conv_id, uid |
| `messages` | 消息（**单副本扩散读**） | msg_id, conv_id, sender_uid, **seq（UNIQUE(conv_id,seq)）** |
| `user_conv_read` | **会话水位线（红点基准）** | uid, conv_id, read_seq |
| `user_msg_read` | **单条已读回执明细** | conv_id, msg_id, uid（7 天外归档 `user_msg_read_cold`） |

### Redis（热点 / 计数 / 回执 / 路由）
| Key | 结构 | 作用 |
| --- | --- | --- |
| `im:conv:{id}:latest` | String | 会话最新 seq（旁路缓存） |
| `im:user:{uid}:conv:{id}:read` | String | 用户在该会话的读水位线 |
| `im:msg:{msgId}:readers` | Set | **已读这条消息的 uid 集合（飞书回执）** |
| `im:msg:{msgId}:rb` | Bitmap | 按成员位统计已读人数（群大时替代 SMEMBERS 省内存） |
| `im:user:{uid}:offline:{convId}` | List(环形) | 离线消息环，只留最近 N 条 |
| `im:user:{uid}:gateways` | Set | 用户当前连在哪台机器（网关路由） |
| `im:user:{uid}` | Pub/Sub | 跨节点投递总线 |

---

## 5. 核心流程：飞书式已读回执是怎么做的

1. **发消息**：MySQL 事务里 `SELECT latest_seq ... FOR UPDATE` 分配单调递增 `seq`，消息只存一份；Redis 更新 `latest_seq`；再经 Pub/Sub 把消息推给在线成员，离线成员写入「离线消息环」。
2. **标记已读**：客户端上报读到的最大 `seq`。服务端：
   - 推进 `user_conv_read.read_seq` → 会话红点基于 `latest_seq - read_seq` 消失；
   - 把该用户写进区间内**每条消息**的 `Set`（读者集合）+ `Bitmap` 置位；
   - 落库 `user_msg_read`（审计，生产按 7 天归档冷存储）；
   - 把回执（谁读了 / X/Y 已读）推给**消息发送者** —— 这就是飞书「看到谁读了我的消息」。
3. **降级保护**：
   - 单次「已读」只给最近 50 条消息写回执，避免一次读 1000 条导致写放大；
   - 成员数超过 `BIG_GROUP_THRESHOLD`（默认 200）的**超大群**，或 `RECEIPT_DEGRADE=1` 时，**只推进水位线、不再维护单条回执**，优先保住消息收发主链路。

---

## 6. 横向对比（面试直接背）

| 系统 | 核心矛盾 | MySQL 作用 | Redis 核心结构 | 一致性要求 |
| --- | --- | --- | --- | --- |
| **C 端 IM（微信）** | 群扩散写爆炸、红点高频查 | 水位线、消息持久化 | String、Bitmap、RingBuffer | 最终一致，红点允许短暂不准 |
| **B 端 IM（飞书/钉钉）** | 回执写入量巨大 | 单条消息回执明细 | **Set、Bitmap** | 回执尽量准，高峰可降级 |
| Feed 社交（微博） | 大 V 发动态写放大 | 博文、关系流水 | ZSet、Hash、分片 Counter | 最终一致 |
| 电商秒杀 | 防超卖、高并发抢券 | 库存、订单事务 | String、Lua、分布式锁 | 库存强一致，计数可异步 |
| 直播弹幕 | 瞬时 QPS 极高 | 主播配置、封禁 | List、ZSet、Stream | 弱一致，在线数允许误差 |
| Agent 大模型平台 | 会话上下文、工具并发 | 会话、计费、日志 | Hash、String、Stream | 配额强一致，会话状态最终一致 |

**加分话术**：
> 不同系统的 Redis+DB 设计，本质都是「识别热点路径，把读多写多、允许短暂不一致的热点放 Redis；事务、审计、不可丢失的基准数据放 MySQL」。
> IM 重点是区分 **C 端红点水位线** 和 **B 端单条回执**；Feed 是 fanout 推流 + ZSet 收件箱；电商核心是库存 Lua 原子扣减；Agent 平台用 Redis 做会话状态、模型路由、token 限流。
> 同时按规模降级：超大群放弃精确未读、热点计数分片、B 端回执高峰期降级，优先保住主链路。

---

## 7. 部署到 taoxie.vip/im

1. 服务器 `43.143.231.106`（taoxie.vip 已解析到此 IP），用户 `ubuntu`。
2. 已准备好 `nginx.conf`（把 `/im/` 反代到本地 8080，支持 WebSocket 升级）。
3. 提供 `deploy.sh`：同步代码 → `docker compose up -d` → 写入 nginx 反代 → reload。
4. 执行需服务器 SSH 私钥（`id_ed25519_audit_server`）。当前沙箱未持有该密钥，脚本已就绪，提供密钥后即一键上线；在此之前可用 `docker compose up -d` 在任意机器本地验证。

---

## 8. 目录结构

```
cmd/server/main.go        入口：装配 store/cache/hub/http
internal/config           环境变量配置
internal/db               MySQL(store.go) + Redis(cache.go) + schema.sql
internal/model            领域模型
internal/protocol         WebSocket JSON 协议
internal/ws               WebSocket 网关（Hub + 客户端 + Pub/Sub 跨节点路由）
internal/service          业务逻辑（发消息 / 已读回执 / 水位线 / 降级）
internal/api              REST + WS 升级
web/                     演示前端（红点 + 已读回执展示）
docker-compose.yml / Dockerfile / nginx.conf / deploy.sh
```

## v2 能力清单（对齐飞书桌面端）

后端从 9 个接口扩到 28 个，前端从单页扩到「消息 + 通讯录」双页。

| 域 | 接口 | 说明 |
|---|---|---|
| 认证 | `POST /auth/login` `POST /auth/logout` `GET /auth/me` | 签发 token（sessions 表），后续请求带 `Authorization: Bearer`；无 token 时回落 `?uid=` 仅作教学脚本兼容 |
| 会话 | `POST /conversations` | 建单聊/群聊，单聊自动复用已有会话 |
| 成员 | `POST /conversations/members` | add / remove / leave，自动发一条系统消息 |
| 设置 | `POST /conversations/settings` | 置顶 / 免打扰 / 标记未读 |
| 消息 | `GET /messages?after_seq=` | 增量补拉（断线重连、多端同步） |
| 消息 | `POST /messages/recall` | 2 分钟内、仅发送者，越权拦截 |
| 消息 | `POST /messages/reaction` | 表情回应，同人同表情再点即取消 |
| 消息 | `POST /messages/forward` | 转发到多个会话 |
| 回执 | `GET /receipt?offset=&limit=` | 名单分页，大群只渲染一屏 |
| 汇总 | `GET /unread/summary` | 总未读 / 有未读会话数 / @我 / 单聊 / 群聊 |
| 搜索 | `GET /search?q=&scope=` | 消息 + 联系人 + 群组三路合并 |
| 提及 | `GET /mentions` | @我的消息 |
| 同步 | `GET /read/state` | 多端已读位置一次拉齐 |
| 在线 | `GET /presence?conv_id=` | 会话内在线成员 |
| 名片 | `GET /user?uid=` `GET /org/tree` | 部门 / 职位 / 邮箱 + 组织架构树 |
| 上传 | `POST /upload` | 图片/文件，落 `web/uploads/` |
| 通知 | `GET /notifications` `POST /notifications/read` | 与业务消息分流的通知中心 |

WebSocket 新增 `typing`（正在输入）、`recall`、`reaction`、`presence` 事件；`send` 支持 `reply_to` / `at_uids` / `files`。

前端新增：会话 tab（全部/未读/@我）、置顶分组、免打扰、未读胶囊、引用回复、@提及、
表情回应、图片文件、撤回、转发、已读回执双列弹窗、全局搜索、通知抽屉、名片、通讯录。

数据库：`messages` 加 `reply_to/at_uids/recalled`，`users` 加 `dept/dept_id/dept_title/email/phone`，
新增 `conv_settings` / `reactions` / `attachments` / `notifications` / `sessions` / `departments` 六张表。
旧库用 `internal/db/migrate.go` 做幂等补列，不需要重建。
