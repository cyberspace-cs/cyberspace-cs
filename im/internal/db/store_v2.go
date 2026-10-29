package db

import (
	"context"
	"database/sql"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/cyberspace-cs/im/internal/model"
)

// ---- 消息字段编解码 ----

func joinUIDs(ids []int64) string {
	if len(ids) == 0 {
		return ""
	}
	parts := make([]string, 0, len(ids))
	for _, id := range ids {
		parts = append(parts, strconv.FormatInt(id, 10))
	}
	return strings.Join(parts, ",")
}

func parseUIDs(s string) []int64 {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]int64, 0, len(parts))
	for _, p := range parts {
		if v, err := strconv.ParseInt(strings.TrimSpace(p), 10, 64); err == nil {
			out = append(out, v)
		}
	}
	return out
}

// scanMessage 统一扫描 10 个消息字段，避免三处查询各写一遍。
func scanMessage(row interface{ Scan(dest ...any) error }) (model.Message, error) {
	var m model.Message
	var atStr string
	err := row.Scan(&m.MsgID, &m.ConvID, &m.SenderUID, &m.Seq, &m.Content,
		&m.Type, &m.ReplyTo, &atStr, &m.Recalled, &m.CreatedAt)
	m.AtUIDs = parseUIDs(atStr)
	return m, err
}

// ---- 消息：增量拉取 / 单条读取 / 撤回 ----

// ListMessagesAfter 增量拉取（断线重连、多端同步用）：seq > afterSeq 正序。
func (s *Store) ListMessagesAfter(ctx context.Context, convID, afterSeq int64, limit int) ([]model.Message, error) {
	if limit <= 0 || limit > 500 {
		limit = 200
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE conv_id=? AND seq>? ORDER BY seq ASC LIMIT ?`,
		convID, afterSeq, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Message
	for rows.Next() {
		m, err := scanMessage(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, nil
}

// GetMessageByID 不带 conv_id 的单条读取（表情回应、撤回只需要 msg_id）。
func (s *Store) GetMessageByID(ctx context.Context, msgID int64) (model.Message, error) {
	row := s.DB.QueryRowContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE msg_id=?`, msgID)
	return scanMessage(row)
}

// RecallMessage 撤回：只允许发送者本人、且 2 分钟内。
func (s *Store) RecallMessage(ctx context.Context, msgID, uid int64, window time.Duration) (model.Message, error) {
	m, err := s.GetMessageByID(ctx, msgID)
	if err != nil {
		return m, err
	}
	if m.SenderUID != uid {
		return m, fmt.Errorf("只能撤回自己发送的消息")
	}
	if m.Recalled {
		return m, nil
	}
	if window > 0 && time.Since(m.CreatedAt) > window {
		return m, fmt.Errorf("超过 %d 分钟，无法撤回", int(window.Minutes()))
	}
	if _, err := s.DB.ExecContext(ctx,
		`UPDATE messages SET recalled=1, content='' WHERE msg_id=?`, msgID); err != nil {
		return m, err
	}
	m.Recalled = true
	m.Content = ""
	return m, nil
}

// ---- 表情回应 ----

// ToggleReaction 加/取消一个表情，返回该消息的最新聚合。
func (s *Store) ToggleReaction(ctx context.Context, msgID, uid int64, emoji string) ([]model.Reaction, error) {
	var n int
	_ = s.DB.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM reactions WHERE msg_id=? AND uid=? AND emoji=?`,
		msgID, uid, emoji).Scan(&n)
	if n > 0 {
		if _, err := s.DB.ExecContext(ctx,
			`DELETE FROM reactions WHERE msg_id=? AND uid=? AND emoji=?`, msgID, uid, emoji); err != nil {
			return nil, err
		}
	} else {
		if _, err := s.DB.ExecContext(ctx,
			`INSERT IGNORE INTO reactions(msg_id,uid,emoji) VALUES(?,?,?)`, msgID, uid, emoji); err != nil {
			return nil, err
		}
	}
	return s.ListReactions(ctx, msgID, uid)
}

// ListReactions 某条消息的表情聚合（按 emoji 分组）。
func (s *Store) ListReactions(ctx context.Context, msgID, meUID int64) ([]model.Reaction, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT emoji, uid FROM reactions WHERE msg_id=? ORDER BY created_at`, msgID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	order := []string{}
	agg := map[string]*model.Reaction{}
	for rows.Next() {
		var emoji string
		var uid int64
		if err := rows.Scan(&emoji, &uid); err != nil {
			return nil, err
		}
		r, ok := agg[emoji]
		if !ok {
			r = &model.Reaction{Emoji: emoji}
			agg[emoji] = r
			order = append(order, emoji)
		}
		r.Count++
		r.Uids = append(r.Uids, uid)
		if uid == meUID {
			r.Mine = true
		}
	}
	out := make([]model.Reaction, 0, len(order))
	for _, e := range order {
		out = append(out, *agg[e])
	}
	return out, nil
}

// ---- 附件 ----
func (s *Store) AddAttachment(ctx context.Context, msgID int64, a model.Attachment) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO attachments(msg_id,name,mime,size,url) VALUES(?,?,?,?,?)`,
		msgID, a.Name, a.Mime, a.Size, a.URL)
	return err
}

// ListAttachments 批量取某个会话内多条消息的附件（渲染时一次装配）。
func (s *Store) ListAttachments(ctx context.Context, msgIDs []int64) (map[int64][]model.Attachment, error) {
	out := map[int64][]model.Attachment{}
	if len(msgIDs) == 0 {
		return out, nil
	}
	ph := strings.Repeat("?,", len(msgIDs))
	ph = ph[:len(ph)-1]
	args := make([]interface{}, 0, len(msgIDs))
	for _, id := range msgIDs {
		args = append(args, id)
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,name,mime,size,url FROM attachments WHERE msg_id IN (`+ph+`)`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var mid int64
		var a model.Attachment
		if err := rows.Scan(&mid, &a.Name, &a.Mime, &a.Size, &a.URL); err != nil {
			return nil, err
		}
		out[mid] = append(out[mid], a)
	}
	return out, nil
}

// ---- 会话设置（置顶 / 免打扰 / 标记未读） ----

type ConvSetting struct {
	Pinned       bool
	Muted        bool
	MarkedUnread bool
}

func (s *Store) GetConvSetting(ctx context.Context, uid, convID int64) ConvSetting {
	var st ConvSetting
	_ = s.DB.QueryRowContext(ctx,
		`SELECT pinned,muted,marked_unread FROM conv_settings WHERE uid=? AND conv_id=?`,
		uid, convID).Scan(&st.Pinned, &st.Muted, &st.MarkedUnread)
	return st
}

func (s *Store) SetConvSetting(ctx context.Context, uid, convID int64, field string, val bool) error {
	col := map[string]string{
		"pinned": "pinned", "muted": "muted", "marked_unread": "marked_unread",
	}[field]
	if col == "" {
		return fmt.Errorf("unknown field %s", field)
	}
	b := 0
	if val {
		b = 1
	}
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO conv_settings(uid,conv_id,`+col+`) VALUES(?,?,?)
		 ON DUPLICATE KEY UPDATE `+col+`=VALUES(`+col+`)`, uid, convID, b)
	return err
}

// ---- 会话列表 V2（带置顶 / 免打扰 / @我 标记） ----

func (s *Store) ListConversationsV2(ctx context.Context, uid int64, bigThreshold int) ([]model.ConversationView, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT c.conv_id,c.type,c.title,c.latest_seq,c.created_at,
		        COALESCE(MAX(r.read_seq),0), COUNT(DISTINCT cm2.uid),
		        COALESCE(last.content,''), COALESCE(last.sender_uid,0), COALESCE(last.at_uids,''),
		        COALESCE(last.created_at, c.created_at),
		        COALESCE(MAX(cs.pinned),0), COALESCE(MAX(cs.muted),0), COALESCE(MAX(cs.marked_unread),0)
		 FROM conversation_members cm
		 JOIN conversations c ON c.conv_id=cm.conv_id
		 LEFT JOIN user_conv_read r ON r.conv_id=c.conv_id AND r.uid=cm.uid
		 JOIN conversation_members cm2 ON cm2.conv_id=c.conv_id
		 LEFT JOIN conv_settings cs ON cs.uid=cm.uid AND cs.conv_id=c.conv_id
		 LEFT JOIN messages last ON last.conv_id=c.conv_id AND last.seq=c.latest_seq
		 WHERE cm.uid=?
		 GROUP BY c.conv_id
		 ORDER BY COALESCE(MAX(cs.pinned),0) DESC,
		          COALESCE(MAX(last.created_at),c.created_at) DESC`, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.ConversationView
	for rows.Next() {
		var v model.ConversationView
		var atStr string
		var pinned, muted, marked int
		if err := rows.Scan(&v.ConvID, &v.Type, &v.Title, &v.LatestSeq, &v.CreatedAt,
			&v.ReadSeq, &v.MemberCnt, &v.LastContent, &v.LastSenderUID, &atStr, &v.LastAt,
			&pinned, &muted, &marked); err != nil {
			return nil, err
		}
		v.Unread = v.LatestSeq - v.ReadSeq
		if v.Unread < 0 {
			v.Unread = 0
		}
		if v.MarkedUnread && v.Unread == 0 {
			v.Unread = 1 // 手动标记未读：红点最少显示 1
		}
		v.IsBig = bigThreshold > 0 && v.MemberCnt > bigThreshold
		v.Pinned, v.Muted, v.MarkedUnread = pinned == 1, muted == 1, marked == 1
		for _, at := range parseUIDs(atStr) {
			if at == uid {
				v.AtMe = true
			}
		}
		out = append(out, v)
	}
	return out, nil
}

// ---- 未读汇总（飞书图标红点 + tab 计数） ----

func (s *Store) UnreadSummary(ctx context.Context, uid int64) (model.UnreadSummary, error) {
	var sum model.UnreadSummary
	err := s.DB.QueryRowContext(ctx,
		`SELECT COALESCE(SUM(GREATEST(c.latest_seq-COALESCE(r.read_seq,0),0)),0),
		        COUNT(CASE WHEN c.latest_seq>COALESCE(r.read_seq,0) THEN 1 END),
		        COALESCE(SUM(CASE WHEN c.type=1 THEN GREATEST(c.latest_seq-COALESCE(r.read_seq,0),0) ELSE 0 END),0),
		        COALESCE(SUM(CASE WHEN c.type=2 THEN GREATEST(c.latest_seq-COALESCE(r.read_seq,0),0) ELSE 0 END),0)
		 FROM conversation_members cm
		 JOIN conversations c ON c.conv_id=cm.conv_id
		 LEFT JOIN user_conv_read r ON r.uid=cm.uid AND r.conv_id=c.conv_id
		 WHERE cm.uid=?`, uid).Scan(&sum.Total, &sum.ConvUnread, &sum.P2P, &sum.Group)
	if err != nil {
		return sum, err
	}
	// @我：未读区间内、且 at_uids 含我的消息条数
	_ = s.DB.QueryRowContext(ctx,
		`SELECT COUNT(*)
		 FROM messages m
		 JOIN conversation_members cm ON cm.conv_id=m.conv_id AND cm.uid=?
		 LEFT JOIN user_conv_read r ON r.uid=cm.uid AND r.conv_id=m.conv_id
		 WHERE m.seq>COALESCE(r.read_seq,0) AND m.sender_uid<>?
		   AND m.recalled=0 AND FIND_IN_SET(?, m.at_uids)`, uid, uid, uid).Scan(&sum.AtMe)
	return sum, nil
}

// MentionMessages 拉「@我」的消息（未读优先，最多 limit 条）。
func (s *Store) MentionMessages(ctx context.Context, uid int64, limit int) ([]model.Message, error) {
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT m.msg_id,m.conv_id,m.sender_uid,m.seq,m.content,m.msg_type,
		        m.reply_to,COALESCE(m.at_uids,''),m.recalled,m.created_at
		 FROM messages m
		 JOIN conversation_members cm ON cm.conv_id=m.conv_id AND cm.uid=?
		 WHERE m.sender_uid<>? AND m.recalled=0 AND FIND_IN_SET(?, m.at_uids)
		 ORDER BY m.created_at DESC LIMIT ?`, uid, uid, uid, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Message
	for rows.Next() {
		m, err := scanMessage(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, nil
}

// ---- 搜索（消息 / 联系人 / 会话） ----

func (s *Store) SearchMessages(ctx context.Context, uid, convID int64, q string, limit int) ([]model.SearchHit, error) {
	if limit <= 0 || limit > 50 {
		limit = 20
	}
	sqlStr := `SELECT m.msg_id,m.conv_id,m.seq,m.content,c.title,COALESCE(u.name,'')
		 FROM messages m
		 JOIN conversation_members cm ON cm.conv_id=m.conv_id AND cm.uid=?
		 JOIN conversations c ON c.conv_id=m.conv_id
		 LEFT JOIN users u ON u.uid=m.sender_uid
		 WHERE m.content LIKE ? AND m.recalled=0`
	args := []interface{}{uid, "%" + q + "%"}
	if convID > 0 {
		sqlStr += ` AND m.conv_id=?`
		args = append(args, convID)
	}
	sqlStr += ` ORDER BY m.created_at DESC LIMIT ?`
	args = append(args, limit)

	rows, err := s.DB.QueryContext(ctx, sqlStr, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.SearchHit
	for rows.Next() {
		var h model.SearchHit
		var convTitle, sender string
		if err := rows.Scan(&h.ID, &h.ConvID, &h.Seq, &h.Snippet, &convTitle, &sender); err != nil {
			return nil, err
		}
		h.Kind = "message"
		h.Title = fmt.Sprintf("%s · %s", convTitle, sender)
		out = append(out, h)
	}
	return out, nil
}

func (s *Store) SearchUsers(ctx context.Context, q string, limit int) ([]model.User, error) {
	if limit <= 0 || limit > 50 {
		limit = 10
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT uid,name,COALESCE(avatar,''),COALESCE(dept,''),COALESCE(dept_id,0),
		        COALESCE(dept_title,''),COALESCE(email,''),COALESCE(phone,'')
		 FROM users WHERE name LIKE ? OR dept LIKE ?
		 ORDER BY uid LIMIT ?`, "%"+q+"%", "%"+q+"%", limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.User
	for rows.Next() {
		var u model.User
		if err := rows.Scan(&u.UID, &u.Name, &u.Avatar, &u.Dept, &u.DeptID, &u.DeptTitle, &u.Email, &u.Phone); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, nil
}

func (s *Store) SearchConvs(ctx context.Context, uid int64, q string, limit int) ([]model.ConversationView, error) {
	if limit <= 0 || limit > 30 {
		limit = 10
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT c.conv_id,c.type,COALESCE(c.title,''),c.latest_seq,c.created_at,
		        (SELECT COUNT(*) FROM conversation_members x WHERE x.conv_id=c.conv_id)
		 FROM conversations c
		 JOIN conversation_members cm ON cm.conv_id=c.conv_id AND cm.uid=?
		 WHERE c.title LIKE ? ORDER BY c.latest_seq DESC LIMIT ?`,
		uid, "%"+q+"%", limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.ConversationView
	for rows.Next() {
		var v model.ConversationView
		if err := rows.Scan(&v.ConvID, &v.Type, &v.Title, &v.LatestSeq, &v.CreatedAt, &v.MemberCnt); err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, nil
}

// FindP2P 查两人之间是否已有单聊，有则复用。
func (s *Store) FindP2P(ctx context.Context, a, b int64) int64 {
	var convID int64
	_ = s.DB.QueryRowContext(ctx,
		`SELECT c.conv_id FROM conversations c
		 JOIN conversation_members m1 ON m1.conv_id=c.conv_id AND m1.uid=?
		 JOIN conversation_members m2 ON m2.conv_id=c.conv_id AND m2.uid=?
		 WHERE c.type=1 LIMIT 1`, a, b).Scan(&convID)
	return convID
}

// ---- 成员管理 ----

func (s *Store) IsMember(ctx context.Context, convID, uid int64) bool {
	var n int
	_ = s.DB.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM conversation_members WHERE conv_id=? AND uid=?`, convID, uid).Scan(&n)
	return n > 0
}

func (s *Store) AddMembers(ctx context.Context, convID int64, uids []int64) error {
	for _, uid := range uids {
		if _, err := s.DB.ExecContext(ctx,
			`INSERT IGNORE INTO conversation_members(conv_id,uid) VALUES(?,?)`, convID, uid); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) RemoveMember(ctx context.Context, convID, uid int64) error {
	_, err := s.DB.ExecContext(ctx,
		`DELETE FROM conversation_members WHERE conv_id=? AND uid=?`, convID, uid)
	return err
}

// ---- 用户 / 组织架构 ----

func (s *Store) GetUser(ctx context.Context, uid int64) (model.User, error) {
	var u model.User
	err := s.DB.QueryRowContext(ctx,
		`SELECT uid,name,COALESCE(avatar,''),COALESCE(dept,''),COALESCE(dept_id,0),
		        COALESCE(dept_title,''),COALESCE(email,''),COALESCE(phone,'')
		 FROM users WHERE uid=?`, uid).
		Scan(&u.UID, &u.Name, &u.Avatar, &u.Dept, &u.DeptID, &u.DeptTitle, &u.Email, &u.Phone)
	return u, err
}

func (s *Store) ListDepts(ctx context.Context) ([]model.Dept, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT dept_id,name,parent_id FROM departments ORDER BY sort,dept_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Dept
	for rows.Next() {
		var d model.Dept
		if err := rows.Scan(&d.DeptID, &d.Name, &d.ParentID); err != nil {
			return nil, err
		}
		out = append(out, d)
	}
	for i := range out {
		_ = s.DB.QueryRowContext(ctx,
			`SELECT COUNT(*) FROM users WHERE dept_id=?`, out[i].DeptID).Scan(&out[i].Count)
	}
	return out, nil
}

func (s *Store) ListDeptMembers(ctx context.Context, deptID int64) ([]model.User, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT uid,name,COALESCE(avatar,''),COALESCE(dept,''),COALESCE(dept_id,0),
		        COALESCE(dept_title,''),COALESCE(email,''),COALESCE(phone,'')
		 FROM users WHERE dept_id=? ORDER BY uid`, deptID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.User
	for rows.Next() {
		var u model.User
		if err := rows.Scan(&u.UID, &u.Name, &u.Avatar, &u.Dept, &u.DeptID, &u.DeptTitle, &u.Email, &u.Phone); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, nil
}

// SeedOrg 初始化部门树，并把已有用户按 uid 取模分到各部门。
// 幂等：部门已存在则只补用户归属。
func (s *Store) SeedOrg(ctx context.Context) error {
	depts := []model.Dept{
		{DeptID: 1, Name: "产品部", ParentID: 0, Sort: 1},
		{DeptID: 2, Name: "研发部", ParentID: 0, Sort: 2},
		{DeptID: 3, Name: "设计部", ParentID: 0, Sort: 3},
		{DeptID: 4, Name: "市场部", ParentID: 0, Sort: 4},
		{DeptID: 5, Name: "人力行政", ParentID: 0, Sort: 5},
	}
	for _, d := range depts {
		if _, err := s.DB.ExecContext(ctx,
			`INSERT INTO departments(dept_id,name,parent_id,sort) VALUES(?,?,?,?)
			 ON DUPLICATE KEY UPDATE name=VALUES(name),sort=VALUES(sort)`,
			d.DeptID, d.Name, d.ParentID, d.Sort); err != nil {
			return err
		}
	}
	titles := map[int64][]string{
		1: {"产品经理", "高级产品经理", "产品助理"},
		2: {"后端工程师", "前端工程师", "算法工程师", "测试工程师"},
		3: {"交互设计师", "视觉设计师"},
		4: {"市场经理", "品牌运营", "增长运营"},
		5: {"HRBP", "招聘专员", "行政主管"},
	}
	rows, err := s.DB.QueryContext(ctx, `SELECT uid,name FROM users ORDER BY uid`)
	if err != nil {
		return err
	}
	type pair struct {
		uid  int64
		name string
	}
	var users []pair
	for rows.Next() {
		var p pair
		if err := rows.Scan(&p.uid, &p.name); err != nil {
			rows.Close()
			return err
		}
		users = append(users, p)
	}
	rows.Close()

	for i, u := range users {
		deptID := int64(i%5 + 1)
		var deptName string
		for _, d := range depts {
			if d.DeptID == deptID {
				deptName = d.Name
			}
		}
		ts := titles[deptID]
		title := ts[i%len(ts)]
		email := fmt.Sprintf("user%d@cyberspace.dev", u.uid)
		phone := fmt.Sprintf("138%08d", u.uid%100000000)
		if _, err := s.DB.ExecContext(ctx,
			`UPDATE users SET dept=?,dept_id=?,dept_title=?,email=?,phone=?
			 WHERE uid=? AND (dept IS NULL OR dept='')`,
			deptName, deptID, title, email, phone, u.uid); err != nil {
			return err
		}
	}
	return nil
}

// ---- 登录态（简易 token） ----

func (s *Store) CreateSession(ctx context.Context, token string, uid int64) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO sessions(token,uid) VALUES(?,?)`, token, uid)
	return err
}

func (s *Store) UIDByToken(ctx context.Context, token string) (int64, error) {
	var uid int64
	err := s.DB.QueryRowContext(ctx, `SELECT uid FROM sessions WHERE token=?`, token).Scan(&uid)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("token invalid")
	}
	return uid, err
}

func (s *Store) DeleteSession(ctx context.Context, token string) error {
	_, err := s.DB.ExecContext(ctx, `DELETE FROM sessions WHERE token=?`, token)
	return err
}

// ---- 通知中心 ----

func (s *Store) AddNotification(ctx context.Context, uid int64, n model.Notification) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO notifications(uid,ntype,title,body,conv_id,msg_id) VALUES(?,?,?,?,?,?)`,
		uid, n.Type, n.Title, n.Body, n.ConvID, n.MsgID)
	return err
}

// ListNotifications 拉通知列表（最新 50 条）。
func (s *Store) ListNotifications(ctx context.Context, uid int64, limit int) ([]model.Notification, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT id,ntype,title,body,COALESCE(conv_id,0),COALESCE(msg_id,0),
		        CASE WHEN read_at IS NULL THEN 0 ELSE 1 END,created_at
		 FROM notifications WHERE uid=? ORDER BY id DESC LIMIT ?`, uid, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Notification
	for rows.Next() {
		var n model.Notification
		var read int
		if err := rows.Scan(&n.ID, &n.Type, &n.Title, &n.Body, &n.ConvID, &n.MsgID, &read, &n.CreatedAt); err != nil {
			return nil, err
		}
		n.Read = read == 1
		out = append(out, n)
	}
	return out, nil
}

func (s *Store) MarkNotificationsRead(ctx context.Context, uid int64) error {
	_, err := s.DB.ExecContext(ctx,
		`UPDATE notifications SET read_at=NOW() WHERE uid=? AND read_at IS NULL`, uid)
	return err
}

// ---- 多端已读位置 ----

// ReadStates 返回该用户全部会话的已读水位线（换设备登录时一次同步）。
func (s *Store) ReadStates(ctx context.Context, uid int64) (map[int64]int64, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT conv_id,read_seq FROM user_conv_read WHERE uid=?`, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := map[int64]int64{}
	for rows.Next() {
		var c, sq int64
		if err := rows.Scan(&c, &sq); err != nil {
			return nil, err
		}
		out[c] = sq
	}
	return out, nil
}

// ---- 批量装配（历史消息渲染用，避免 N+1 查询） ----

// ListReactionsBatch 一次取出一批消息的表情聚合。
func (s *Store) ListReactionsBatch(ctx context.Context, msgIDs []int64, meUID int64) map[int64][]model.Reaction {
	out := map[int64][]model.Reaction{}
	if len(msgIDs) == 0 {
		return out
	}
	ph := strings.Repeat("?,", len(msgIDs))
	ph = ph[:len(ph)-1]
	args := make([]interface{}, 0, len(msgIDs))
	for _, id := range msgIDs {
		args = append(args, id)
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,emoji,uid FROM reactions WHERE msg_id IN (`+ph+`) ORDER BY created_at`, args...)
	if err != nil {
		return out
	}
	defer rows.Close()
	idx := map[int64]map[string]*model.Reaction{}
	for rows.Next() {
		var mid, uid int64
		var emoji string
		if err := rows.Scan(&mid, &emoji, &uid); err != nil {
			return out
		}
		if idx[mid] == nil {
			idx[mid] = map[string]*model.Reaction{}
		}
		r := idx[mid][emoji]
		if r == nil {
			r = &model.Reaction{Emoji: emoji}
			idx[mid][emoji] = r
		}
		r.Count++
		r.Uids = append(r.Uids, uid)
		if uid == meUID {
			r.Mine = true
		}
	}
	for mid, m := range idx {
		for _, r := range m {
			out[mid] = append(out[mid], *r)
		}
	}
	return out
}

// GetMessagesByIDs 批量取消息（用于装配引用块的被引消息）。
func (s *Store) GetMessagesByIDs(ctx context.Context, ids []int64) map[int64]model.Message {
	out := map[int64]model.Message{}
	if len(ids) == 0 {
		return out
	}
	ph := strings.Repeat("?,", len(ids))
	ph = ph[:len(ph)-1]
	args := make([]interface{}, 0, len(ids))
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE msg_id IN (`+ph+`)`, args...)
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		m, err := scanMessage(rows)
		if err != nil {
			return out
		}
		out[m.MsgID] = m
	}
	return out
}
