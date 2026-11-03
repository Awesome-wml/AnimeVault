#!/bin/bash
# 以调试模式启动 Chrome（可以被 Playwright 连接）

echo "关闭现有 Chrome 进程..."
pkill -x "Google Chrome" 2>/dev/null
sleep 2

echo "以调试模式启动 Chrome..."
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/Library/Application Support/Google/Chrome" \
  > /dev/null 2>&1 &

echo "Chrome 已启动（调试端口: 9222）"
echo "现在可以运行 python3 connect_running_chrome.py 连接"
