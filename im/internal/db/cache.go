// Package db 同时封装 Redis（热点 / 计数 / 回执 / 路由）。
//
// 飞书式 B 端 IM 的 Redis 职责（对照你给的大厂对比）：
//  - 水位线：String 缓存会话 latest_seq 与用户 read_seq（旁路缓存，最终一致）。
//  - 单条已读回执：Set  msg:{msgId}:readers 存已读 uid；Bitmap 批量统计已读人数。
//  - 离线消息：List 环形缓冲，只保留最近 N 条（用户上线时快速补推）。
//  - 网关路由：Set  user:{uid}:gateways 记录用户当前连在哪台机器，用于跨节点投递。
//  - 投递总线：Pub/Sub 频道 im:user:{uid}，多机部署时把消息广播到持有该用户的节点。
package db

import (
	"context"
	"fmt"
	"strconv"

	"github.com/redis/go-redis/v9"
)

// Cache 包裹 *redis.Client。
type Cache struct {
	RDB *redis.Client
	cap int // 离线环容量
}

func NewCache(addr, pass string, db, cap int) *Cache {
	rdb := redis.NewClient(&redis.Options{Addr: addr, Password: pass, DB: db})
	return &Cache{RDB: rdb, cap: cap}
}

func (c *Cache) Ping(ctx context.Context) error { return c.RDB.Ping(ctx).Err() }

// ---- key 构造 ----

func latestKey(convID int64) string  { return fmt.Sprintf("im:conv:%d:latest", convID) }
func readKey(uid, convID int64) string { return fmt.Sprintf("im:user:%d:conv:%d:read", uid, convID) }
func readersKey(msgID int64) string   { return fmt.Sprintf("im:msg:%d:readers", msgID) }
func rbKey(msgID int64) string        { return fmt.Sprintf("im:msg:%d:rb", msgID) }
func midxKey(convID int64) string     { return fmt.Sprintf("im:conv:%d:midx", convID) }
func offlineKey(uid, convID int64) string { return fmt.Sprintf("im:user:%d:offline:%d", uid, convID) }
func gatewayKey(uid int64) string     { return fmt.Sprintf("im:user:%d:gateways", uid) }
func userChan(uid int64) string       { return fmt.Sprintf("im:user:%d", uid) }

// ---- 水位线 ----

func (c *Cache) SetLatestSeq(ctx context.Context, convID, seq int64) {
	c.RDB.Set(ctx, latestKey(convID), seq, 0)
}
func (c *Cache) GetLatestSeq(ctx context.Context, convID int64) int64 {
	v, _ := c.RDB.Get(ctx, latestKey(convID)).Int64()
	return v
}
func (c *Cache) SetReadSeq(ctx context.Context, uid, convID, seq int64) {
	c.RDB.Set(ctx, readKey(uid, convID), seq, 0)
}
func (c *Cache) GetReadSeq(ctx context.Context, uid, convID int64) int64 {
	v, _ := c.RDB.Get(ctx, readKey(uid, convID)).Int64()
	return v
}

// ---- 单条已读回执（飞书招牌） ----

// MemberIndex 为会话成员分配稳定 bit 位（Bitmap 统计用）。
func (c *Cache) MemberIndex(ctx context.Context, convID, uid int64) int64 {
	key := midxKey(convID)
	if v, err := c.RDB.HGet(ctx, key, strconv.FormatInt(uid, 10)).Int64(); err == nil {
		return v
	}
	n, _ := c.RDB.HLen(ctx, key).Result()
	c.RDB.HSet(ctx, key, strconv.FormatInt(uid, 10), n)
	return n
}

// MarkReader 把 uid 加入某条消息的读者集合，并返回最新读者列表与人数。
// 同时写 Set（列头像用）与 Bitmap（批量统计人数，群大时替代 SMEMBERS 省内存）。
func (c *Cache) MarkReader(ctx context.Context, msgID, convID, uid int64) ([]int64, int64, error) {
	sk, bk := readersKey(msgID), rbKey(msgID)
	added, err := c.RDB.SAdd(ctx, sk, uid).Result()
	if err != nil {
		return nil, 0, err
	}
	if added > 0 {
		idx := c.MemberIndex(ctx, convID, uid)
		c.RDB.SetBit(ctx, bk, int64(idx), 1)
	}
	members, err := c.RDB.SMembers(ctx, sk).Result()
	if err != nil {
		return nil, 0, err
	}
	// 群很大时 BITCOUNT 比 SMEMBERS 更省：这里两者都给，上层按需取
	count, _ := c.RDB.BitCount(ctx, bk, &redis.BitCount{Start: 0, End: -1}).Result()
	readers := make([]int64, 0, len(members))
	for _, m := range members {
		if u, e := strconv.ParseInt(m, 10, 64); e == nil {
			readers = append(readers, u)
		}
	}
	if count > 0 {
		return readers, count, nil
	}
	return readers, int64(len(readers)), nil
}

func (c *Cache) GetReaders(ctx context.Context, msgID int64) ([]int64, int64, error) {
	members, err := c.RDB.SMembers(ctx, readersKey(msgID)).Result()
	if err != nil {
		return nil, 0, err
	}
	readers := make([]int64, 0, len(members))
	for _, m := range members {
		if u, e := strconv.ParseInt(m, 10, 64); e == nil {
			readers = append(readers, u)
		}
	}
	return readers, int64(len(readers)), nil
}

// ---- 离线消息环（RingBuffer） ----

func (c *Cache) PushOffline(ctx context.Context, uid, convID, msgID int64) {
	key := offlineKey(uid, convID)
	c.RDB.LPush(ctx, key, msgID)
	c.RDB.LTrim(ctx, key, 0, int64(c.cap-1)) // 只留最近 cap 条
}

// PopOffline 取走并清空某会话的离线消息 id 列表。
func (c *Cache) PopOffline(ctx context.Context, uid, convID int64) ([]int64, error) {
	key := offlineKey(uid, convID)
	ids, err := c.RDB.LRange(ctx, key, 0, int64(c.cap-1)).Result()
	if err != nil {
		return nil, err
	}
	c.RDB.Del(ctx, key)
	out := make([]int64, 0, len(ids))
	for _, s := range ids {
		if v, e := strconv.ParseInt(s, 10, 64); e == nil {
			out = append(out, v)
		}
	}
	return out, nil
}

// ---- 网关路由 / 在线状态 ----

func (c *Cache) AddGateway(ctx context.Context, uid int64, nodeID string) {
	c.RDB.SAdd(ctx, gatewayKey(uid), nodeID)
}
func (c *Cache) RemoveGateway(ctx context.Context, uid int64, nodeID string) {
	c.RDB.SRem(ctx, gatewayKey(uid), nodeID)
}
func (c *Cache) IsOnline(ctx context.Context, uid int64) bool {
	n, _ := c.RDB.SCard(ctx, gatewayKey(uid)).Result()
	return n > 0
}

// ---- Pub/Sub 投递总线 ----

func (c *Cache) PublishUser(ctx context.Context, uid int64, payload []byte) {
	c.RDB.Publish(ctx, userChan(uid), payload)
}

// NewPubSub 返回一个订阅用的 PubSub 客户端（Hub 用来收跨节点消息）。
func (c *Cache) NewPubSub() *redis.PubSub {
	return c.RDB.Subscribe(context.Background())
}
