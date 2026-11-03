# DongAI 部署指南

## 一、环境要求

- Docker 20.10+
- Docker Compose 2.0+
- 8GB+ 内存
- 20GB+ 磁盘空间

## 二、快速启动（推荐）

### 1. 克隆/准备项目

```bash
cd dongai
```

### 2. 配置环境变量

**后端配置**
```bash
# 已创建 backend/.env，可根据需要修改
# 重要：修改 JWT_SECRET 为随机字符串
```

**前端配置**
```bash
# 已创建 frontend/.env
# 如果后端地址不是 localhost:8000，需要修改 VUE_APP_API_BASE_URL
```

### 3. 启动服务

```bash
# 一键启动所有服务
docker-compose up -d

# 查看启动日志
docker-compose logs -f

# 等待所有服务启动完成（约1-2分钟）
```

### 4. 访问应用

- **前端界面**: http://localhost:8080
- **后端API**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

### 5. 初次使用

1. 打开 http://localhost:8080
2. 点击"注册"创建账号
3. 登录后点击"配置API密钥"
4. 填入豆包API密钥和地址
5. 开始创建项目！

## 三、本地开发模式

### 后端开发

```bash
cd backend

# 创建虚拟环境
python3.13 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动MongoDB和Redis（使用Docker）
docker-compose up -d mongodb redis

# 修改 .env 中的连接地址为 localhost
# MONGODB_URL=mongodb://admin:dongai_mongo_2024@localhost:27017/
# REDIS_URL=redis://localhost:6379/0

# 启动后端
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run serve

# 访问 http://localhost:8080
```

## 四、环境变量说明

### Backend (.env)

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|------|
| MONGODB_URL | MongoDB连接地址 | mongodb://admin:dongai_mongo_2024@mongodb:27017/ | ✅ |
| MONGODB_DB_NAME | 数据库名称 | dongai | ✅ |
| REDIS_URL | Redis连接地址 | redis://redis:6379/0 | ❌ |
| STATIC_DIR | 静态文件目录 | /app/static | ✅ |
| JWT_SECRET | JWT密钥（生产环境必须修改） | dongai-secret-key-change-in-production-2024 | ✅ |
| JWT_ALGORITHM | JWT算法 | HS256 | ✅ |
| JWT_EXPIRE_MINUTES | Token过期时间(分钟) | 43200 (30天) | ✅ |
| CORS_ORIGINS | 允许的跨域源 | http://localhost:8080,http://localhost:3000 | ✅ |

### Frontend (.env)

| 变量名 | 说明 | 默认值 | 必填 |
|--------|------|--------|------|
| VUE_APP_API_BASE_URL | 后端API地址 | http://localhost:8000 | ✅ |

## 五、豆包API配置

### 获取豆包API密钥

1. 访问火山引擎官网：https://console.volcengine.com/ark
2. 注册/登录账号
3. 进入"模型推理"或"方舟"服务
4. 创建API密钥
5. 记录以下信息：
   - API Key（密钥）
   - Endpoint（接入点地址）

### 在系统中配置

1. 登录DongAI系统
2. 点击右上角"配置API密钥"
3. 填入：
   - **API密钥**: 从火山引擎获取的 API Key
   - **API地址**: 通常为 `https://ark.cn-beijing.volces.com/api/v3`
4. 点击保存

**注意**: 
- 每个用户的API密钥独立存储
- 不同用户之间数据完全隔离
- API调用费用由各自的豆包账号承担

## 六、常见问题

### 1. MongoDB连接失败

```bash
# 检查MongoDB是否启动
docker-compose ps mongodb

# 查看MongoDB日志
docker-compose logs mongodb

# 重启MongoDB
docker-compose restart mongodb
```

### 2. Redis连接失败（可忽略）

Redis是可选组件，连接失败不影响主要功能。如需使用：

```bash
# 检查Redis状态
docker-compose ps redis

# 重启Redis
docker-compose restart redis
```

### 3. 前端无法连接后端

检查：
1. 后端是否正常启动: http://localhost:8000/health
2. `.env` 中的 `VUE_APP_API_BASE_URL` 是否正确
3. CORS配置是否包含前端地址

### 4. 图片/音频无法访问

检查：
1. `static/` 目录是否正确挂载
2. 文件权限是否正确
3. 后端日志中是否有文件保存错误

```bash
# 查看static目录
ls -la static/images
ls -la static/audio

# 确保目录可写
chmod -R 755 static/
```

### 5. SSE流式输出失败

1. 检查豆包API密钥是否正确
2. 检查网络连接
3. 查看浏览器Console是否有错误
4. 检查后端日志: `docker-compose logs backend`

## 七、生产环境部署建议

### 1. 安全配置

```bash
# 修改 backend/.env
JWT_SECRET=<生成一个强随机字符串>

# 使用环境变量管理敏感信息
# 不要将 .env 文件提交到版本控制
```

### 2. 性能优化

```yaml
# docker-compose.yml 中为MongoDB增加资源限制
mongodb:
  deploy:
    resources:
      limits:
        memory: 2G
      reservations:
        memory: 1G
```

### 3. 数据备份

```bash
# MongoDB备份
docker exec dongai_mongo mongodump \
  --uri="mongodb://admin:dongai_mongo_2024@localhost:27017" \
  --out=/backup/$(date +%Y%m%d)

# 静态文件备份
tar -czf static_backup_$(date +%Y%m%d).tar.gz static/
```

### 4. 日志管理

```bash
# 查看实时日志
docker-compose logs -f --tail=100

# 查看特定服务日志
docker-compose logs backend
docker-compose logs frontend
docker-compose logs mongodb
```

### 5. 监控

访问健康检查端点:
- Backend: http://localhost:8000/health
- 返回MongoDB和Redis连接状态

## 八、Docker命令速查

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose stop

# 重启服务
docker-compose restart

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止并删除容器
docker-compose down

# 停止并删除容器、网络、卷（慎用！）
docker-compose down -v

# 重新构建镜像
docker-compose build

# 重新构建并启动
docker-compose up -d --build
```

## 九、技术支持

### 架构说明

- **后端**: FastAPI + MongoDB + Redis（可选）
- **前端**: Vue 2 + Element UI + Vuex
- **AI服务**: 豆包大模型（LLM + 文生图 + TTS）
- **存储**: MongoDB（数据） + 本地文件系统（图片/音频）

### 目录结构

```
dongai/
├── backend/          # 后端代码
│   ├── api/         # API路由
│   ├── core/        # 核心逻辑（适配器模式）
│   ├── db/          # 数据库连接
│   ├── models/      # 数据模型
│   ├── utils/       # 工具类
│   └── main.py      # 主入口
├── frontend/        # 前端代码
│   └── src/
│       ├── views/   # 页面组件
│       ├── api/     # API封装
│       ├── router/  # 路由配置
│       └── store/   # Vuex状态管理
├── static/          # 静态文件（持久化）
│   ├── images/      # 生成的图片
│   └── audio/       # 生成的音频
└── docker-compose.yml
```

### 扩展指南

当前版本已预留扩展接口，可方便添加：
1. 其他AI服务商（OpenAI、MiniMax等）
2. 视频生成功能
3. FFmpeg成片合成
4. 更多TTS音色

修改 `backend/core/providers/` 下的适配器即可。

---

**祝您使用愉快！如有问题，请查看日志或提交Issue。**
