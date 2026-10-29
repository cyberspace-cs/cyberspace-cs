// Package service 实现 IM 业务逻辑，是「MySQL + Redis」如何协作的核心。
//
// 飞书 / 钉钉 B 端 IM 的关键设计都在这里落地：
//  1. 发消息：MySQL 事务分配 seq（单副本扩散读），Redis 更新 latest_seq 水位线，
//     再经 Pub/Sub 把消息推给在线成员；离线成员写入离线消息环。
//  2. 已读（飞书招牌）：推进「会话水位线」让红点消失；同时把 uid 写进
//     每条消息的读者集合（Redis Set + Bitmap），并把回执推给消息发送者。
//  3. 回执降级：超大群 / 降级开关开启时，只推进水位线、不维护单条回执，
//     优先保住消息收发主链路（对应大厂「高峰期回执可降级」）。
package service

import (
	"context"
	"encoding/json"
	"time"

	"github.com/cyberspace-cs/im/internal/config"
	"github.com/cyberspace-cs/im/internal/db"
	"github.com/cyberspace-cs/im/internal/model"
	"github.com/cyberspace-cs/im/internal/protocol"
	"github.com/cyberspace-cs/im/internal/ws"
)

// 单次「已读」最多给最近多少条消息写回执，避免一次性读 1000 条导致写放大。
const maxReceiptsPerRead = 50

// Service 业务编排：组合 store / cache / hub。
type Service struct {
	store *db.Store
	cache *db.Cache
	hub   *ws.Hub
	cfg   *config.Config
}

func New(store *db.Store, cache *db.Cache, hub *ws.Hub, cfg *config.Config) *Service {
	return &Service{store: store, cache: cache, hub: hub, cfg: cfg}
}

// Hub 暴露给 HTTP 层做 WebSocket 升级。
func (s *Service) Hub() *ws.Hub { return s.hub }

// ---- 推送辅助 ----

// sendSelf 直接发往本连接（不依赖 hub 路由，避免登录瞬间还没入网的竞态）。
func (s *Service) sendSelf(c *ws.Client, typ string, data interface{}) {
	b, err := protocol.Encode(typ, data)
	if err != nil {
		return
	}
	c.Send(b)
}

// sendTo 经 Redis Pub/Sub 投递给指定 uid（跨节点可达）。
func (s *Service) sendTo(uid int64, typ string, data interface{}) {
	b, err := protocol.Encode(typ, data)
	if err != nil {
		return
	}
	s.hub.Deliver(uid, b)
}

// ---- WebSocket 消息入口（实现 ws.MessageHandler） ----

func (s *Service) Handle(c *ws.Client, payload []byte) {
	var env protocol.Envelope
	if err := json.Unmarshal(payload, &env); err != nil {
		return
	}
	switch env.Type {
	case protocol.TypeLogin:
		var r protocol.LoginReq
		if json.Unmarshal(env.Data, &r) == nil && r.UID != 0 {
			s.Login(c, r)
		}
		return
	}
	// 其余消息必须已登录
	if c.UID == 0 {
		return
	}
	switch env.Type {
	case protocol.TypeSend:
		var r protocol.SendReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.Send(c, r)
		}
	case protocol.TypeRead:
		var r protocol.ReadReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.Read(c, r)
		}
	case protocol.TypeSync:
		var r protocol.SyncReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.Sync(c, r)
		}
	case protocol.TypeRecall:
		var r protocol.RecallReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.Recall(c, r)
		}
	case protocol.TypeReaction:
		var r protocol.ReactionReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.React(c, r)
		}
	case protocol.TypeTyping:
		var r protocol.TypingReq
		if json.Unmarshal(env.Data, &r) == nil {
			s.Typing(c, r)
		}
	case protocol.TypePing:
		s.sendSelf(c, protocol.TypePong, nil)
	}
}

// ---- 业务方法 ----

// Login 绑定 uid，补推离线消息与未读水位线。
func (s *Service) Login(c *ws.Client, req protocol.LoginReq) {
	ctx := context.Background()
	c.UID = req.UID
	c.Register(s.hub) // 登录确定 uid 后才入网（订阅频道 + 登记网关）
	s.sendSelf(c, protocol.TypeWelcome, WelcomeData{UID: req.UID})

	convs, err := s.store.ListConversationsForUser(ctx, req.UID, s.cfg.BigGroupThreshold)
	if err != nil {
		return
	}
	for _, cv := range convs {
		ids, _ := s.cache.PopOffline(ctx, req.UID, cv.ConvID)
		for _, mid := range ids {
			if msg, e := s.store.GetMessage(ctx, cv.ConvID, mid); e == nil {
				s.sendSelf(c, protocol.TypeMessage, msg)
			}
		}
		unread := cv.LatestSeq - cv.ReadSeq
		if unread < 0 {
			unread = 0
		}
		s.sendSelf(c, protocol.TypeUnread, UnreadData{
			ConvID: cv.ConvID, Unread: unread, LatestSeq: cv.LatestSeq, ReadSeq: cv.ReadSeq,
		})
	}
}

// Send 发消息：落库分配 seq -> 更新水位线 -> 推送给成员（在线走 pubsub / 离线走消息环）。
func (s *Service) Send(c *ws.Client, req protocol.SendReq) {
	ctx := context.Background()
	uid, convID := c.UID, req.ConvID
	if convID == 0 {
		s.sendSelf(c, protocol.TypeError, map[string]string{"msg": "conv_id required"})
		return
	}
	msgType := req.Type
	if msgType == 0 {
		msgType = 1
	}
	msgID, seq, err := s.store.InsertMessageFull(ctx, convID, uid, req.Content, msgType, req.ReplyTo, req.AtUIDs)
	if err != nil {
		s.sendSelf(c, protocol.TypeError, map[string]string{"msg": err.Error()})
		return
	}
	msg := model.Message{
		MsgID: msgID, ConvID: convID, SenderUID: uid, Seq: seq,
		Content: req.Content, Type: msgType, ReplyTo: req.ReplyTo,
		AtUIDs: req.AtUIDs, CreatedAt: time.Now(),
	}
	// 引用回复：装配被引消息摘要，接收方直接渲染引用块
	if req.ReplyTo > 0 {
		if q, e := s.store.GetMessageByID(ctx, req.ReplyTo); e == nil {
			msg.Quote = &model.Quote{MsgID: q.MsgID, SenderUID: q.SenderUID, Content: q.Content}
		}
	}
	// 附件：先落库再随消息体推给接收方
	for _, f := range req.Files {
		_ = s.store.AddAttachment(ctx, msgID, model.Attachment{Name: f.Name, Mime: f.Mime, Size: f.Size, URL: f.URL})
		msg.Files = append(msg.Files, model.Attachment{Name: f.Name, Mime: f.Mime, Size: f.Size, URL: f.URL})
	}
	// 热点水位线（旁路缓存）
	s.cache.SetLatestSeq(ctx, convID, seq)

	// 给发送者回 ack（携带完整消息，前端据此渲染自己的气泡）
	s.sendSelf(c, protocol.TypeAck, AckData{ClientID: req.ClientID, Message: msg})

	// 扩散读：同一份消息推给每位成员
	members, _ := s.store.GetMembers(ctx, convID)
	for _, m := range members {
		if m == uid {
			continue
		}
		if s.cache.IsOnline(ctx, m) {
			s.sendTo(m, protocol.TypeMessage, msg)
		} else {
			s.cache.PushOffline(ctx, m, convID, msgID) // 离线消息环（RingBuffer）
		}
	}
	// @提及：给被 @ 的人落一条通知（与业务消息分流）
	for _, at := range req.AtUIDs {
		if at == uid {
			continue
		}
		_ = s.store.AddNotification(ctx, at, model.Notification{
			Type: "mention", Title: "有人 @ 了你",
			Body: truncate(req.Content, 60), ConvID: convID, MsgID: msgID,
		})
	}
}

// Read 标记已读：推进水位线（红点消失）+ 为区间内每条消息写「单条已读回执」。
func (s *Service) Read(c *ws.Client, req protocol.ReadReq) {
	ctx := context.Background()
	uid, convID := c.UID, req.ConvID

	oldRead := s.cache.GetReadSeq(ctx, uid, convID)
	if oldRead == 0 {
		oldRead, _ = s.store.GetReadSeq(ctx, uid, convID)
	}
	if req.Seq <= oldRead {
		return // 已读过，丢弃
	}

	// 1) 推进会话水位线（红点基准）
	s.store.SetReadSeq(ctx, uid, convID, req.Seq)
	s.cache.SetReadSeq(ctx, uid, convID, req.Seq)
	latest := s.cache.GetLatestSeq(ctx, convID)
	if latest == 0 {
		latest, _ = s.store.GetLatestSeq(ctx, convID)
	}
	unread := latest - req.Seq
	if unread < 0 {
		unread = 0
	}
	s.sendSelf(c, protocol.TypeUnread, UnreadData{
		ConvID: convID, Unread: unread, LatestSeq: latest, ReadSeq: req.Seq,
	})

	// 2) 单条已读回执（飞书招牌），带降级保护
	memberCount, _ := s.store.CountMembers(ctx, convID)
	isBig := s.cfg.BigGroupThreshold > 0 && memberCount > s.cfg.BigGroupThreshold
	if s.cfg.ReceiptDegrade || isBig {
		// 降级：不维护精确单条回执，只推进水位线，优先保主链路
		return
	}

	lo := oldRead + 1
	hi := req.Seq
	count := hi - lo + 1
	if count > maxReceiptsPerRead { // 防写放大：只给最近 N 条写回执
		lo = hi - maxReceiptsPerRead + 1
	}
	msgs, err := s.store.MessagesInRange(ctx, convID, lo, hi)
	if err != nil {
		return
	}
	total := memberCount - 1 // 应读人数（不含发送者）
	for _, m := range msgs {
		if m.SenderUID == uid {
			continue // 自己的消息无需自己回执
		}
		readers, rc, _ := s.cache.MarkReader(ctx, m.MsgID, convID, uid)
		_ = s.store.InsertMsgRead(ctx, convID, m.MsgID, uid) // 落库审计 / 7天归档
		s.sendTo(m.SenderUID, protocol.TypeReceipt, model.Receipt{
			ConvID: convID, MsgID: m.MsgID, Readers: readers,
			ReadCount: rc, Total: int64(total), IsBig: isBig,
		})
	}
}

// Sync 拉取历史（扩散读：按 seq 直接从消息表拉）。
func (s *Service) Sync(c *ws.Client, req protocol.SyncReq) {
	limit := req.Limit
	if limit <= 0 {
		limit = 50
	}
	msgs, err := s.store.ListMessages(context.Background(), req.ConvID, req.BeforeSeq, limit)
	if err != nil {
		return
	}
	for i := len(msgs) - 1; i >= 0; i-- { // 倒序取出，正序推给前端
		s.sendSelf(c, protocol.TypeMessage, msgs[i])
	}
}

// ---- REST 用方法 ----

func (s *Service) ListConversations(uid int64) ([]model.ConversationView, error) {
	return s.store.ListConversationsForUser(context.Background(), uid, s.cfg.BigGroupThreshold)
}

func (s *Service) ListUsers() ([]model.User, error) {
	return s.store.ListUsers(context.Background())
}

func (s *Service) ListMembers(convID int64) ([]model.User, error) {
	return s.store.ListConvMembers(context.Background(), convID)
}

func (s *Service) PullHistory(convID, beforeSeq int64, limit int) ([]model.Message, error) {
	ctx := context.Background()
	msgs, err := s.store.ListMessages(ctx, convID, beforeSeq, limit)
	if err == nil {
		s.decorate(ctx, msgs, 0) // 装配引用块 / 表情 / 附件
	}
	return msgs, err
}

func (s *Service) Receipt(convID, msgID int64) (model.Receipt, error) {
	readers, count, _ := s.cache.GetReaders(context.Background(), msgID)
	memberCount, _ := s.store.CountMembers(context.Background(), convID)
	total := memberCount - 1
	if total < 0 {
		total = 0
	}
	return model.Receipt{
		ConvID: convID, MsgID: msgID, Readers: readers,
		ReadCount: count, Total: int64(total),
	}, nil
}

func (s *Service) Seed() (int64, int64, error) {
	return s.store.SeedDemo(context.Background())
}

func (s *Service) SeedBig(n int) (int64, error) {
	return s.store.SeedBig(context.Background(), n)
}

// ---- 推送载荷结构 ----

type WelcomeData struct {
	UID int64 `json:"uid"`
}

type AckData struct {
	ClientID string        `json:"client_id,omitempty"`
	Message  model.Message `json:"message"`
}

type UnreadData struct {
	ConvID    int64 `json:"conv_id"`
	Unread    int64 `json:"unread"`
	LatestSeq int64 `json:"latest_seq"`
	ReadSeq   int64 `json:"read_seq"`
}
