// 飞书式 IM 教学服务入口。
//
// 启动顺序：加载配置 -> 连 MySQL(建表/灌种子) -> 连 Redis -> 起 Hub(WS 网关) -> 起 HTTP。
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/cyberspace-cs/im/internal/api"
	"github.com/cyberspace-cs/im/internal/config"
	"github.com/cyberspace-cs/im/internal/db"
	"github.com/cyberspace-cs/im/internal/service"
	"github.com/cyberspace-cs/im/internal/ws"
)

func main() {
	cfg := config.Load()

	store, err := db.NewStore(cfg.MySQLDSN)
	if err != nil {
		log.Fatalf("mysql init: %v", err)
	}
	if _, _, err := store.SeedDemo(context.Background()); err != nil {
		log.Printf("warn: seed demo: %v", err)
	}

	cache := db.NewCache(cfg.RedisAddr, cfg.RedisPass, cfg.RedisDB, cfg.OfflineRingCap)
	if err := cache.Ping(context.Background()); err != nil {
		log.Fatalf("redis ping: %v", err)
	}

	hub := ws.NewHub(cache, cfg.NodeID)
	svc := service.New(store, cache, hub, cfg)
	hub.SetHandler(svc)

	go hub.Run()

	srv := &http.Server{
		Addr:    cfg.HTTPAddr,
		Handler: api.NewServer(svc),
	}
	go func() {
		log.Printf("IM server listening on %s  (ws=%s)", cfg.HTTPAddr, cfg.WSPath)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http server: %v", err)
		}
	}()

	// 优雅退出
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	log.Println("shutting down...")
	hub.Stop()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = srv.Shutdown(ctx)
}
