# 🚀 DongAI 快速参考卡片

## 一分钟启动

```bash
docker-compose up -d
```

访问: **http://localhost:8080**

---

## 核心命令

| 命令 | 说明 |
|------|------|
| `docker-compose up -d` | 启动所有服务 |
| `docker-compose down` | 停止所有服务 |
| `docker-compose logs -f` | 查看实时日志 |
| `docker-compose ps` | 查看服务状态 |
| `docker-compose restart` | 重启服务 |

---

## 服务地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端界面 | http://localhost:8080 | Vue2应用 |
| 后端API | http://localhost:8000 | FastAPI |
| API文档 | http://localhost:8000/docs | Swagger UI |
| 健康检查 | http://localhost:8000/health | 服务状态 |

---

## 目录结构

```
dongai/
├── backend/          # FastAPI后端
├── frontend/         # Vue2前端
├── static/           # 静态文件（图片/音频）
├── docker-compose.yml
└── *.md             # 文档
```

---

## 配置文件

| 文件 | 说明 |
|------|------|
| `backend/.env` | 后端环境变量（JWT密钥、数据库地址） |
| `frontend/.env` | 前端环境变量（API地址） |

---

## 使用流程

```
1. 注册账号
   ↓
2. 配置豆包API密钥
   ↓
3. 创建项目
   ↓
4. 生成小说（SSE流式）
   ↓
5. 提取角色（AI自动识别）
   ↓
6. 拆分分镜（AI自动拆分）
   ↓
7. 生成图片（文生图）
   ↓
8. 生成配音（TTS）
   ↓
9. 导出SRT字幕
```

---

## 常见问题

### Q: 启动失败？
```bash
# 检查端口占用
lsof -i :8000
lsof -i :8080
lsof -i :27017

# 查看日志
docker-compose logs
```

### Q: 无法访问前端？
- 确认Docker容器已启动: `docker-compose ps`
- 检查浏览器地址是否正确: http://localhost:8080

### Q: API调用失败？
1. 检查豆包API密钥是否配置
2. 检查账户余额是否充足
3. 查看后端日志: `docker-compose logs backend`

---

## 技术栈速查

### 后端
- Python 3.13 + FastAPI
- MongoDB (Motor)
- Redis (可选)
- JWT + bcrypt

### 前端
- Vue 2 + Element UI
- Vuex + Vue Router
- Axios

### AI服务
- 豆包大模型（LLM）
- 豆包文生图
- 豆包TTS

---

## 文档索引

- 📖 [START.md](./START.md) - 快速启动（3步）
- 📘 [DEPLOYMENT.md](./DEPLOYMENT.md) - 详细部署
- 📗 [USAGE.md](./USAGE.md) - 使用教程
- 📙 [PROJECT_STRUCTURE.md](./PROJECT_STRUCTURE.md) - 项目结构
- 📕 [PROJECT_SUMMARY.md](./PROJECT_SUMMARY.md) - 交付总结

---

## 环境检查

```bash
# 运行环境检查脚本
bash check.sh
```

---

## 数据备份

```bash
# MongoDB备份
docker exec dongai_mongo mongodump \
  --uri="mongodb://admin:dongai_mongo_2024@localhost:27017" \
  --out=/backup/$(date +%Y%m%d)

# 静态文件备份
tar -czf static_backup_$(date +%Y%m%d).tar.gz static/
```

---

## 端口说明

| 端口 | 服务 |
|------|------|
| 8080 | 前端 |
| 8000 | 后端 |
| 27017 | MongoDB |
| 6379 | Redis |

---

## 重要提醒

⚠️ **生产环境必须修改**:
- `backend/.env` 中的 `JWT_SECRET`

⚠️ **首次使用必须配置**:
- 登录后配置豆包API密钥

⚠️ **注意事项**:
- 确保static/目录有写权限
- Redis连接失败不影响主功能
- 首次启动需要1-2分钟

---

**🎉 准备好了！开始创作吧！**
