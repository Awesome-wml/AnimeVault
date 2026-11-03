# DongAI - AI短剧工作台

对标梦源AI的前后端分离短剧创作平台，支持多用户协作，集成豆包大模型。

## 技术栈

**后端**
- Python 3.13 + FastAPI
- MongoDB (motor异步驱动)
- Redis (可选)
- 豆包大模型 + 文生图 + TTS

**前端**
- Vue 2 + Vue Router + Vuex
- Element UI

## 功能特性

- ✅ 多用户注册登录，数据隔离
- ✅ 项目管理（新建/编辑/删除）
- ✅ AI小说生成（SSE流式输出，支持万字长文）
- ✅ 角色管理（AI提取角色，绑定TTS音色）
- ✅ 分镜工作台（可视化表格编辑）
- ✅ 文生图（豆包文生图API）
- ✅ TTS配音（豆包TTS + SRT字幕生成）

## 快速启动

### 1. 创建静态文件目录

```bash
mkdir -p static/images static/audio
touch static/images/.gitkeep static/audio/.gitkeep
```

### 2. 配置环境变量

**后端配置 (backend/.env)**
```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env 填入必要配置
```

**前端配置 (frontend/.env)**
```bash
cp frontend/.env.example frontend/.env
```

### 3. 启动服务

```bash
# 使用 Docker Compose 一键启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 4. 访问应用

- 前端：http://localhost:8080
- 后端API：http://localhost:8000
- API文档：http://localhost:8000/docs

## 本地开发

### 后端开发

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 前端开发

```bash
cd frontend
npm install
npm run serve
```

## 环境变量说明

### Backend (.env)

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| MONGODB_URL | MongoDB连接地址 | mongodb://admin:dongai_mongo_2024@localhost:27017/ |
| MONGODB_DB_NAME | 数据库名称 | dongai |
| REDIS_URL | Redis连接地址（可选） | redis://localhost:6379/0 |
| STATIC_DIR | 静态文件目录 | ../static |
| JWT_SECRET | JWT密钥 | 请修改为随机字符串 |
| JWT_ALGORITHM | JWT算法 | HS256 |
| JWT_EXPIRE_MINUTES | Token过期时间(分钟) | 43200 (30天) |

### Frontend (.env)

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| VUE_APP_API_BASE_URL | 后端API地址 | http://localhost:8000 |

## 数据模型

### User (用户)
- username: 用户名
- password_hash: 密码哈希
- doubao_api_key: 豆包API密钥
- doubao_base_url: 豆包API地址

### Project (项目)
- user_id: 所属用户
- name: 项目名称
- novel_content: 小说内容

### Character (角色)
- user_id, project_id: 归属
- name: 角色名
- description: 外貌人设
- voice_name: TTS音色

### Shot (分镜)
- user_id, project_id: 归属
- shot_no: 镜头序号
- text: 台词旁白
- prompt: 正向提示词
- neg_prompt: 负面提示词
- duration: 时长
- img_path: 图片路径
- audio_path: 音频路径

## 架构设计

采用适配器模式封装AI服务：

```
core/providers/
├── base.py          # 基类接口
├── llm_provider.py  # LLM适配器（豆包）
├── image_provider.py # 文生图适配器
└── tts_provider.py  # TTS适配器
```

方便后续扩展其他AI服务商（OpenAI、MiniMax等）。

## 注意事项

1. 首次启动需要在个人设置中配置豆包API密钥
2. 静态文件存储在 `static/` 目录，已通过 Docker volume 持久化
3. Redis为可选组件，无Redis时程序仍可正常运行
4. 当前版本不包含视频合成功能，已预留扩展接口

## License

MIT
