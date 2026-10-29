package service

// 本文件承载 v2 新增能力：撤回、表情回应、正在输入、搜索、@我、
// 未读汇总、建会话、成员管理、会话设置、转发、组织架构、通知、多端已读。
//
// 设计原则不变：
//   - 写的路径仍然走 store（MySQL 是基准源），读的热路径可以走 cache。
//   - 任何非关键的附加动作（@通知、表情、撤回广播）都不阻塞消息主链路。

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/cyberspace-cs/im/internal/model"
	"github.com/cyberspace-cs/im/internal/protocol"
	"github.com/cyberspace-cs/im/internal/ws"
)

// recallWindow 撤回时限（飞书同样是 2 分钟）。
const recallWindow = 2 * time.Minute

func truncate(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n]) + "…"
}

// ---- WebSocket 侧新增动作 ----

// Recall 撤回：仅发送者本人、2 分钟内；成功后向会话成员广播 recall 事件。
func (s *Service) Recall(c *ws.Client, req protocol.RecallReq) {
	ctx := context.Background()
	if req.MsgID == 0 {
		return
	}
	m, err := s.store.RecallMessage(ctx, req.MsgID, c.UID, recallWindow)
	if err != nil {
		s.sendSelf(c, protocol.TypeError, map[string]string{"msg": err.Error()})
		return
	}
	convID := req.ConvID
	if convID == 0 {
		convID = m.ConvID
	}
	payload := map[string]interface{}{"conv_id": convID, "msg_id": req.MsgID}
	s.sendSelf(c, protocol.TypeRecall, payload)
	members, _ := s.store.GetMembers(ctx, convID)
	for _, uid := range members {
		if uid == c.UID {
			continue
		}
		s.sendTo(uid, protocol.TypeRecall, payload)
	}
}

// React 表情回应：同一个人再点一次即取消，返回该消息最新聚合。
func (s *Service) React(c *ws.Client, req protocol.ReactionReq) {
	ctx := context.Background()
	if req.MsgID == 0 || req.Emoji == "" {
		return
	}
	agg, err := s.store.ToggleReaction(ctx, req.MsgID, c.UID, req.Emoji)
	if err != nil {
		s.sendSelf(c, protocol.TypeError, map[string]string{"msg": err.Error()})
		return
	}
	convID := req.ConvID
	payload := map[string]interface{}{"conv_id": convID, "msg_id": req.MsgID, "reactions": agg}
	s.sendSelf(c, protocol.TypeReaction, payload)
	members, _ := s.store.GetMembers(ctx, convID)
	for _, uid := range members {
		if uid == c.UID {
			continue
		}
		s.sendTo(uid, protocol.TypeReaction, payload)
	}
}

// Typing 正在输入：不落库、不重试，丢了也无所谓的高频小包。
func (s *Service) Typing(c *ws.Client, req protocol.TypingReq) {
	if req.ConvID == 0 {
		return
	}
	members, _ := s.store.GetMembers(context.Background(), req.ConvID)
	for _, uid := range members {
		if uid == c.UID {
			continue
		}
		s.sendTo(uid, protocol.TypeTypingEv, map[string]interface{}{
			"conv_id": req.ConvID, "uid": c.UID,
		})
	}
}

// ---- REST 侧新增能力 ----

// UnreadSummary 未读汇总：一次聚合出「总未读 / 有未读会话数 / @我 / 单聊 / 群聊」。
// 全部由水位线相减得出，不扫消息表（@我 那一条才需要扫未读区间）。
func (s *Service) UnreadSummary(uid int64) (model.UnreadSummary, error) {
	return s.store.UnreadSummary(context.Background(), uid)
}

// ListConversationsV2 会话列表（带置顶 / 免打扰 / @我）。
func (s *Service) ListConversationsV2(uid int64) ([]model.ConversationView, error) {
	return s.store.ListConversationsV2(context.Background(), uid, s.cfg.BigGroupThreshold)
}

// Search 全局搜索：消息 / 联系人 / 会话三路合并。
func (s *Service) Search(uid int64, q, scope string, convID int64) ([]model.SearchHit, error) {
	ctx := context.Background()
	q = strings.TrimSpace(q)
	if q == "" {
		return nil, nil
	}
	var hits []model.SearchHit
	if scope == "" || scope == "message" {
		m, err := s.store.SearchMessages(ctx, uid, convID, q, 20)
		if err != nil {
			return nil, err
		}
		hits = append(hits, m...)
	}
	if scope == "" || scope == "user" {
		us, err := s.store.SearchUsers(ctx, q, 8)
		if err != nil {
			return nil, err
		}
		for _, u := range us {
			hits = append(hits, model.SearchHit{
				Kind: "user", ID: u.UID, UID: u.UID,
				Title: u.Name, Snippet: u.Dept + " · " + u.DeptTitle,
			})
		}
	}
	if scope == "" || scope == "conv" {
		cs, err := s.store.SearchConvs(ctx, uid, q, 8)
		if err != nil {
			return nil, err
		}
		for _, c := range cs {
			hits = append(hits, model.SearchHit{
				Kind: "conv", ID: c.ConvID, ConvID: c.ConvID,
				Title: c.Title, Snippet: fmt.Sprintf("%d 人", c.MemberCnt),
			})
		}
	}
	return hits, nil
}

// Mentions 拉「@我」的消息列表。
func (s *Service) Mentions(uid int64) ([]model.Message, error) {
	return s.store.MentionMessages(context.Background(), uid, 30)
}

// CreateConversation 建单聊 / 群聊，并把创建者一并加入。
func (s *Service) CreateConversation(uid int64, convType int, title string, members []int64) (int64, error) {
	if convType != 1 && convType != 2 {
		convType = 2
	}
	all := []int64{uid}
	for _, m := range members {
		if m != uid {
			all = append(all, m)
		}
	}
	if convType == 1 && len(all) < 2 {
		return 0, fmt.Errorf("单聊需要至少两个成员")
	}
	if convType == 1 {
		// 单聊：如果两人之间已有单聊，直接复用
		if exist := s.store.FindP2P(context.Background(), all[0], all[1]); exist > 0 {
			return exist, nil
		}
		if title == "" {
			u, _ := s.store.GetUser(context.Background(), all[1])
			title = u.Name
		}
	}
	return s.store.CreateConversation(context.Background(), convType, title, all)
}

// AddMembers 拉人入群（并发一条系统消息，让群里知道）。
func (s *Service) AddMembers(operator, convID int64, uids []int64) error {
	ctx := context.Background()
	if !s.store.IsMember(ctx, convID, operator) {
		return fmt.Errorf("不在该会话中")
	}
	if err := s.store.AddMembers(ctx, convID, uids); err != nil {
		return err
	}
	names := make([]string, 0, len(uids))
	for _, u := range uids {
		if usr, err := s.store.GetUser(ctx, u); err == nil {
			names = append(names, usr.Name)
		}
	}
	if len(names) > 0 {
		msgID, seq, err := s.store.InsertMessage(ctx, convID, operator,
			strings.Join(names, "、")+" 加入了群聊", 1)
		if err == nil {
			msg := model.Message{MsgID: msgID, ConvID: convID, SenderUID: operator,
				Seq: seq, Content: strings.Join(names, "、") + " 加入了群聊", Type: 1, CreatedAt: time.Now()}
			s.cache.SetLatestSeq(ctx, convID, seq)
			members, _ := s.store.GetMembers(ctx, convID)
			for _, m := range members {
				if m != operator {
					s.sendTo(m, protocol.TypeMessage, msg)
				}
			}
		}
	}
	return nil
}

// RemoveMember 退群 / 踢人。
func (s *Service) RemoveMember(operator, convID, target int64) error {
	ctx := context.Background()
	if operator != target && !s.store.IsMember(ctx, convID, operator) {
		return fmt.Errorf("不在该会话中")
	}
	if err := s.store.RemoveMember(ctx, convID, target); err != nil {
		return err
	}
	u, _ := s.store.GetUser(ctx, target)
	msgID, seq, err := s.store.InsertMessage(ctx, convID, target, u.Name+" 退出了群聊", 1)
	if err == nil {
		msg := model.Message{MsgID: msgID, ConvID: convID, SenderUID: target,
			Seq: seq, Content: u.Name + " 退出了群聊", Type: 1, CreatedAt: time.Now()}
		s.cache.SetLatestSeq(ctx, convID, seq)
		members, _ := s.store.GetMembers(ctx, convID)
		for _, m := range members {
			s.sendTo(m, protocol.TypeMessage, msg)
		}
	}
	return nil
}

// SetConvSetting 置顶 / 免打扰 / 标记未读。
func (s *Service) SetConvSetting(uid, convID int64, fields map[string]bool) error {
	ctx := context.Background()
	for k, v := range fields {
		if err := s.store.SetConvSetting(ctx, uid, convID, k, v); err != nil {
			return err
		}
	}
	return nil
}

// Forward 转发：把源消息内容复制到目标会话（不做引用链，飞书合并转发另说）。
func (s *Service) Forward(uid int64, msgID int64, toConvIDs []int64) ([]int64, error) {
	ctx := context.Background()
	src, err := s.store.GetMessageByID(ctx, msgID)
	if err != nil {
		return nil, err
	}
	var out []int64
	for _, to := range toConvIDs {
		if !s.store.IsMember(ctx, to, uid) {
			continue
		}
		newID, seq, err := s.store.InsertMessageFull(ctx, to, uid, src.Content, src.Type, 0, nil)
		if err != nil {
			continue
		}
		msg := model.Message{MsgID: newID, ConvID: to, SenderUID: uid, Seq: seq,
			Content: src.Content, Type: src.Type, CreatedAt: time.Now()}
		s.cache.SetLatestSeq(ctx, to, seq)
		members, _ := s.store.GetMembers(ctx, to)
		for _, m := range members {
			if m != uid {
				s.sendTo(m, protocol.TypeMessage, msg)
			}
		}
		out = append(out, newID)
	}
	return out, nil
}

// User 用户名片。
func (s *Service) User(uid int64) (model.User, error) {
	return s.store.GetUser(context.Background(), uid)
}

// OrgTree 组织架构：部门 + 每个部门的成员。
func (s *Service) OrgTree() ([]model.Dept, error) {
	ctx := context.Background()
	depts, err := s.store.ListDepts(ctx)
	if err != nil {
		return nil, err
	}
	for i := range depts {
		ms, err := s.store.ListDeptMembers(ctx, depts[i].DeptID)
		if err == nil {
			depts[i].Members = ms
		}
	}
	return depts, nil
}

// Notifications 通知中心。
func (s *Service) Notifications(uid int64) ([]model.Notification, error) {
	return s.store.ListNotifications(context.Background(), uid, 50)
}

// MarkNotificationsRead 一键已读。
func (s *Service) MarkNotificationsRead(uid int64) error {
	return s.store.MarkNotificationsRead(context.Background(), uid)
}

// ReadStates 多端已读位置同步。
func (s *Service) ReadStates(uid int64) (map[int64]int64, error) {
	return s.store.ReadStates(context.Background(), uid)
}

// OnlineMembers 某会话当前在线成员（presence）。
func (s *Service) OnlineMembers(convID int64) ([]int64, error) {
	ctx := context.Background()
	members, err := s.store.GetMembers(ctx, convID)
	if err != nil {
		return nil, err
	}
	out := make([]int64, 0, len(members))
	for _, m := range members {
		if s.cache.IsOnline(ctx, m) {
			out = append(out, m)
		}
	}
	return out, nil
}

// LoginToken 签发 token（教学用：随机 32 字节 hex，落 MySQL sessions）。
func (s *Service) LoginToken(uid int64, token string) error {
	return s.store.CreateSession(context.Background(), token, uid)
}

// UIDByToken 校验 token。
func (s *Service) UIDByToken(token string) (int64, error) {
	return s.store.UIDByToken(context.Background(), token)
}

// Logout 注销 token。
func (s *Service) Logout(token string) error {
	return s.store.DeleteSession(context.Background(), token)
}

// SeedOrg 初始化组织架构（部门 + 职位/邮箱）。
func (s *Service) SeedOrg() error {
	return s.store.SeedOrg(context.Background())
}

// SearchUsers 按姓名 / 部门搜人。
func (s *Service) SearchUsers(q string) ([]model.User, error) {
	return s.store.SearchUsers(context.Background(), q, 20)
}

// decorate 批量装配引用块、表情回应、附件，避免前端渲染时 N+1 拉取。
func (s *Service) decorate(ctx context.Context, msgs []model.Message, meUID int64) {
	if len(msgs) == 0 {
		return
	}
	ids := make([]int64, 0, len(msgs))
	qids := make([]int64, 0, 4)
	for _, m := range msgs {
		ids = append(ids, m.MsgID)
		if m.ReplyTo > 0 {
			qids = append(qids, m.ReplyTo)
		}
	}
	atts, _ := s.store.ListAttachments(ctx, ids)
	reacts := s.store.ListReactionsBatch(ctx, ids, meUID)
	qmap := s.store.GetMessagesByIDs(ctx, qids)
	for i := range msgs {
		if a, ok := atts[msgs[i].MsgID]; ok {
			msgs[i].Files = a
		}
		if r, ok := reacts[msgs[i].MsgID]; ok {
			msgs[i].Reactions = r
		}
		if msgs[i].ReplyTo > 0 {
			if q, ok := qmap[msgs[i].ReplyTo]; ok {
				msgs[i].Quote = &model.Quote{MsgID: q.MsgID, SenderUID: q.SenderUID, Content: q.Content}
			}
		}
	}
}

// PullAfter 增量拉取：断线重连 / 多端同步时只补 seq 之后的消息。
func (s *Service) PullAfter(convID, afterSeq int64, limit int) ([]model.Message, error) {
	ctx := context.Background()
	msgs, err := s.store.ListMessagesAfter(ctx, convID, afterSeq, limit)
	if err == nil {
		s.decorate(ctx, msgs, 0)
	}
	return msgs, err
}

// RecallByREST REST 版撤回（WS 之外的备用入口，同样广播给成员）。
func (s *Service) RecallByREST(uid, convID, msgID int64) error {
	ctx := context.Background()
	m, err := s.store.RecallMessage(ctx, msgID, uid, recallWindow)
	if err != nil {
		return err
	}
	if convID == 0 {
		convID = m.ConvID
	}
	payload := map[string]interface{}{"conv_id": convID, "msg_id": msgID}
	members, _ := s.store.GetMembers(ctx, convID)
	for _, u := range members {
		s.sendTo(u, protocol.TypeRecall, payload)
	}
	return nil
}

// ReactByREST REST 版表情回应。
func (s *Service) ReactByREST(uid, convID, msgID int64, emoji string) ([]model.Reaction, error) {
	ctx := context.Background()
	agg, err := s.store.ToggleReaction(ctx, msgID, uid, emoji)
	if err != nil {
		return nil, err
	}
	if convID == 0 {
		if m, e := s.store.GetMessageByID(ctx, msgID); e == nil {
			convID = m.ConvID
		}
	}
	payload := map[string]interface{}{"conv_id": convID, "msg_id": msgID, "reactions": agg}
	members, _ := s.store.GetMembers(ctx, convID)
	for _, u := range members {
		s.sendTo(u, protocol.TypeReaction, payload)
	}
	return agg, nil
}
