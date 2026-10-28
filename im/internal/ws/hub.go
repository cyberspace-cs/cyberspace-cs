package ws

import (
	"context"
	"strconv"
	"strings"

	"github.com/cyberspace-cs/im/internal/db"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
)

// MessageHandler 由业务层（service）实现，处理一条客户端消息。
// 这样 ws 包不反向依赖 service，避免循环引用。
type MessageHandler interface {
	Handle(c *Client, payload []byte)
}

// Delivery 一条待投递消息（经 pub/sub 或本地产生）。
type Delivery struct {
	UID     int64
	Payload []byte
}

// Hub 管理所有本地连接，并通过 Redis Pub/Sub 实现跨节点投递。
type Hub struct {
	cache   *db.Cache
	nodeID  string
	handler MessageHandler

	clients     map[int64]map[*Client]bool // uid -> 该用户在本机的连接集合
	regCount   map[int64]int               // 订阅计数（每个 uid 只订阅一次 pubsub 频道）
	register   chan *Client
	unregister chan *Client
	deliver    chan *Delivery

	ps         *redis.PubSub
	subscribed map[string]bool
	ctx        context.Context
	cancel     context.CancelFunc
}

func NewHub(cache *db.Cache, nodeID string) *Hub {
	ctx, cancel := context.WithCancel(context.Background())
	h := &Hub{
		cache:      cache,
		nodeID:     nodeID,
		clients:    make(map[int64]map[*Client]bool),
		regCount:   make(map[int64]int),
		register:   make(chan *Client, 256),
		unregister: make(chan *Client, 256),
		deliver:    make(chan *Delivery, 1024),
		ps:         cache.NewPubSub(),
		subscribed: make(map[string]bool),
		ctx:        ctx,
		cancel:     cancel,
	}
	return h
}

func (h *Hub) SetHandler(mh MessageHandler) { h.handler = mh }

// Register 由业务层在「登录、uid 确定后」调用，把一个连接交给 Hub 管理。
// 注意：readPump / writePump 在 HTTP 升级处即启动，这里只做注册入网。
func (h *Hub) Register(c *Client) {
	h.register <- c
}

// Deliver 业务层调用：把 payload 投递给指定 uid（经 pub/sub 广播到所有节点）。
func (h *Hub) Deliver(uid int64, payload []byte) {
	h.cache.PublishUser(h.ctx, uid, payload)
}

func (h *Hub) Run() {
	// 后台接收 pub/sub 消息，转成 Delivery 交给主循环统一投递
	go func() {
		for {
			msg, err := h.ps.ReceiveMessage(h.ctx)
			if err != nil {
				if h.ctx.Err() != nil {
					return
				}
				continue
			}
			uid, ok := parseUserChan(msg.Channel)
			if !ok {
				continue
			}
			h.deliver <- &Delivery{UID: uid, Payload: []byte(msg.Payload)}
		}
	}()

	for {
		select {
		case c := <-h.register:
			h.addClient(c)
		case c := <-h.unregister:
			h.removeClient(c)
		case d := <-h.deliver:
			h.dispatch(d)
		case <-h.ctx.Done():
			return
		}
	}
}

func (h *Hub) addClient(c *Client) {
	set, ok := h.clients[c.UID]
	if !ok {
		set = make(map[*Client]bool)
		h.clients[c.UID] = set
	}
	set[c] = true
	h.regCount[c.UID]++
	if h.regCount[c.UID] == 1 {
		ch := userChan(c.UID)
		if !h.subscribed[ch] {
			_ = h.ps.Subscribe(h.ctx, ch)
			h.subscribed[ch] = true
		}
	}
	// 记录网关路由：用户连到了本节点
	h.cache.AddGateway(h.ctx, c.UID, h.nodeID)
}

func (h *Hub) removeClient(c *Client) {
	set, ok := h.clients[c.UID]
	if !ok {
		return
	}
	if set[c] {
		delete(set, c)
		h.regCount[c.UID]--
	}
	if len(set) == 0 {
		delete(h.clients, c.UID)
		ch := userChan(c.UID)
		if h.regCount[c.UID] <= 0 {
			if h.subscribed[ch] {
				_ = h.ps.Unsubscribe(h.ctx, ch)
				delete(h.subscribed, ch)
			}
			delete(h.regCount, c.UID)
			h.cache.RemoveGateway(h.ctx, c.UID, h.nodeID)
		}
	}
}

func (h *Hub) dispatch(d *Delivery) {
	set := h.clients[d.UID]
	for c := range set {
		c.Send(d.Payload)
	}
}

func (h *Hub) Stop() { h.cancel() }

// ---- helpers ----

func userChan(uid int64) string { return "im:user:" + strconv.FormatInt(uid, 10) }

func parseUserChan(ch string) (int64, bool) {
	if !strings.HasPrefix(ch, "im:user:") {
		return 0, false
	}
	uid, err := strconv.ParseInt(strings.TrimPrefix(ch, "im:user:"), 10, 64)
	if err != nil {
		return 0, false
	}
	return uid, true
}

// NewClient 构造一个已绑定 uid 的 Client。
func NewClient(hub *Hub, uid int64, conn *websocket.Conn) *Client {
	return &Client{UID: uid, hub: hub, conn: conn, send: make(chan []byte, 64)}
}
