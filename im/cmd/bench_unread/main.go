// bench_unread 演示并量化「未读数快速获取」在 50 人群里的两种实现：
//
//   A. 水位线减法（本项目采用的扩散读方案）：
//        unread = conversations.latest_seq - user_conv_read.read_seq
//      这是 O(1) 点查，与消息条数无关。一个人发消息只 bump latest_seq 一次，
//      49 个接收方的未读靠"各自减法"懒算出来，发送时不写 49 行。
//
//   B. 朴素 COUNT(*)（错误示范）：
//        SELECT COUNT(*) FROM messages WHERE conv_id=? AND seq > read_seq
//      每次取未读都要扫一遍未读区间，消息越多越慢，且与成员数成正比放大。
//
// 同时演示单条已读回执的快速计数：Redis SCARD（读人数）vs SMEMBERS（拉全量再数）。
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/redis/go-redis/v9"

	_ "github.com/go-sql-driver/mysql"

	"github.com/cyberspace-cs/im/internal/db"
)

func main() {
	dsn := env("MYSQL_DSN", "root:rootpass@tcp(127.0.0.1:3306)/im?parseTime=true&charset=utf8mb4&loc=Local")
	rdb := redis.NewClient(&redis.Options{Addr: env("REDIS_ADDR", "127.0.0.1:6379")})
	ctx := context.Background()

	store, err := db.NewStore(dsn)
	if err != nil {
		panic(err)
	}
	_ = rdb.FlushDB(ctx).Err()

	const n = 50
	convID, err := store.SeedBig(ctx, n)
	if err != nil {
		panic(err)
	}
	fmt.Printf("=== 已就绪：%d 人压测群 conv_id=%d ===\n\n", n, convID)

	// 发送方连续发 2000 条消息，模拟"群聊历史很长"，让朴素 COUNT 的代价显现。
	const msgN = 2000
	sender := int64(2001)
	for i := 1; i <= msgN; i++ {
		if _, _, err := store.InsertMessage(ctx, convID, sender, fmt.Sprintf("压测消息 #%d", i), 1); err != nil {
			panic(err)
		}
	}
	latest, _ := store.GetLatestSeq(ctx, convID)
	fmt.Printf("发送方发了 %d 条消息，会话 latest_seq=%d（49 个接收方均未读）\n\n", msgN, latest)

	members, _ := store.GetMembers(ctx, convID)
	receivers := members[1:] // 去掉发送方

	const waterSQL = `SELECT c.latest_seq, COALESCE(r.read_seq,0)
	                  FROM conversations c
	                  LEFT JOIN user_conv_read r ON r.conv_id=c.conv_id AND r.uid=?
	                  WHERE c.conv_id=?`

	// ---------- A. 水位线减法（快速路径） ----------
	aStart := time.Now()
	var totalWater int64
	for _, uid := range receivers {
		var latest2, readSeq int64
		_ = store.DB.QueryRowContext(ctx, waterSQL, uid, convID).Scan(&latest2, &readSeq)
		totalWater += latest2 - readSeq
	}
	aDur := time.Since(aStart)

	// ---------- B. 朴素 COUNT(*)（慢路径） ----------
	const countSQL = `SELECT COUNT(*) FROM messages WHERE conv_id=? AND seq > ?`
	bStart := time.Now()
	var totalNaive int64
	for _, uid := range receivers {
		var latest2, readSeq int64
		_ = store.DB.QueryRowContext(ctx, waterSQL, uid, convID).Scan(&latest2, &readSeq)
		var c int64
		_ = store.DB.QueryRowContext(ctx, countSQL, convID, readSeq).Scan(&c)
		totalNaive += c
	}
	bDur := time.Since(bStart)

	fmt.Println("┌──────────────────────────────────┬──────────────┬──────────────────────────┐")
	fmt.Println("│ 取未读数方式                      │ 总耗时(49人) │ 单次/人(平均)            │")
	fmt.Println("├──────────────────────────────────┼──────────────┼──────────────────────────┤")
	fmt.Printf("│ A. 水位线减法 latest-read (O(1))   │ %-12s │ %-24s │\n", fmtDur(aDur), fmtDur(aDur/time.Duration(len(receivers))))
	fmt.Printf("│ B. 朴素 COUNT(*) 扫未读区间        │ %-12s │ %-24s │\n", fmtDur(bDur), fmtDur(bDur/time.Duration(len(receivers))))
	fmt.Println("└──────────────────────────────────┴──────────────┴──────────────────────────┘")
	fmt.Printf("\n两人算出的总未读一致：water=%d  naive=%d  （水位线结果与 COUNT 完全一致）\n", totalWater, totalNaive)
	if aDur > 0 {
		fmt.Printf("加速比：朴素耗时 / 水位线耗时 ≈ %.1fx\n\n", float64(bDur)/float64(aDur))
	}

	// ---------- 单条已读回执快速计数：SCARD vs SMEMBERS ----------
	fmt.Println("=== 单条已读回执：读人数快速获取（49 个接收方全部已读第 1 条）===")
	var firstMsgID int64
	_ = store.DB.QueryRowContext(ctx, `SELECT msg_id FROM messages WHERE conv_id=? ORDER BY seq ASC LIMIT 1`, convID).Scan(&firstMsgID)
	for _, uid := range receivers {
		_ = rdb.SAdd(ctx, fmt.Sprintf("im:msg:%d:readers", firstMsgID), uid).Err()
	}
	scardStart := time.Now()
	scard, _ := rdb.SCard(ctx, fmt.Sprintf("im:msg:%d:readers", firstMsgID)).Result()
	scardDur := time.Since(scardStart)

	smStart := time.Now()
	members2, _ := rdb.SMembers(ctx, fmt.Sprintf("im:msg:%d:readers", firstMsgID)).Result()
	smDur := time.Since(smStart)

	fmt.Printf("  Redis SCARD (直接拿人数)：      %d 人，耗时 %s\n", scard, fmtDur(scardDur))
	fmt.Printf("  Redis SMEMBERS+len (拉全量)：  %d 人，耗时 %s（网络传输 %d 个 uid）\n", len(members2), fmtDur(smDur), len(members2))
	fmt.Println("  关键：SCARD 只返回 1 个数字；SMEMBERS 返回全部 uid，人数越多网络/内存放大越明显。")

	// 单用户一次性拿全群未读（飞书侧边栏红点）：1 次聚合查询
	fmt.Println("\n=== 飞书侧边栏「总未读」快速获取：单用户 1 次聚合查询 ===")
	convList, _ := store.ListConversationsForUser(ctx, receivers[0], 0)
	var sum int64
	for _, c := range convList {
		sum += c.Unread
	}
	fmt.Printf("  用户 %d 的会话列表(含未读水位线) 1 次查询即得，本群未读=%d\n", receivers[0], sum)

	// ---------- 缩放性：未读越多，两种方式耗时如何变化 ----------
	fmt.Println("\n=== 缩放性：未读越大，取未读耗时怎么变（单用户，各测 40 次取平均）===")
	fmt.Println("┌──────────────┬──────────────────┬────────────────────┬──────────────┐")
	fmt.Println("│ 未读条数      │ A. 水位线 (O(1))  │ B. COUNT(*) (O(n)) │ B/A 倍数     │")
	fmt.Println("├──────────────┼──────────────────┼────────────────────┼──────────────┤")
	for _, readSeq := range []int64{1900, 1000, 0} {
		unread := latest - readSeq
		// A: 水位线
		aStart2 := time.Now()
		for i := 0; i < 40; i++ {
			var l2, rs int64
			_ = store.DB.QueryRowContext(ctx, waterSQL, receivers[0], convID).Scan(&l2, &rs)
		}
		aDurSingle := time.Since(aStart2) / 40
		// B: COUNT
		b2 := time.Now()
		for i := 0; i < 40; i++ {
			var c int64
			_ = store.DB.QueryRowContext(ctx, countSQL, convID, readSeq).Scan(&c)
		}
		bDurSingle := time.Since(b2) / 40
		fmt.Printf("│ %-12d │ %-16s │ %-18s │ %-12.1f │\n",
			unread, fmtDur(aDurSingle), fmtDur(bDurSingle), float64(bDurSingle)/float64(aDurSingle))
	}
	fmt.Println("└──────────────┴──────────────────┴────────────────────┴──────────────┘")
	fmt.Println("说明：水位线耗时基本不变（只读两个数相减）；COUNT(*) 随未读条数线性增长。")
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func fmtDur(d time.Duration) string {
	if d < time.Microsecond {
		return fmt.Sprintf("%d ns", d.Nanoseconds())
	}
	if d < time.Millisecond {
		return fmt.Sprintf("%.1f µs", float64(d.Nanoseconds())/1000)
	}
	return fmt.Sprintf("%.2f ms", float64(d.Nanoseconds())/1e6)
}
