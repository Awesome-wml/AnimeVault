#!/bin/bash

echo "========================================="
echo "  DongAI 环境检查工具"
echo "========================================="
echo ""

# 检查Docker
echo "🔍 检查Docker..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version)
    echo "✅ Docker已安装: $DOCKER_VERSION"
else
    echo "❌ Docker未安装"
    echo "   请访问: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查Docker Compose
echo ""
echo "🔍 检查Docker Compose..."
if command -v docker-compose &> /dev/null; then
    COMPOSE_VERSION=$(docker-compose --version)
    echo "✅ Docker Compose已安装: $COMPOSE_VERSION"
else
    echo "❌ Docker Compose未安装"
    echo "   请访问: https://docs.docker.com/compose/install/"
    exit 1
fi

# 检查端口占用
echo ""
echo "🔍 检查端口占用..."
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo "⚠️  端口 $1 已被占用"
        lsof -Pi :$1 -sTCP:LISTEN
        return 1
    else
        echo "✅ 端口 $1 可用"
        return 0
    fi
}

ALL_PORTS_OK=true
check_port 8000 || ALL_PORTS_OK=false
check_port 8080 || ALL_PORTS_OK=false
check_port 27017 || ALL_PORTS_OK=false
check_port 6379 || ALL_PORTS_OK=false

if [ "$ALL_PORTS_OK" = false ]; then
    echo ""
    echo "⚠️  警告: 部分端口被占用，可能导致启动失败"
    echo "   解决方案:"
    echo "   1. 停止占用端口的进程"
    echo "   2. 修改 docker-compose.yml 中的端口映射"
fi

# 检查目录结构
echo ""
echo "🔍 检查目录结构..."
if [ -d "backend" ] && [ -d "frontend" ] && [ -d "static" ]; then
    echo "✅ 目录结构完整"
else
    echo "❌ 目录结构不完整"
    exit 1
fi

# 检查必要文件
echo ""
echo "🔍 检查配置文件..."
if [ -f "backend/.env" ] && [ -f "frontend/.env" ] && [ -f "docker-compose.yml" ]; then
    echo "✅ 配置文件完整"
else
    echo "❌ 配置文件缺失"
    exit 1
fi

# 显示配置信息
echo ""
echo "========================================="
echo "  配置摘要"
echo "========================================="
echo ""
echo "📁 项目目录: $(pwd)"
echo "🔧 后端端口: 8000"
echo "🎨 前端端口: 8080"
echo "💾 MongoDB端口: 27017"
echo "🔴 Redis端口: 6379"
echo ""
echo "📝 环境文件:"
echo "   - backend/.env"
echo "   - frontend/.env"
echo ""
echo "========================================="
echo "  检查完成！"
echo "========================================="
echo ""
echo "✅ 所有检查通过，可以启动服务了！"
echo ""
echo "启动命令："
echo "  docker-compose up -d"
echo ""
echo "查看日志："
echo "  docker-compose logs -f"
echo ""
echo "访问地址："
echo "  前端: http://localhost:8080"
echo "  后端: http://localhost:8000/docs"
echo ""
