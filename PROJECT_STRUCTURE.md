# DongAI 项目结构说明

## 完整目录树

```
dongai/
├── README.md                      # 项目总览
├── START.md                       # 快速启动指南（⭐ 推荐首读）
├── DEPLOYMENT.md                  # 详细部署指南
├── USAGE.md                       # 使用教程
├── PROJECT_STRUCTURE.md           # 本文件
├── docker-compose.yml             # Docker编排配置
├── .gitignore                     # Git忽略规则
├── check.sh                       # 环境检查脚本
│
├── static/                        # 静态文件目录（持久化）
│   ├── images/                    # AI生成的图片
│   │   └── .gitkeep
│   └── audio/                     # AI生成的音频
│       └── .gitkeep
│
├── backend/                       # 后端项目（Python FastAPI）
│   ├── main.py                    # FastAPI主入口
│   ├── requirements.txt           # Python依赖
│   ├── Dockerfile                 # 后端镜像构建
│   ├── .env                       # 环境变量配置
│   ├── .env.example               # 环境变量示例
│   │
│   ├── config/                    # 配置模块
│   │   ├── __init__.py
│   │   └── settings.py            # 全局配置（Pydantic Settings）
│   │
│   ├── db/                        # 数据库模块
│   │   ├── __init__.py
│   │   ├── mongo_client.py        # MongoDB异步客户端
│   │   └── redis_client.py        # Redis客户端（可选）
│   │
│   ├── models/                    # 数据模型
│   │   ├── __init__.py
│   │   └── schema.py              # Pydantic数据模型
│   │
│   ├── core/                      # 核心业务逻辑
│   │   ├── __init__.py
│   │   ├── prompt_tpl.py          # AI提示词模板
│   │   │
│   │   └── providers/             # AI服务提供者（适配器模式）
│   │       ├── __init__.py
│   │       ├── base.py            # 适配器基类
│   │       ├── llm_provider.py    # LLM提供者（豆包）
│   │       ├── image_provider.py  # 文生图提供者（豆包）
│   │       └── tts_provider.py    # TTS提供者（豆包）
│   │
│   ├── api/                       # API路由
│   │   ├── __init__.py
│   │   ├── auth.py                # 认证相关（注册/登录/JWT）
│   │   ├── project.py             # 项目管理CRUD
│   │   ├── novel.py               # 小说生成（SSE流式输出）
│   │   ├── character.py           # 角色管理（AI提取）
│   │   ├── shot.py                # 分镜管理（AI拆分）
│   │   ├── image.py               # 文生图API
│   │   ├── tts.py                 # TTS语音合成API
│   │   └── config.py              # 系统配置API
│   │
│   └── utils/                     # 工具类
│       ├── __init__.py
│       ├── file_util.py           # 文件处理工具
│       └── srt_builder.py         # SRT字幕生成器
│
└── frontend/                      # 前端项目（Vue 2）
    ├── package.json               # npm依赖配置
    ├── vue.config.js              # Vue CLI配置
    ├── babel.config.js            # Babel配置
    ├── jsconfig.json              # JS编译配置
    ├── Dockerfile                 # 前端镜像构建
    ├── nginx.conf                 # Nginx配置
    ├── .env                       # 环境变量
    ├── .env.example               # 环境变量示例
    ├── .gitignore                 # Git忽略规则
    │
    ├── public/                    # 静态资源
    │   ├── index.html             # HTML模板
    │   └── favicon.ico            # 网站图标
    │
    └── src/                       # 源代码
        ├── main.js                # Vue入口文件
        ├── App.vue                # 根组件
        │
        ├── router/                # Vue Router路由
        │   └── index.js           # 路由配置
        │
        ├── store/                 # Vuex状态管理
        │   └── index.js           # Vuex Store
        │
        ├── api/                   # API封装
        │   └── index.js           # Axios封装 + API接口
        │
        ├── views/                 # 页面组件
        │   ├── Login.vue          # 登录/注册页
        │   ├── ProjectList.vue    # 项目列表页
        │   ├── NovelEdit.vue      # 小说编辑页（SSE流式）
        │   ├── CharacterManage.vue # 角色管理页
        │   └── ShotWorkbench.vue  # 分镜工作台（表格编辑）
        │
        ├── components/            # 公共组件
        │   └── HelloWorld.vue     # （示例组件）
        │
        └── assets/                # 资源文件
            └── logo.png
```

## 技术栈详解

### 后端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Python | 3.13 | 编程语言 |
| FastAPI | 0.109.0 | Web框架 |
| Uvicorn | 0.27.0 | ASGI服务器 |
| Motor | 3.3.2 | MongoDB异步驱动 |
| Redis | 5.0.1 | 缓存（可选） |
| Pydantic | 2.5.3 | 数据验证 |
| python-jose | 3.3.0 | JWT认证 |
| bcrypt | 4.1.2 | 密码加密 |
| httpx | 0.26.0 | HTTP客户端（调用AI服务） |
| srt | 3.5.3 | SRT字幕处理 |

### 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 2.6.14 | 前端框架 |
| Vue Router | 3.5.3 | 路由管理 |
| Vuex | 3.6.2 | 状态管理 |
| Element UI | 2.15.13 | UI组件库 |
| Axios | 1.6.0 | HTTP客户端 |

### 基础设施

| 组件 | 版本 | 用途 |
|------|------|------|
| MongoDB | 7.0 | 主数据库 |
| Redis | 7.2 | 缓存（可选） |
| Nginx | Alpine | 前端静态文件服务 |
| Docker | 20.10+ | 容器化 |
| Docker Compose | 2.0+ | 服务编排 |

## 数据库设计

### MongoDB集合

#### 1. users（用户）

```javascript
{
  _id: ObjectId,
  username: String,          // 用户名（唯一索引）
  password_hash: String,     // bcrypt加密的密码
  doubao_api_key: String,    // 豆包API密钥
  doubao_base_url: String,   // 豆包API地址
  create_time: DateTime      // 创建时间
}
```

#### 2. projects（项目）

```javascript
{
  _id: ObjectId,
  user_id: String,           // 所属用户ID（索引）
  name: String,              // 项目名称
  novel_content: String,     // 小说内容
  create_time: DateTime      // 创建时间
}
```

#### 3. characters（角色）

```javascript
{
  _id: ObjectId,
  user_id: String,           // 所属用户ID
  project_id: String,        // 所属项目ID（复合索引）
  name: String,              // 角色名
  description: String,       // 外貌人设描述
  voice_name: String         // TTS音色名称
}
```

#### 4. shots（分镜）

```javascript
{
  _id: ObjectId,
  user_id: String,           // 所属用户ID
  project_id: String,        // 所属项目ID（复合索引）
  shot_no: Integer,          // 镜头序号
  text: String,              // 台词/旁白
  prompt: String,            // 正向提示词
  neg_prompt: String,        // 负面提示词
  duration: Float,           // 镜头时长（秒）
  img_path: String,          // 图片相对路径
  audio_path: String         // 音频相对路径
}
```

### 索引设计

```javascript
// users
db.users.createIndex({ username: 1 }, { unique: true })

// projects
db.projects.createIndex({ user_id: 1 })

// characters
db.characters.createIndex({ user_id: 1, project_id: 1 })

// shots
db.shots.createIndex({ user_id: 1, project_id: 1 })
db.shots.createIndex({ project_id: 1, shot_no: 1 })
```

## API接口概览

### 认证模块 (/api/auth)

- `POST /api/auth/register` - 用户注册
- `POST /api/auth/login` - 用户登录
- `GET /api/auth/me` - 获取当前用户信息
- `PUT /api/auth/config` - 更新API密钥配置
- `GET /api/auth/config` - 获取API配置

### 项目管理 (/api/projects)

- `POST /api/projects` - 创建项目
- `GET /api/projects` - 获取项目列表
- `GET /api/projects/{id}` - 获取项目详情
- `PUT /api/projects/{id}` - 更新项目
- `DELETE /api/projects/{id}` - 删除项目

### 小说生成 (/api/novel)

- `POST /api/novel/generate` - 生成小说（SSE流式）
- `POST /api/novel/save` - 保存小说内容

### 角色管理 (/api/characters)

- `POST /api/characters/extract` - AI提取角色
- `POST /api/characters` - 创建角色
- `GET /api/characters` - 获取角色列表
- `PUT /api/characters/{id}` - 更新角色
- `DELETE /api/characters/{id}` - 删除角色

### 分镜管理 (/api/shots)

- `POST /api/shots/split` - AI拆分分镜
- `POST /api/shots` - 创建分镜
- `GET /api/shots` - 获取分镜列表
- `PUT /api/shots/{id}` - 更新分镜
- `DELETE /api/shots/{id}` - 删除分镜

### 文生图 (/api/image)

- `POST /api/image/generate` - 生成图片

### TTS配音 (/api/tts)

- `GET /api/tts/voices` - 获取可用音色
- `POST /api/tts/generate` - 生成语音
- `POST /api/tts/srt/export` - 导出SRT字幕
- `GET /api/tts/srt/download/{id}` - 下载SRT文件

### 系统配置 (/api/config)

- `GET /api/config/system` - 获取系统配置

## 适配器模式设计

### 为什么使用适配器模式？

1. **解耦AI服务**: 核心业务逻辑与具体AI服务商解耦
2. **易于扩展**: 新增服务商只需实现基类接口
3. **统一接口**: 上层调用无需关心底层实现

### 适配器结构

```
BaseLLMProvider (抽象基类)
    ↓
DoubaoLLMProvider (豆包实现)

BaseImageProvider (抽象基类)
    ↓
DoubaoImageProvider (豆包实现)

BaseTTSProvider (抽象基类)
    ↓
DoubaoTTSProvider (豆包实现)
```

### 如何扩展新服务商？

示例：添加OpenAI支持

```python
# backend/core/providers/openai_llm_provider.py
from .base import BaseLLMProvider

class OpenAILLMProvider(BaseLLMProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    async def chat(self, messages, model, temperature=0.7, stream=False):
        # 实现OpenAI调用逻辑
        pass
    
    async def chat_json(self, messages, model, max_retries=3):
        # 实现JSON强制输出
        pass
```

然后在API层根据用户配置选择对应的Provider即可。

## 部署架构

### Docker Compose服务

```
┌─────────────┐      ┌─────────────┐
│  Frontend   │─────▶│   Backend   │
│ (Vue + Nginx)│      │  (FastAPI)  │
│  Port: 8080 │      │  Port: 8000 │
└─────────────┘      └──────┬──────┘
                            │
         ┌──────────────────┼──────────────────┐
         │                  │                  │
    ┌────▼─────┐     ┌──────▼──────┐   ┌──────▼──────┐
    │ MongoDB  │     │    Redis    │   │   Static    │
    │Port: 27017│     │ Port: 6379  │   │   Volume    │
    └──────────┘     └─────────────┘   └─────────────┘
```

### 数据持久化

- **MongoDB数据**: Docker volume `mongo_data`
- **Redis数据**: Docker volume `redis_data`
- **静态文件**: 宿主机目录 `./static`

### 网络配置

- 所有服务在同一个Docker网络 `dongai_network`
- 服务间通过服务名互相访问（如：`mongodb`, `redis`, `backend`）

## 开发规范

### 后端代码规范

1. 使用 `async/await` 异步编程
2. 所有API返回统一的 `ResponseModel`
3. 异常统一捕获并返回友好提示
4. 敏感信息（密钥）通过环境变量管理
5. 数据库操作使用Motor异步驱动
6. 文件操作使用 `FileUtil` 工具类

### 前端代码规范

1. 使用Vue 2 Options API
2. 组件化开发，页面组件放在 `views/`
3. API调用统一通过 `api/index.js`
4. 状态管理使用Vuex
5. 路由使用Vue Router
6. UI组件使用Element UI
7. 异步操作显示loading状态

### Git提交规范

```
feat: 新功能
fix: Bug修复
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 构建/工具链相关
```

## 扩展计划

### 短期扩展（已预留接口）

- [ ] 视频生成功能
- [ ] FFmpeg成片合成
- [ ] 更多TTS音色
- [ ] 批量操作优化

### 长期扩展

- [ ] 支持其他AI服务商（OpenAI、MiniMax、通义千问等）
- [ ] 项目模板市场
- [ ] 团队协作功能
- [ ] 数字人视频生成
- [ ] 自动配乐功能
- [ ] 云端渲染

## 性能优化建议

1. **数据库查询优化**: 使用索引，避免全表扫描
2. **静态文件CDN**: 生产环境将static目录上传至CDN
3. **Redis缓存**: 启用Redis缓存热点数据
4. **异步任务队列**: 大批量生成使用Celery等任务队列
5. **前端懒加载**: 路由组件懒加载
6. **API限流**: 防止恶意调用

## 安全建议

1. **JWT密钥**: 生产环境必须修改为强随机字符串
2. **HTTPS**: 生产环境使用HTTPS
3. **输入验证**: 所有用户输入进行严格验证
4. **SQL注入防护**: 使用ORM/ODM，避免拼接查询
5. **XSS防护**: 前端输出转义
6. **CSRF防护**: 关键操作添加CSRF token
7. **API密钥加密**: 数据库中的API密钥应加密存储（当前为明文）

## 常见问题排查

### 后端问题

1. **MongoDB连接失败**: 检查 `.env` 中的连接字符串
2. **API密钥无效**: 检查豆包API密钥是否正确
3. **文件保存失败**: 检查 `static/` 目录权限
4. **导入错误**: 检查所有 `__init__.py` 文件是否存在

### 前端问题

1. **无法连接后端**: 检查 `.env` 中的 `VUE_APP_API_BASE_URL`
2. **CORS错误**: 检查后端CORS配置
3. **路由404**: 确认使用Hash模式
4. **组件未注册**: 检查是否正确导入Element UI

---

**本文档详细说明了项目的目录结构、技术栈、数据库设计、API接口等关键信息。如有疑问，请查看其他文档或查看代码注释。**
