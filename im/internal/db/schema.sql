-- ============================================================================
-- cyberspace-cs IM 教学库 schema
-- 设计对齐：飞书 / 钉钉 B 端 IM（单条已读回执）
-- 核心思想：MySQL 做持久化基准源、事务、审计、冷数据；
--           Redis 做热点、计数、回执集合、水位线、路由。绝大多数是最终一致。
-- ============================================================================

CREATE DATABASE IF NOT EXISTS im DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE im;

-- 用户表 ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  uid        BIGINT       PRIMARY KEY,
  name       VARCHAR(64)  NOT NULL,
  avatar     VARCHAR(256),
  dept       VARCHAR(64)  DEFAULT '' COMMENT '部门名（冗余，列表直接展示）',
  dept_id    BIGINT       DEFAULT 0  COMMENT '部门 id（组织架构树）',
  dept_title VARCHAR(64)  DEFAULT '' COMMENT '职位',
  email      VARCHAR(128) DEFAULT '',
  phone      VARCHAR(32)  DEFAULT '',
  created_at DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 会话表 ---------------------------------------------------------------------
-- latest_seq 是该会话当前最大消息序号，消息表与水位线都以它为基准。
CREATE TABLE IF NOT EXISTS conversations (
  conv_id    BIGINT      PRIMARY KEY AUTO_INCREMENT,
  type       TINYINT     NOT NULL DEFAULT 1 COMMENT '1=单聊, 2=群聊',
  title      VARCHAR(128),
  latest_seq BIGINT      NOT NULL DEFAULT 0,
  created_at DATETIME    DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 会话成员 -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_members (
  conv_id  BIGINT NOT NULL,
  uid      BIGINT NOT NULL,
  role     TINYINT DEFAULT 0,
  joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (conv_id, uid),
  KEY idx_uid (uid)
) ENGINE=InnoDB;

-- 消息表（扩散读：每条消息只存一份）------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
  msg_id     BIGINT      PRIMARY KEY AUTO_INCREMENT,
  conv_id    BIGINT      NOT NULL,
  sender_uid BIGINT      NOT NULL,
  seq        BIGINT      NOT NULL,
  content    TEXT,
  msg_type   TINYINT     DEFAULT 1 COMMENT '1=文本 2=图片 3=文件',
  reply_to   BIGINT      DEFAULT 0 COMMENT '引用回复的消息 id',
  at_uids    VARCHAR(512) DEFAULT '' COMMENT '被 @ 的 uid，逗号分隔',
  recalled   TINYINT     DEFAULT 0 COMMENT '1=已撤回（内容置空，保留占位）',
  created_at DATETIME    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_conv_seq (conv_id, seq),
  KEY idx_conv_seq (conv_id, seq)
) ENGINE=InnoDB COMMENT='扩散读：每条消息只存一份';

-- 会话水位线（红点未读基准）--------------------------------------------------
-- 用户在该会话读到的最大 seq；未读 = conversations.latest_seq - 本表 read_seq。
CREATE TABLE IF NOT EXISTS user_conv_read (
  uid       BIGINT NOT NULL,
  conv_id   BIGINT NOT NULL,
  read_seq  BIGINT NOT NULL DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (uid, conv_id)
) ENGINE=InnoDB COMMENT='会话水位线：红点未读基准';

-- 单条已读回执明细（飞书招牌能力）--------------------------------------------
-- 记录「谁读了哪条消息」。写入压力极大（每条被读都写一行），
-- 因此 7 天外的回执明细归档到冷存储（如 HBase / COS），热表只留近期。
CREATE TABLE IF NOT EXISTS user_msg_read (
  id        BIGINT      PRIMARY KEY AUTO_INCREMENT,
  conv_id   BIGINT      NOT NULL,
  msg_id    BIGINT      NOT NULL,
  uid       BIGINT      NOT NULL,
  read_at   DATETIME    DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uniq_msg_uid (msg_id, uid),
  KEY idx_conv (conv_id)
) ENGINE=InnoDB COMMENT='单条已读回执明细；7天外归档冷存储';

-- 冷归档表（示意，生产中按时间分区 / 下沉对象存储）----------------------------
CREATE TABLE IF NOT EXISTS user_msg_read_cold (
  id        BIGINT      PRIMARY KEY,
  conv_id   BIGINT      NOT NULL,
  msg_id    BIGINT      NOT NULL,
  uid       BIGINT      NOT NULL,
  read_at   DATETIME,
  KEY idx_conv (conv_id)
) ENGINE=InnoDB COMMENT='回执冷归档（>7天）';

-- ============================================================================
-- v2：会话个性化 / 表情回应 / 附件 / 通知 / 登录态 / 组织架构
-- ============================================================================

-- 会话个性化设置（置顶 / 免打扰 / 手动标记未读）------------------------------
-- 一人一会话一行，读多写少，可整体缓存进 Redis Hash。
CREATE TABLE IF NOT EXISTS conv_settings (
  uid        BIGINT  NOT NULL,
  conv_id    BIGINT  NOT NULL,
  pinned     TINYINT DEFAULT 0 COMMENT '置顶',
  muted      TINYINT DEFAULT 0 COMMENT '免打扰（只显示小红点不显示数字）',
  marked_unread TINYINT DEFAULT 0 COMMENT '手动标记未读',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (uid, conv_id)
) ENGINE=InnoDB;

-- 表情回应（飞书气泡下方那一排）---------------------------------------------
CREATE TABLE IF NOT EXISTS reactions (
  msg_id     BIGINT      NOT NULL,
  uid        BIGINT      NOT NULL,
  emoji      VARCHAR(32) NOT NULL,
  created_at DATETIME    DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (msg_id, uid, emoji),
  KEY idx_msg (msg_id)
) ENGINE=InnoDB;

-- 附件（图片 / 文件消息）-----------------------------------------------------
CREATE TABLE IF NOT EXISTS attachments (
  id      BIGINT       PRIMARY KEY AUTO_INCREMENT,
  msg_id  BIGINT       NOT NULL,
  name    VARCHAR(255) DEFAULT '',
  mime    VARCHAR(128) DEFAULT '',
  size    BIGINT       DEFAULT 0,
  url     VARCHAR(512) DEFAULT '',
  KEY idx_msg (msg_id)
) ENGINE=InnoDB;

-- 通知中心（与业务消息分流，避免污染会话列表）--------------------------------
CREATE TABLE IF NOT EXISTS notifications (
  id         BIGINT       PRIMARY KEY AUTO_INCREMENT,
  uid        BIGINT       NOT NULL,
  ntype      VARCHAR(32)  DEFAULT '',
  title      VARCHAR(128) DEFAULT '',
  body       VARCHAR(512) DEFAULT '',
  conv_id    BIGINT       DEFAULT 0,
  msg_id     BIGINT       DEFAULT 0,
  read_at    DATETIME     NULL,
  created_at DATETIME     DEFAULT CURRENT_TIMESTAMP,
  KEY idx_uid (uid, id)
) ENGINE=InnoDB;

-- 登录态（简易 token，教学用；生产应换 JWT + 刷新令牌）-----------------------
CREATE TABLE IF NOT EXISTS sessions (
  token      VARCHAR(64) PRIMARY KEY,
  uid        BIGINT      NOT NULL,
  created_at DATETIME    DEFAULT CURRENT_TIMESTAMP,
  KEY idx_uid (uid)
) ENGINE=InnoDB;

-- 部门（组织架构树）----------------------------------------------------------
CREATE TABLE IF NOT EXISTS departments (
  dept_id   BIGINT      PRIMARY KEY,
  name      VARCHAR(64) NOT NULL,
  parent_id BIGINT      DEFAULT 0,
  sort      INT         DEFAULT 0
) ENGINE=InnoDB;
