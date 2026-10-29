package api

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/cyberspace-cs/im/internal/model"
	"github.com/cyberspace-cs/im/internal/ws"
)

// ---- 基础设施 ----

func writeJSON(w http.ResponseWriter, v interface{}, err error) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	if err != nil {
		w.WriteHeader(500)
		_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
		return
	}
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func decode(r *http.Request, v interface{}) error {
	defer r.Body.Close()
	return json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(v)
}

func qInt(r *http.Request, key string) int64 {
	v, _ := strconv.ParseInt(r.URL.Query().Get(key), 10, 64)
	return v
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return r.URL.Query().Get("token")
}

// requireUID 解析身份：优先 token，其次 uid 参数（教学脚本兼容）。
// token 存在但无效时直接 401，避免"拿错 token 还能冒充"。
func (s *Server) requireUID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	if tok := bearer(r); tok != "" {
		uid, err := s.svc.UIDByToken(tok)
		if err != nil || uid == 0 {
			writeErr(w, 401, "token 无效或已过期")
			return 0, false
		}
		return uid, true
	}
	if uid := qInt(r, "uid"); uid > 0 {
		return uid, true
	}
	writeErr(w, 401, "需要 token 或 uid")
	return 0, false
}

// ---- 认证 ----

type loginReq struct {
	UID int64 `json:"uid"`
}

// handleLogin 教学版：选出身份即签发 token，不做密码校验。
// 真实系统这里应是「手机号+验证码」或 SSO，然后签发 JWT。
func (s *Server) handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, 405, "POST only")
		return
	}
	var req loginReq
	if err := decode(r, &req); err != nil || req.UID == 0 {
		writeErr(w, 400, "uid required")
		return
	}
	u, err := s.svc.User(req.UID)
	if err != nil {
		writeErr(w, 404, "用户不存在")
		return
	}
	tok, err := randomToken()
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	if err := s.svc.LoginToken(req.UID, tok); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, map[string]interface{}{"token": tok, "user": u}, nil)
}

func (s *Server) handleLogout(w http.ResponseWriter, r *http.Request) {
	if tok := bearer(r); tok != "" {
		_ = s.svc.Logout(tok)
	}
	writeJSON(w, map[string]bool{"ok": true}, nil)
}

func (s *Server) handleMe(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	u, err := s.svc.User(uid)
	writeJSON(w, u, err)
}

func randomToken() (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// ---- 会话 ----

func (s *Server) handleConversations(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	switch r.Method {
	case http.MethodGet:
		list, err := s.svc.ListConversationsV2(uid)
		writeJSON(w, list, err)
	case http.MethodPost:
		var req struct {
			Type    int     `json:"type"`
			Title   string  `json:"title"`
			Members []int64 `json:"members"`
		}
		if err := decode(r, &req); err != nil {
			writeErr(w, 400, "invalid body")
			return
		}
		convID, err := s.svc.CreateConversation(uid, req.Type, req.Title, req.Members)
		if err != nil {
			writeErr(w, 400, err.Error())
			return
		}
		writeJSON(w, map[string]int64{"conv_id": convID}, nil)
	default:
		writeErr(w, 405, "method not allowed")
	}
}

func (s *Server) handleConvMembers(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	var req struct {
		ConvID int64   `json:"conv_id"`
		Op     string  `json:"op"` // add | remove | leave
		UIDs   []int64 `json:"uids"`
	}
	if err := decode(r, &req); err != nil || req.ConvID == 0 {
		writeErr(w, 400, "conv_id required")
		return
	}
	switch req.Op {
	case "add":
		writeJSON(w, map[string]bool{"ok": true}, s.svc.AddMembers(uid, req.ConvID, req.UIDs))
	case "remove":
		if len(req.UIDs) == 0 {
			writeErr(w, 400, "uids required")
			return
		}
		writeJSON(w, map[string]bool{"ok": true}, s.svc.RemoveMember(uid, req.ConvID, req.UIDs[0]))
	case "leave":
		writeJSON(w, map[string]bool{"ok": true}, s.svc.RemoveMember(uid, req.ConvID, uid))
	default:
		writeErr(w, 400, "op must be add/remove/leave")
	}
}

func (s *Server) handleConvSettings(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	var req struct {
		ConvID       int64 `json:"conv_id"`
		Pinned       *bool `json:"pinned"`
		Muted        *bool `json:"muted"`
		MarkedUnread *bool `json:"marked_unread"`
	}
	if err := decode(r, &req); err != nil || req.ConvID == 0 {
		writeErr(w, 400, "conv_id required")
		return
	}
	fields := map[string]bool{}
	if req.Pinned != nil {
		fields["pinned"] = *req.Pinned
	}
	if req.Muted != nil {
		fields["muted"] = *req.Muted
	}
	if req.MarkedUnread != nil {
		fields["marked_unread"] = *req.MarkedUnread
	}
	writeJSON(w, map[string]bool{"ok": true}, s.svc.SetConvSetting(uid, req.ConvID, fields))
}

func (s *Server) handleMembers(w http.ResponseWriter, r *http.Request) {
	convID := qInt(r, "conv_id")
	if convID == 0 {
		writeErr(w, 400, "conv_id required")
		return
	}
	list, err := s.svc.ListMembers(convID)
	writeJSON(w, list, err)
}

// ---- 消息 ----

func (s *Server) handleMessages(w http.ResponseWriter, r *http.Request) {
	convID := qInt(r, "conv_id")
	if convID == 0 {
		writeErr(w, 400, "conv_id required")
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if after := qInt(r, "after_seq"); after > 0 {
		msgs, err := s.svc.PullAfter(convID, after, limit)
		writeJSON(w, msgs, err)
		return
	}
	before := qInt(r, "before_seq")
	if before == 0 {
		before = 1 << 62
	}
	msgs, err := s.svc.PullHistory(convID, before, limit)
	writeJSON(w, msgs, err)
}

func (s *Server) handleReceipt(w http.ResponseWriter, r *http.Request) {
	convID, msgID := qInt(r, "conv_id"), qInt(r, "msg_id")
	if convID == 0 || msgID == 0 {
		writeErr(w, 400, "conv_id & msg_id required")
		return
	}
	rc, err := s.svc.Receipt(convID, msgID)
	if err != nil {
		writeJSON(w, nil, err)
		return
	}
	// 分页：大群回执名单可能上千人，前端一次只渲染一屏
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 {
		limit = 100
	}
	total := len(rc.Readers)
	if offset > total {
		offset = total
	}
	end := offset + limit
	if end > total {
		end = total
	}
	rc.Readers = rc.Readers[offset:end]
	rc.Offset, rc.Limit = offset, limit
	writeJSON(w, rc, nil)
}

func (s *Server) handleRecall(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	var req struct {
		ConvID int64 `json:"conv_id"`
		MsgID  int64 `json:"msg_id"`
	}
	if err := decode(r, &req); err != nil || req.MsgID == 0 {
		writeErr(w, 400, "msg_id required")
		return
	}
	if err := s.svc.RecallByREST(uid, req.ConvID, req.MsgID); err != nil {
		writeErr(w, 400, err.Error())
		return
	}
	writeJSON(w, map[string]bool{"ok": true}, nil)
}

func (s *Server) handleReaction(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	var req struct {
		ConvID int64  `json:"conv_id"`
		MsgID  int64  `json:"msg_id"`
		Emoji  string `json:"emoji"`
	}
	if err := decode(r, &req); err != nil || req.MsgID == 0 {
		writeErr(w, 400, "msg_id required")
		return
	}
	agg, err := s.svc.ReactByREST(uid, req.ConvID, req.MsgID, req.Emoji)
	writeJSON(w, map[string]interface{}{"reactions": agg}, err)
}

func (s *Server) handleForward(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	var req struct {
		MsgID     int64   `json:"msg_id"`
		ToConvIDs []int64 `json:"to_conv_ids"`
	}
	if err := decode(r, &req); err != nil || req.MsgID == 0 {
		writeErr(w, 400, "msg_id required")
		return
	}
	ids, err := s.svc.Forward(uid, req.MsgID, req.ToConvIDs)
	writeJSON(w, map[string]interface{}{"new_msg_ids": ids}, err)
}

// ---- 聚合查询 ----

func (s *Server) handleUnreadSummary(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	sum, err := s.svc.UnreadSummary(uid)
	writeJSON(w, sum, err)
}

func (s *Server) handleSearch(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	q := r.URL.Query().Get("q")
	hits, err := s.svc.Search(uid, q, r.URL.Query().Get("scope"), qInt(r, "conv_id"))
	writeJSON(w, map[string]interface{}{"hits": hits}, err)
}

func (s *Server) handleMentions(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	list, err := s.svc.Mentions(uid)
	writeJSON(w, list, err)
}

func (s *Server) handleReadState(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	st, err := s.svc.ReadStates(uid)
	writeJSON(w, map[string]interface{}{"states": st}, err)
}

func (s *Server) handlePresence(w http.ResponseWriter, r *http.Request) {
	convID := qInt(r, "conv_id")
	if convID == 0 {
		writeErr(w, 400, "conv_id required")
		return
	}
	uids, err := s.svc.OnlineMembers(convID)
	writeJSON(w, map[string]interface{}{"online": uids}, err)
}

// ---- 人与组织 ----

func (s *Server) handleUsers(w http.ResponseWriter, r *http.Request) {
	if q := r.URL.Query().Get("q"); q != "" {
		list, err := s.svc.SearchUsers(q)
		writeJSON(w, list, err)
		return
	}
	list, err := s.svc.ListUsers()
	writeJSON(w, list, err)
}

func (s *Server) handleUser(w http.ResponseWriter, r *http.Request) {
	uid := qInt(r, "uid")
	if uid == 0 {
		writeErr(w, 400, "uid required")
		return
	}
	u, err := s.svc.User(uid)
	if err != nil {
		writeErr(w, 404, "用户不存在")
		return
	}
	writeJSON(w, u, nil)
}

func (s *Server) handleOrgTree(w http.ResponseWriter, r *http.Request) {
	tree, err := s.svc.OrgTree()
	writeJSON(w, map[string]interface{}{"depts": tree}, err)
}

// ---- 上传 / 通知 ----

func (s *Server) handleUpload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, 405, "POST only")
		return
	}
	if err := r.ParseMultipartForm(16 << 20); err != nil {
		writeErr(w, 400, "解析上传失败")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeErr(w, 400, "缺少 file 字段")
		return
	}
	defer file.Close()
	if header.Size > 16<<20 {
		writeErr(w, 400, "文件超过 16MB")
		return
	}
	dir := filepath.Join("web", "uploads")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	ext := filepath.Ext(header.Filename)
	name := fmt.Sprintf("%d_%s%s", time.Now().UnixNano(), randSuffix(), ext)
	dst, err := os.Create(filepath.Join(dir, name))
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	defer dst.Close()
	size, err := io.Copy(dst, file)
	if err != nil {
		writeErr(w, 500, err.Error())
		return
	}
	writeJSON(w, model.Attachment{
		Name: header.Filename,
		Mime: header.Header.Get("Content-Type"),
		Size: size,
		URL:  "/uploads/" + name,
	}, nil)
}

func randSuffix() string {
	b := make([]byte, 4)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func (s *Server) handleNotifications(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	list, err := s.svc.Notifications(uid)
	writeJSON(w, list, err)
}

func (s *Server) handleNotificationsRead(w http.ResponseWriter, r *http.Request) {
	uid, ok := s.requireUID(w, r)
	if !ok {
		return
	}
	writeJSON(w, map[string]bool{"ok": true}, s.svc.MarkNotificationsRead(uid))
}

// ---- 运维 / 演示数据 ----

func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]string{"status": "ok"}, nil)
}

func (s *Server) handleSeed(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, 405, "POST only")
		return
	}
	p, g, err := s.svc.Seed()
	_ = s.svc.SeedOrg()
	writeJSON(w, map[string]int64{"p2p_conv": p, "group_conv": g}, err)
}

func (s *Server) handleSeedBig(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeErr(w, 405, "POST only")
		return
	}
	n, _ := strconv.Atoi(r.URL.Query().Get("n"))
	if n <= 0 {
		n = 50
	}
	g, err := s.svc.SeedBig(n)
	_ = s.svc.SeedOrg()
	writeJSON(w, map[string]interface{}{"group_conv": g, "members": n}, err)
}

func (s *Server) handleSeedOrg(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]bool{"ok": true}, s.svc.SeedOrg())
}

// ---- WebSocket ----

func (s *Server) handleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := s.upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	// 先启动收发协程（才能收到 login），注册入网推迟到登录确定 uid 之后
	c := ws.NewClient(s.svc.Hub(), 0, conn)
	c.Start()
}
