// Package api 暴露 HTTP REST 接口与 WebSocket 升级入口。
//
// 路由约定（便于 nginx 在 /im 下反代）：
//   GET  /api/healthz              健康检查
//   GET  /api/conversations?uid=   会话列表（带未读水位线）
//   GET  /api/messages?conv_id=&before_seq=&limit=  拉历史
//   GET  /api/receipt?conv_id=&msg_id=             查某条消息已读回执
//   POST /api/seed                 灌入演示数据
//   GET  /ws                        WebSocket 长连接
//   /*                             静态前端
package api

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/gorilla/websocket"

	"github.com/cyberspace-cs/im/internal/service"
	"github.com/cyberspace-cs/im/internal/ws"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true }, // 教学环境放行跨域
}

// NewServer 构造 HTTP handler（含 REST、WS、静态资源）。
func NewServer(svc *service.Service) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/api/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})

	mux.HandleFunc("/api/conversations", func(w http.ResponseWriter, r *http.Request) {
		uid, _ := strconv.ParseInt(r.URL.Query().Get("uid"), 10, 64)
		if uid == 0 {
			http.Error(w, "uid required", 400)
			return
		}
		list, err := svc.ListConversations(uid)
		writeJSON(w, list, err)
	})

	mux.HandleFunc("/api/users", func(w http.ResponseWriter, r *http.Request) {
		users, err := svc.ListUsers()
		writeJSON(w, users, err)
	})

	mux.HandleFunc("/api/members", func(w http.ResponseWriter, r *http.Request) {
		convID, _ := strconv.ParseInt(r.URL.Query().Get("conv_id"), 10, 64)
		if convID == 0 {
			http.Error(w, "conv_id required", 400)
			return
		}
		members, err := svc.ListMembers(convID)
		writeJSON(w, members, err)
	})

	mux.HandleFunc("/api/messages", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		convID, _ := strconv.ParseInt(q.Get("conv_id"), 10, 64)
		before, _ := strconv.ParseInt(q.Get("before_seq"), 10, 64)
		limit, _ := strconv.Atoi(q.Get("limit"))
		if convID == 0 {
			http.Error(w, "conv_id required", 400)
			return
		}
		msgs, err := svc.PullHistory(convID, before, limit)
		writeJSON(w, msgs, err)
	})

	mux.HandleFunc("/api/receipt", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		convID, _ := strconv.ParseInt(q.Get("conv_id"), 10, 64)
		msgID, _ := strconv.ParseInt(q.Get("msg_id"), 10, 64)
		if convID == 0 || msgID == 0 {
			http.Error(w, "conv_id & msg_id required", 400)
			return
		}
		rc, err := svc.Receipt(convID, msgID)
		writeJSON(w, rc, err)
	})

	mux.HandleFunc("/api/seed", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", 405)
			return
		}
		p, g, err := svc.Seed()
		writeJSON(w, map[string]int64{"p2p_conv": p, "group_conv": g}, err)
	})

	mux.HandleFunc("/api/seed_big", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", 405)
			return
		}
		n, _ := strconv.Atoi(r.URL.Query().Get("n"))
		if n <= 0 {
			n = 50
		}
		g, err := svc.SeedBig(n)
		writeJSON(w, map[string]interface{}{"group_conv": g, "members": n}, err)
	})

	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		// 先启动收发协程（才能收到 login），注册入网推迟到登录确定 uid 之后
		c := ws.NewClient(svc.Hub(), 0, conn)
		c.Start()
	})

	// 静态前端
	mux.Handle("/", http.FileServer(http.Dir("web")))
	return mux
}

func writeJSON(w http.ResponseWriter, v interface{}, err error) {
	w.Header().Set("Content-Type", "application/json")
	if err != nil {
		w.WriteHeader(500)
		_, _ = w.Write([]byte(`{"error":"` + err.Error() + `"}`))
		return
	}
	b, _ := json.Marshal(v)
	_, _ = w.Write(b)
}
