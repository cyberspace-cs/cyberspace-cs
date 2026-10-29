// Package api 暴露 HTTP REST 接口与 WebSocket 升级入口。
//
// 路由约定（全部挂在 /api 下，便于 nginx 在 /im 前缀反代）：
//
//	POST /api/auth/login            换取 token（教学版：选身份即登录）
//	POST /api/auth/logout
//	GET  /api/auth/me               当前身份
//
//	GET  /api/conversations         会话列表（置顶/免打扰/@我/未读）
//	POST /api/conversations         建单聊或群聊
//	POST /api/conversations/members 加人 / 踢人 / 退群
//	POST /api/conversations/settings 置顶 / 免打扰 / 标记未读
//
//	GET  /api/messages              before_seq 往前翻 / after_seq 增量拉
//	POST /api/messages/recall       撤回（2 分钟内）
//	POST /api/messages/reaction     表情回应
//	POST /api/messages/forward      转发
//
//	GET  /api/receipt               已读回执（支持分页）
//	GET  /api/unread/summary        未读汇总（图标红点 + tab 计数）
//	GET  /api/search                全局搜索
//	GET  /api/mentions              @我的消息
//	GET  /api/read/state            多端已读位置
//
//	GET  /api/user                  用户名片
//	GET  /api/org/tree              组织架构树
//	GET  /api/presence              会话内在线成员
//
//	POST /api/upload                图片 / 文件上传
//	GET  /api/notifications         通知中心
//	POST /api/notifications/read    全部已读
//
//	GET  /api/healthz               健康检查
//	GET  /ws                        WebSocket 长连接
//	/*                              静态前端
package api

import (
	"net/http"

	"github.com/gorilla/websocket"

	"github.com/cyberspace-cs/im/internal/service"
)

// Server 持有业务层，路由与 handler 都是它的方法。
type Server struct {
	svc      *service.Service
	upgrader websocket.Upgrader
}

// NewServer 构造 HTTP handler（含 REST、WS、静态资源）。
func NewServer(svc *service.Service) http.Handler {
	s := &Server{
		svc: svc,
		upgrader: websocket.Upgrader{
			ReadBufferSize:  4096,
			WriteBufferSize: 4096,
			// 教学环境放行跨域；生产应校验 Origin 白名单
			CheckOrigin: func(r *http.Request) bool { return true },
		},
	}

	mux := http.NewServeMux()

	// 认证
	mux.HandleFunc("/api/auth/login", s.handleLogin)
	mux.HandleFunc("/api/auth/logout", s.handleLogout)
	mux.HandleFunc("/api/auth/me", s.handleMe)

	// 会话
	mux.HandleFunc("/api/conversations", s.handleConversations)
	mux.HandleFunc("/api/conversations/members", s.handleConvMembers)
	mux.HandleFunc("/api/conversations/settings", s.handleConvSettings)
	mux.HandleFunc("/api/members", s.handleMembers)

	// 消息
	mux.HandleFunc("/api/messages", s.handleMessages)
	mux.HandleFunc("/api/messages/recall", s.handleRecall)
	mux.HandleFunc("/api/messages/reaction", s.handleReaction)
	mux.HandleFunc("/api/messages/forward", s.handleForward)
	mux.HandleFunc("/api/receipt", s.handleReceipt)

	// 聚合查询
	mux.HandleFunc("/api/unread/summary", s.handleUnreadSummary)
	mux.HandleFunc("/api/search", s.handleSearch)
	mux.HandleFunc("/api/mentions", s.handleMentions)
	mux.HandleFunc("/api/read/state", s.handleReadState)
	mux.HandleFunc("/api/presence", s.handlePresence)

	// 人与组织
	mux.HandleFunc("/api/users", s.handleUsers)
	mux.HandleFunc("/api/user", s.handleUser)
	mux.HandleFunc("/api/org/tree", s.handleOrgTree)

	// 上传 / 通知
	mux.HandleFunc("/api/upload", s.handleUpload)
	mux.HandleFunc("/api/notifications", s.handleNotifications)
	mux.HandleFunc("/api/notifications/read", s.handleNotificationsRead)

	// 运维 / 演示数据
	mux.HandleFunc("/api/healthz", s.handleHealthz)
	mux.HandleFunc("/api/seed", s.handleSeed)
	mux.HandleFunc("/api/seed_big", s.handleSeedBig)
	mux.HandleFunc("/api/seed_org", s.handleSeedOrg)

	// WebSocket
	mux.HandleFunc("/ws", s.handleWS)

	// 静态前端
	mux.Handle("/", http.FileServer(http.Dir("web")))
	return mux
}
