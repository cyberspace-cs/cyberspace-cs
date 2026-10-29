// Package protocol 定义 WebSocket 的 JSON 通信协议。
//
// 设计目标：协议与业务解耦，客户端只用一套 JSON 信封（Envelope）收发，
// 通过 type 字段区分动作。这样前端可以很薄，专注渲染。
package protocol

import "encoding/json"

// ---- 客户端 -> 服务端 ----
const (
	TypeLogin  = "login"  // 登录（绑定 uid 到本连接）
	TypeSend   = "send"   // 发消息
	TypeRead   = "read"   // 标记已读（读到某 seq，触发回执）
	TypeSync   = "sync"   // 拉取历史（扩散读：直接从消息表按 seq 拉）
	TypePing   = "ping"
	TypeTyping = "typing" // 正在输入（不落库，只转发）
)

// ---- 服务端 -> 客户端 ----
const (
	TypeWelcome  = "welcome"  // 登录成功
	TypeAck      = "ack"      // 发消息落库确认（带回 seq / msg_id）
	TypeMessage  = "message"  // 新消息推送
	TypeUnread   = "unread"   // 未读水位线更新（红点）
	TypeReceipt  = "receipt"  // 单条消息已读回执更新（飞书招牌）
	TypePong     = "pong"
	TypeError    = "error"
	TypeRecall   = "recall"   // 消息已撤回
	TypeReaction = "reaction" // 表情回应变化
	TypeTypingEv = "typing"   // 对方正在输入
	TypePresence = "presence" // 在线状态变化
	TypeNotify   = "notify"   // 通知中心新条目
)

// Envelope 统一信封。
type Envelope struct {
	Type string          `json:"type"`
	Data json.RawMessage `json:"data,omitempty"`
}

// LoginReq 登录请求。教学项目省略真实鉴权，仅绑定 uid。
type LoginReq struct {
	UID   int64  `json:"uid"`
	Token string `json:"token,omitempty"`
}

// SendReq 发消息。
type SendReq struct {
	ClientID string    `json:"client_id,omitempty"` // 客户端临时 id，用于回 ack 对应
	ConvID   int64     `json:"conv_id"`
	Content  string    `json:"content"`
	Type     int       `json:"type"` // 默认 1=文本 2=图片 3=文件
	ReplyTo  int64     `json:"reply_to,omitempty"`
	AtUIDs   []int64   `json:"at_uids,omitempty"`
	Files    []FileRef `json:"files,omitempty"`
}

// FileRef 附件引用（先走 /api/upload 拿到 url，再随消息发出）。
type FileRef struct {
	Name string `json:"name"`
	Mime string `json:"mime"`
	Size int64  `json:"size"`
	URL  string `json:"url"`
}

// RecallReq 撤回消息。
type RecallReq struct {
	ConvID int64 `json:"conv_id"`
	MsgID  int64 `json:"msg_id"`
}

// ReactionReq 表情回应（同一人对同一条消息同一表情再点一次 = 取消）。
type ReactionReq struct {
	ConvID int64  `json:"conv_id"`
	MsgID  int64  `json:"msg_id"`
	Emoji  string `json:"emoji"`
}

// TypingReq 「正在输入」。
type TypingReq struct {
	ConvID int64 `json:"conv_id"`
}

// ReadReq 标记已读：把该会话自己的水位线推进到 seq。
// 服务端据此把 [oldReadSeq+1, seq] 区间内每条消息的读者集合加入自己。
type ReadReq struct {
	ConvID int64 `json:"conv_id"`
	Seq    int64 `json:"seq"`
}

// SyncReq 拉取历史。
type SyncReq struct {
	ConvID    int64 `json:"conv_id"`
	BeforeSeq int64 `json:"before_seq"` // 游标：拉取 seq <= before_seq 的消息
	Limit     int   `json:"limit"`
}

func Encode(typ string, data interface{}) ([]byte, error) {
	payload, err := json.Marshal(data)
	if err != nil {
		return nil, err
	}
	return json.Marshal(Envelope{Type: typ, Data: payload})
}
