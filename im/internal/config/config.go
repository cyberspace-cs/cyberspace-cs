// Package config 负责从环境变量加载服务配置。
// 设计要点：所有外部依赖（MySQL / Redis / 端口 / 降级阈值）都通过环境变量注入，
// 这样同一份代码在「本地开发」「Docker Compose」「生产服务器」三套环境下无需改码。
package config

import (
	"os"
	"strconv"
)

type Config struct {
	HTTPAddr          string // HTTP + WebSocket 监听地址
	WSPath            string // WebSocket 挂载路径
	MySQLDSN          string // MySQL 数据源（持久化基准源）
	RedisAddr         string // Redis 地址（热点 / 计数 / 回执 / 路由）
	RedisPass         string
	RedisDB           int
	NodeID            string // 单节点标识，用于网关路由（多机部署时区分机器）
	BigGroupThreshold int    // 超大群阈值：超过则回执/离线缓冲降级
	OfflineRingCap    int    // 离线消息环（RingBuffer）保留最近 N 条
	ReceiptDegrade    bool   // 回执是否进入降级模式（优先保收发主链路）
}

func def(k, v string) string {
	if x := os.Getenv(k); x != "" {
		return x
	}
	return v
}

func atoiDef(k string, v int) int {
	if x := os.Getenv(k); x != "" {
		if n, err := strconv.Atoi(x); err == nil {
			return n
		}
	}
	return v
}

// Load 读取配置，未设置时使用教学友好的默认值。
func Load() *Config {
	return &Config{
		HTTPAddr:          def("HTTP_ADDR", ":8080"),
		WSPath:            def("WS_PATH", "/ws"),
		MySQLDSN:          def("MYSQL_DSN", "root:rootpass@tcp(127.0.0.1:3306)/im?parseTime=true&charset=utf8mb4&loc=Local"),
		RedisAddr:         def("REDIS_ADDR", "127.0.0.1:6379"),
		RedisPass:         os.Getenv("REDIS_PASS"),
		RedisDB:           atoiDef("REDIS_DB", 0),
		NodeID:            def("NODE_ID", "node-1"),
		BigGroupThreshold: atoiDef("BIG_GROUP_THRESHOLD", 200),
		OfflineRingCap:    atoiDef("OFFLINE_RING_CAP", 30),
		ReceiptDegrade:    os.Getenv("RECEIPT_DEGRADE") == "1",
	}
}
