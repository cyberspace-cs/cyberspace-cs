// Package model 定义 IM 系统的领域模型。
//
// 飞书 / 钉钉 B 端 IM 的两套核心语义：
//  1. 会话未读红点  -> 水位线（read_seq）：用户在该会话读到的最大 seq。
//  2. 单条已读回执  -> 每条消息各自记录「谁读了」（Feishu 招牌能力）。
package model

import "time"

// User 用户。
type User struct {
	UID   int64  `json:"uid"`
	Name  string `json:"name"`
	Avatar string `json:"avatar,omitempty"`
}

// Conversation 会话（1=单聊，2=群聊）。
// LatestSeq 是该会话当前最大消息序号，消息表与水位线都以它为基准。
type Conversation struct {
	ConvID    int64     `json:"conv_id"`
	Type      int       `json:"type"`
	Title     string    `json:"title,omitempty"`
	LatestSeq int64     `json:"latest_seq"`
	MemberCnt int       `json:"member_cnt"`
	CreatedAt time.Time `json:"created_at"`
}

// Message 消息。扩散读：每条消息只存一份（conv_id, seq 唯一）。
type Message struct {
	MsgID     int64     `json:"msg_id"`
	ConvID    int64     `json:"conv_id"`
	SenderUID int64     `json:"sender_uid"`
	Seq       int64     `json:"seq"`
	Content   string    `json:"content"`
	Type      int       `json:"type"` // 1=文本
	CreatedAt time.Time `json:"created_at"`
}

// ConversationView 带某个用户的未读水位线视图（用于会话列表红点）。
type ConversationView struct {
	Conversation
	ReadSeq int64 `json:"read_seq"` // 用户已读到的 seq
	Unread  int64 `json:"unread"`   // latest_seq - read_seq
	IsBig   bool  `json:"is_big"`   // 超大群降级：不维护精确离线缓冲
}

// Receipt 单条消息已读回执快照（飞书式）。
type Receipt struct {
	ConvID    int64   `json:"conv_id"`
	MsgID     int64   `json:"msg_id"`
	Readers   []int64 `json:"readers"`    // 已读 uid 列表（头像展示用）
	ReadCount int64   `json:"read_count"` // 已读人数
	Total     int64   `json:"total"`      // 应读人数（群成员数，不含发送者）
	IsBig     bool    `json:"is_big"`
}
