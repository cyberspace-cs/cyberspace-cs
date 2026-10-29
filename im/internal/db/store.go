// Package db 封装 MySQL 持久化层（持久化基准源）。
//
// 飞书式 B 端 IM 的 MySQL 职责：
//  - messages：每条消息只存一份（扩散读），(conv_id, seq) 唯一。
//  - user_conv_read：会话水位线，红点未读基准。
//  - user_msg_read：单条已读回执明细（写入量大，生产按 7 天归档冷存储）。
//  - conversations / members：会话与成员关系。
package db

import (
	"context"
	"database/sql"
	_ "embed"
	"fmt"
	"strings"
	"time"

	_ "github.com/go-sql-driver/mysql"

	"github.com/cyberspace-cs/im/internal/model"
)

//go:embed schema.sql
var schemaSQL string

// Store 包裹 *sql.DB，提供 IM 读写方法。
type Store struct {
	DB *sql.DB
}

// NewStore 打开 MySQL 连接、建表、可选灌入演示数据。
func NewStore(dsn string) (*Store, error) {
	// 建表脚本含多条语句，需开启 multiStatements
	if !strings.Contains(dsn, "multiStatements") {
		if strings.Contains(dsn, "?") {
			dsn += "&multiStatements=true"
		} else {
			dsn += "?multiStatements=true"
		}
	}
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, err
	}
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("mysql ping: %w", err)
	}
	db.SetMaxOpenConns(50)
	db.SetMaxIdleConns(10)
	s := &Store{DB: db}
	if _, err := db.Exec(schemaSQL); err != nil {
		return nil, fmt.Errorf("init schema: %w", err)
	}
	if err := s.migrate(context.Background()); err != nil {
		return nil, fmt.Errorf("migrate: %w", err)
	}
	return s, nil
}

// ---- 用户 / 会话 ----

func (s *Store) UpsertUser(ctx context.Context, u model.User) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO users(uid,name,avatar) VALUES(?,?,?)
		 ON DUPLICATE KEY UPDATE name=VALUES(name), avatar=VALUES(avatar)`,
		u.UID, u.Name, u.Avatar)
	return err
}

// CreateConversation 创建会话并加入成员，返回 conv_id。
func (s *Store) CreateConversation(ctx context.Context, convType int, title string, members []int64) (int64, error) {
	tx, err := s.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()
	res, err := tx.ExecContext(ctx,
		`INSERT INTO conversations(type,title) VALUES(?,?)`, convType, title)
	if err != nil {
		return 0, err
	}
	convID, _ := res.LastInsertId()
	for _, m := range members {
		if _, err := tx.ExecContext(ctx,
			`INSERT IGNORE INTO conversation_members(conv_id,uid) VALUES(?,?)`, convID, m); err != nil {
			return 0, err
		}
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	return convID, nil
}

func (s *Store) GetMembers(ctx context.Context, convID int64) ([]int64, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT uid FROM conversation_members WHERE conv_id=?`, convID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []int64
	for rows.Next() {
		var uid int64
		if err := rows.Scan(&uid); err != nil {
			return nil, err
		}
		out = append(out, uid)
	}
	return out, nil
}

func (s *Store) CountMembers(ctx context.Context, convID int64) (int, error) {
	var n int
	err := s.DB.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM conversation_members WHERE conv_id=?`, convID).Scan(&n)
	return n, err
}

// ---- 消息（扩散读：单副本 + 水位线） ----

// InsertMessage 在事务内分配 seq 并落库，返回 (msg_id, seq)。
// 用 SELECT ... FOR UPDATE 锁住会话行，避免并发分配出重复 seq。
func (s *Store) InsertMessage(ctx context.Context, convID, senderUID int64, content string, msgType int) (int64, int64, error) {
	return s.InsertMessageFull(ctx, convID, senderUID, content, msgType, 0, nil)
}

// InsertMessageFull 带「引用回复 / @提及」的完整版本。
func (s *Store) InsertMessageFull(ctx context.Context, convID, senderUID int64, content string, msgType int, replyTo int64, atUIDs []int64) (int64, int64, error) {
	tx, err := s.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, 0, err
	}
	defer tx.Rollback()
	var latest int64
	if err := tx.QueryRowContext(ctx,
		`SELECT latest_seq FROM conversations WHERE conv_id=? FOR UPDATE`, convID).Scan(&latest); err != nil {
		return 0, 0, err
	}
	newSeq := latest + 1
	if _, err := tx.ExecContext(ctx,
		`UPDATE conversations SET latest_seq=? WHERE conv_id=?`, newSeq, convID); err != nil {
		return 0, 0, err
	}
	res, err := tx.ExecContext(ctx,
		`INSERT INTO messages(conv_id,sender_uid,seq,content,msg_type,reply_to,at_uids) VALUES(?,?,?,?,?,?,?)`,
		convID, senderUID, newSeq, content, msgType, replyTo, joinUIDs(atUIDs))
	if err != nil {
		return 0, 0, err
	}
	msgID, _ := res.LastInsertId()
	if err := tx.Commit(); err != nil {
		return 0, 0, err
	}
	return msgID, newSeq, nil
}

// ListMessages 扩散读：按 seq 拉取历史（游标 before_seq 之前，倒序取 limit 条）。
func (s *Store) ListMessages(ctx context.Context, convID, beforeSeq int64, limit int) ([]model.Message, error) {
	if limit <= 0 || limit > 100 {
		limit = 50
	}
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE conv_id=? AND seq<=? ORDER BY seq DESC LIMIT ?`,
		convID, beforeSeq, limit)
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

// MessagesInRange 取 [lo, hi] 区间内、按 seq 正序的消息（用于「已读」批量写回执）。
func (s *Store) MessagesInRange(ctx context.Context, convID, lo, hi int64) ([]model.Message, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE conv_id=? AND seq BETWEEN ? AND ? ORDER BY seq ASC`,
		convID, lo, hi)
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

func (s *Store) GetMessage(ctx context.Context, convID, msgID int64) (model.Message, error) {
	row := s.DB.QueryRowContext(ctx,
		`SELECT msg_id,conv_id,sender_uid,seq,content,msg_type,reply_to,COALESCE(at_uids,''),recalled,created_at
		 FROM messages WHERE conv_id=? AND msg_id=?`, convID, msgID)
	return scanMessage(row)
}

func (s *Store) GetLatestSeq(ctx context.Context, convID int64) (int64, error) {
	var n int64
	err := s.DB.QueryRowContext(ctx,
		`SELECT latest_seq FROM conversations WHERE conv_id=?`, convID).Scan(&n)
	return n, err
}

// ---- 水位线（红点） ----

func (s *Store) GetReadSeq(ctx context.Context, uid, convID int64) (int64, error) {
	var n int64
	err := s.DB.QueryRowContext(ctx,
		`SELECT COALESCE((SELECT read_seq FROM user_conv_read WHERE uid=? AND conv_id=?),0)`, uid, convID).Scan(&n)
	return n, err
}

func (s *Store) SetReadSeq(ctx context.Context, uid, convID, seq int64) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT INTO user_conv_read(uid,conv_id,read_seq) VALUES(?,?,?)
		 ON DUPLICATE KEY UPDATE read_seq=GREATEST(read_seq,VALUES(read_seq))`,
		uid, convID, seq)
	return err
}

// ---- 单条已读回执明细（落库 + 冷归档示意） ----

func (s *Store) InsertMsgRead(ctx context.Context, convID, msgID, uid int64) error {
	_, err := s.DB.ExecContext(ctx,
		`INSERT IGNORE INTO user_msg_read(conv_id,msg_id,uid) VALUES(?,?,?)`, convID, msgID, uid)
	return err
}

// GetReaders 从 MySQL 回执明细取某条消息的读者（Redis 不可用时的冷路径）。
func (s *Store) GetReaders(ctx context.Context, msgID int64) ([]int64, error) {
	rows, err := s.DB.QueryContext(ctx, `SELECT uid FROM user_msg_read WHERE msg_id=?`, msgID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []int64
	for rows.Next() {
		var u int64
		if err := rows.Scan(&u); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, nil
}

// ---- 会话列表（带水位线视图） ----

func (s *Store) ListConversationsForUser(ctx context.Context, uid int64, bigThreshold int) ([]model.ConversationView, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT c.conv_id,c.type,c.title,c.latest_seq,c.created_at,
		        COALESCE(MAX(r.read_seq),0), COUNT(DISTINCT cm2.uid),
		        COALESCE((SELECT content FROM messages m WHERE m.conv_id=c.conv_id ORDER BY m.seq DESC LIMIT 1), ''),
		        COALESCE((SELECT sender_uid FROM messages m WHERE m.conv_id=c.conv_id ORDER BY m.seq DESC LIMIT 1), 0)
		 FROM conversation_members cm
		 JOIN conversations c ON c.conv_id=cm.conv_id
		 LEFT JOIN user_conv_read r ON r.conv_id=c.conv_id AND r.uid=?
		 JOIN conversation_members cm2 ON cm2.conv_id=c.conv_id
		 WHERE cm.uid=?
		 GROUP BY c.conv_id
		 ORDER BY COALESCE((SELECT MAX(m.created_at) FROM messages m WHERE m.conv_id=c.conv_id), c.created_at) DESC`, uid, uid)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.ConversationView
	for rows.Next() {
		var v model.ConversationView
		if err := rows.Scan(&v.ConvID, &v.Type, &v.Title, &v.LatestSeq, &v.CreatedAt, &v.ReadSeq, &v.MemberCnt, &v.LastContent, &v.LastSenderUID); err != nil {
			return nil, err
		}
		v.Unread = v.LatestSeq - v.ReadSeq
		if v.Unread < 0 {
			v.Unread = 0
		}
		v.IsBig = bigThreshold > 0 && v.MemberCnt > bigThreshold
		out = append(out, v)
	}
	return out, nil
}

// ListUsers 返回全部用户（uid/name/avatar）。
func (s *Store) ListUsers(ctx context.Context) ([]model.User, error) {
	rows, err := s.DB.QueryContext(ctx, `SELECT uid,name,avatar FROM users ORDER BY uid`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.User
	for rows.Next() {
		var u model.User
		if err := rows.Scan(&u.UID, &u.Name, &u.Avatar); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, nil
}

// ListConvMembers 返回某会话的成员（带 name/avatar）。
func (s *Store) ListConvMembers(ctx context.Context, convID int64) ([]model.User, error) {
	rows, err := s.DB.QueryContext(ctx,
		`SELECT u.uid,u.name,u.avatar
		 FROM conversation_members cm JOIN users u ON u.uid=cm.uid
		 WHERE cm.conv_id=? ORDER BY u.uid`, convID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.User
	for rows.Next() {
		var u model.User
		if err := rows.Scan(&u.UID, &u.Name, &u.Avatar); err != nil {
			return nil, err
		}
		out = append(out, u)
	}
	return out, nil
}

// SeedBig 灌入 n 个用户 + 1 个 n 人群（用于「未读数快速获取」压测演示）。
// 返回群聊 convID。已存在则直接返回已有群。
func (s *Store) SeedBig(ctx context.Context, n int) (int64, error) {
	if n < 2 {
		n = 50
	}
	// 幂等：已存在「压测群」则复用
	var exists int64
	_ = s.DB.QueryRowContext(ctx,
		`SELECT conv_id FROM conversations WHERE title=? LIMIT 1`, "未读压测群").Scan(&exists)
	if exists > 0 {
		return exists, nil
	}
	members := make([]int64, 0, n)
	for i := 1; i <= n; i++ {
		uid := int64(2000 + i)
		if err := s.UpsertUser(ctx, model.User{
			UID:    uid,
			Name:   "User" + fmt.Sprintf("%02d", i),
			Avatar: "👤",
		}); err != nil {
			return 0, err
		}
		members = append(members, uid)
	}
	convID, err := s.CreateConversation(ctx, 2, "未读压测群", members)
	if err != nil {
		return 0, err
	}
	// 预置一条群消息，便于演示回执
	if _, _, err := s.InsertMessage(ctx, convID, members[0], "这是 50 人压测群的第一条消息，用于演示未读数快速获取 🚀", 1); err != nil {
		return 0, err
	}
	return convID, nil
}

// ---- 演示数据 ----

// SeedDemo 在用户表为空时灌入 4 个用户 + 1 个单聊 + 1 个群聊。
// 返回 (单聊convID, 群聊convID, error)。已存在则直接返回已有 conv。
func (s *Store) SeedDemo(ctx context.Context) (int64, int64, error) {
	var cnt int
	_ = s.DB.QueryRowContext(ctx, `SELECT COUNT(*) FROM users`).Scan(&cnt)
	if cnt > 0 {
		// 已有数据：找第一个群聊返回
		var g int64
		err := s.DB.QueryRowContext(ctx,
			`SELECT conv_id FROM conversations WHERE type=2 LIMIT 1`).Scan(&g)
		if err != nil {
			return 0, 0, nil
		}
		var p int64
		_ = s.DB.QueryRowContext(ctx,
			`SELECT conv_id FROM conversations WHERE type=1 LIMIT 1`).Scan(&p)
		return p, g, nil
	}
	users := []model.User{
		{UID: 1001, Name: "Alice", Avatar: "🦊"},
		{UID: 1002, Name: "Bob", Avatar: "🐼"},
		{UID: 1003, Name: "Carol", Avatar: "🐯"},
		{UID: 1004, Name: "Dave", Avatar: "🐧"},
	}
	for _, u := range users {
		if err := s.UpsertUser(ctx, u); err != nil {
			return 0, 0, err
		}
	}
	// 让创建时间稳定，避免演示随机
	_, _ = s.DB.ExecContext(ctx, `UPDATE users SET created_at=? WHERE uid=1001`, time.Now())

	p, err := s.CreateConversation(ctx, 1, "", []int64{1001, 1002})
	if err != nil {
		return 0, 0, err
	}
	g, err := s.CreateConversation(ctx, 2, "IM教学群", []int64{1001, 1002, 1003, 1004})
	if err != nil {
		return 0, 0, err
	}
	// 预置一条群消息，便于演示回执
	if _, _, err := s.InsertMessage(ctx, g, 1001, "大家好，这是飞书式已读回执 IM 教学项目 👋", 1); err != nil {
		return 0, 0, err
	}
	return p, g, nil
}
