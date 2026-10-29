// Package model 定义 IM 系统的领域模型。
//
// 飞书 / 钉钉 B 端 IM 的两套核心语义：
//  1. 会话未读红点  -> 水位线（read_seq）：用户在该会话读到的最大 seq。
//  2. 单条已读回执  -> 每条消息各自记录「谁读了」（Feishu 招牌能力）。
package model

import "time"

// User 用户。
type User struct {
	UID       int64  `json:"uid"`
	Name      string `json:"name"`
	Avatar    string `json:"avatar,omitempty"`
	Dept      string `json:"dept,omitempty"`
	DeptID    int64  `json:"dept_id,omitempty"`
	DeptTitle string `json:"dept_title,omitempty"`
	Email     string `json:"email,omitempty"`
	Phone     string `json:"phone,omitempty"`
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
	Type      int       `json:"type"` // 1=文本 2=图片 3=文件
	ReplyTo   int64     `json:"reply_to,omitempty"`
	AtUIDs    []int64   `json:"at_uids,omitempty"`
	Recalled  bool      `json:"recalled,omitempty"`
	CreatedAt time.Time `json:"created_at"`

	// 以下为读取时装配的展示字段（不落库）
	Quote     *Quote       `json:"quote,omitempty"`      // 引用回复的原消息摘要
	Reactions []Reaction   `json:"reactions,omitempty"`  // 表情回应聚合
	Files     []Attachment `json:"files,omitempty"`      // 附件
}

// Quote 引用回复的原消息摘要（只带展示所需的三个字段）。
type Quote struct {
	MsgID     int64  `json:"msg_id"`
	SenderUID int64  `json:"sender_uid"`
	Content   string `json:"content"`
}

// Reaction 表情回应聚合。
type Reaction struct {
	Emoji string  `json:"emoji"`
	Count int     `json:"count"`
	Uids  []int64 `json:"uids,omitempty"`
	Mine  bool    `json:"mine,omitempty"`
}

// Attachment 附件。
type Attachment struct {
	Name string `json:"name"`
	Mime string `json:"mime"`
	Size int64  `json:"size"`
	URL  string `json:"url"`
}

// ConversationView 带某个用户的未读水位线视图（用于会话列表红点）。
type ConversationView struct {
	Conversation
	ReadSeq       int64  `json:"read_seq"`        // 用户已读到的 seq
	Unread        int64  `json:"unread"`          // latest_seq - read_seq
	IsBig         bool   `json:"is_big"`          // 超大群降级：不维护精确离线缓冲
	LastContent   string `json:"last_content"`    // 最近一条消息预览
	LastSenderUID int64  `json:"last_sender_uid"` // 最近一条消息发送者
	LastAt        time.Time `json:"last_at"`      // 最近活跃时间（列表时间戳）
	AtMe          bool   `json:"at_me"`           // 最近消息是否 @我
	Pinned        bool   `json:"pinned"`          // 置顶
	Muted         bool   `json:"muted"`           // 免打扰
	MarkedUnread  bool   `json:"marked_unread"`   // 手动标记未读
}

// Receipt 单条消息已读回执快照（飞书式）。
type Receipt struct {
	ConvID    int64   `json:"conv_id"`
	MsgID     int64   `json:"msg_id"`
	Readers   []int64 `json:"readers"`    // 已读 uid 列表（头像展示用）
	ReadCount int64   `json:"read_count"` // 已读人数
	Total     int64   `json:"total"`      // 应读人数（群成员数，不含发送者）
	IsBig     bool    `json:"is_big"`
	Offset    int     `json:"offset"`
	Limit     int     `json:"limit"`
}

// UnreadSummary 未读汇总（对应飞书左侧图标红点与会话列表 tab）。
type UnreadSummary struct {
	Total      int64 `json:"total"`       // 所有会话未读之和
	ConvUnread int   `json:"conv_unread"` // 有未读的会话数
	AtMe       int   `json:"at_me"`       // 被 @ 且未读的条数
	P2P        int   `json:"p2p"`         // 单聊未读
	Group      int   `json:"group"`       // 群聊未读
}

// Dept 部门节点（组织架构树）。
type Dept struct {
	DeptID   int64  `json:"dept_id"`
	Name     string `json:"name"`
	ParentID int64  `json:"parent_id"`
	Sort     int    `json:"sort"`
	Count    int    `json:"count"`
	Members  []User `json:"members,omitempty"`
}

// Notification 通知中心条目。
type Notification struct {
	ID        int64     `json:"id"`
	Type      string    `json:"type"`
	Title     string    `json:"title"`
	Body      string    `json:"body"`
	ConvID    int64     `json:"conv_id,omitempty"`
	MsgID     int64     `json:"msg_id,omitempty"`
	Read      bool      `json:"read"`
	CreatedAt time.Time `json:"created_at"`
}

// SearchHit 全局搜索结果（消息 / 联系人 / 会话统一结构）。
type SearchHit struct {
	Kind    string `json:"kind"` // message | user | conv
	ID      int64  `json:"id"`
	Title   string `json:"title"`
	Snippet string `json:"snippet"`
	ConvID  int64  `json:"conv_id,omitempty"`
	UID     int64  `json:"uid,omitempty"`
	Seq     int64  `json:"seq,omitempty"`
}
