// 临时端到端冒烟测试：验证飞书式已读回执全链路。
// 用法：go run ./cmd/smoke  （依赖已运行的 IM 服务 :8080）
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/cyberspace-cs/im/internal/model"
	"github.com/cyberspace-cs/im/internal/protocol"
	"github.com/gorilla/websocket"
)

type client struct {
	uid int64
	ws  *websocket.Conn
	in  chan protocol.Envelope
}

func dial(uid int64) *client {
	ws, _, err := websocket.DefaultDialer.Dial("ws://127.0.0.1:8080/ws", http.Header{})
	if err != nil {
		panic(err)
	}
	c := &client{uid: uid, ws: ws, in: make(chan protocol.Envelope, 128)}
	c.ws.WriteJSON(protocol.Envelope{
		Type: protocol.TypeLogin,
		Data: must(json.Marshal(protocol.LoginReq{UID: uid})),
	})
	go func() {
		for {
			_, b, err := ws.ReadMessage()
			if err != nil {
				return
			}
			var e protocol.Envelope
			if json.Unmarshal(b, &e) == nil {
				c.in <- e
			}
		}
	}()
	return c
}

func (c *client) send(typ string, v interface{}) {
	data, _ := json.Marshal(v)
	c.ws.WriteJSON(protocol.Envelope{Type: typ, Data: data})
}

func must(b []byte, err error) json.RawMessage {
	if err != nil {
		panic(err)
	}
	return b
}

func drain(c *client, d time.Duration) {
	timeout := time.After(d)
	for {
		select {
		case <-c.in:
		case <-timeout:
			return
		}
	}
}

func expectType(c *client, typ string, d time.Duration) protocol.Envelope {
	timeout := time.After(d)
	for {
		select {
		case e := <-c.in:
			if e.Type == typ {
				return e
			}
		case <-timeout:
			panic(fmt.Sprintf("timeout waiting %s for uid %d", typ, c.uid))
		}
	}
}

func main() {
	alice := dial(1001)
	bob := dial(1002)
	carol := dial(1003)
	time.Sleep(800 * time.Millisecond)
	drain(alice, 600*time.Millisecond)
	drain(bob, 600*time.Millisecond)
	drain(carol, 600*time.Millisecond)

	// Alice 在群聊(conv 2)发一条消息
	alice.send(protocol.TypeSend, protocol.SendReq{ConvID: 2, Content: "hello from alice @group"})
	bm := expectType(bob, protocol.TypeMessage, 3*time.Second)
	cm := expectType(carol, protocol.TypeMessage, 3*time.Second)
	var msg model.Message
	_ = json.Unmarshal(bm.Data, &msg)
	fmt.Printf("[OK] Bob 收到消息: #%d \"%s\"\n", msg.Seq, msg.Content)
	_ = cm

	// Bob 已读（按区间批量，会为 msg1/2/3 各发一份回执）
	bob.send(protocol.TypeRead, protocol.ReadReq{ConvID: 2, Seq: msg.Seq})
	// Carol 已读
	carol.send(protocol.TypeRead, protocol.ReadReq{ConvID: 2, Seq: msg.Seq})

	// 只关注本测试发出的那条消息(msg.MsgID)的回执，确认 Bob & Carol 都进了读者集合
	want := msg.MsgID
	gotBob, gotCarol := false, false
	deadline := time.After(5 * time.Second)
	for !(gotBob && gotCarol) {
		select {
		case e := <-alice.in:
			if e.Type != protocol.TypeReceipt {
				continue
			}
			var r model.Receipt
			_ = json.Unmarshal(e.Data, &r)
			if r.MsgID != want {
				continue
			}
			fmt.Printf("[receipt] msg=%d read_count=%d total=%d readers=%v\n", r.MsgID, r.ReadCount, r.Total, r.Readers)
			for _, u := range r.Readers {
				if u == 1002 {
					gotBob = true
				}
				if u == 1003 {
					gotCarol = true
				}
			}
		case <-deadline:
			goto done
		}
	}
done:
	if gotBob && gotCarol {
		fmt.Println("=== PASS: 飞书式单条已读回执全链路验证通过（Bob+Carol 均出现在读者列表）===")
	} else {
		panic(fmt.Sprintf("FAIL: 回执读者不完整 bob=%v carol=%v", gotBob, gotCarol))
	}
}
