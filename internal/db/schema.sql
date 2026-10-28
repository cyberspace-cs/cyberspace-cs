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
  uid      BIGINT       PRIMARY KEY,
  name     VARCHAR(64)  NOT NULL,
  avatar   VARCHAR(256),
  created_at DATETIME   DEFAULT CURRENT_TIMESTAMP
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
  msg_type   TINYINT     DEFAULT 1,
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
