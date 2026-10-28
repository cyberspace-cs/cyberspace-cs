// Package ws 实现 WebSocket 长连接层（网关）。
//
// 多机部署时，一个用户只连在某台机器上。要给他推消息，需要：
//  1) 通过 Redis Set 记录「用户连在哪台机器」(gateways)；
//  2) 通过 Redis Pub/Sub 频道 im:user:{uid} 把消息广播给所有机器；
//  3) 持有该用户连接的机器收到后，转发给本地连接。
// 单机能跑，多机也能横向扩展 —— 这是大厂 IM 网关的标准做法。
package ws

import (
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// Client 表示一个 WebSocket 连接（已绑定 uid）。
type Client struct {
	UID  int64
	hub  *Hub
	conn *websocket.Conn
	send chan []byte

	regMu      sync.Mutex
	registered bool // 仅登录(确定 uid)后才向 Hub 注册，避免以 uid=0 入网
}

const writeWait = 10 * time.Second

func (c *Client) readPump() {
	defer func() {
		c.hub.unregister <- c
		_ = c.conn.Close()
	}()
	c.conn.SetReadLimit(1 << 20)
	for {
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			break
		}
		// 交给上层业务处理（service 实现 MessageHandler）
		if c.hub.handler != nil {
			c.hub.handler.Handle(c, message)
		}
	}
}

func (c *Client) writePump() {
	for payload := range c.send {
		_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))
		if err := c.conn.WriteMessage(websocket.TextMessage, payload); err != nil {
			return
		}
	}
}

// Send 向本连接推送一帧（线程安全，走 channel）。
func (c *Client) Send(b []byte) {
	c.send <- b
}

// Start 启动收发协程（在 HTTP 升级处调用，先于登录）。
func (c *Client) Start() {
	go c.readPump()
	go c.writePump()
}

// Register 仅在登录、uid 确定后调用一次，把连接交给 Hub 管理。
// 用 regMu 保证幂等，防止重复注册导致网关计数错乱。
func (c *Client) Register(h *Hub) {
	c.regMu.Lock()
	if c.registered {
		c.regMu.Unlock()
		return
	}
	c.registered = true
	c.regMu.Unlock()
	h.register <- c
}
