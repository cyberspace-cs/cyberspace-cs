#!/usr/bin/env bash
# 飞书式 IM 一键部署脚本（需具备目标服务器的 SSH 访问权限）。
# 前置：服务器已装 docker / docker-compose / nginx。
#
# 用法：
#   DEPLOY_KEY=~/.ssh/id_ed25519_audit_server bash deploy.sh
#
# 说明：当前沙箱没有该私钥，故本脚本已写好但暂未执行；
#      你提供私钥（或把密钥放到 ~/.ssh/id_ed25519_audit_server）后即可一键上线。
set -e

SERVER="${DEPLOY_SERVER:-ubuntu@43.143.231.106}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/id_ed25519_audit_server}"
APP_DIR="${DEPLOY_DIR:-/opt/cyberspace-cs}"

echo "==> 同步代码到 $SERVER:$APP_DIR"
rsync -avz --delete -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
  --exclude '.git' --exclude 'mysql-data' ./ "$SERVER:$APP_DIR"

echo "==> 在服务器上构建并启动（MySQL+Redis+App）"
ssh -i "$KEY" -o StrictHostKeyChecking=no "$SERVER" bash -s <<EOF
  set -e
  cd $APP_DIR
  docker compose down || true
  docker compose up -d --build
  # 反代 /im -> 本地 8080
  if command -v nginx >/dev/null 2>&1; then
    cp nginx.conf /etc/nginx/conf.d/im.conf
    nginx -t && systemctl reload nginx
  else
    echo "nginx 未安装；可直接访问 http://43.143.231.106:8080/ "
  fi
  echo "==> 部署完成：http://taoxie.vip/im/  (或 http://43.143.231.106:8080/)"
EOF
