# 端到端自动化测试

一条命令起好后端和前端，跑完后端接口测试和浏览器主流程测试，收尾时停服务、删测试库。

## 怎么跑

```bash
# 一次性准备
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
cd frontend && npm install && cd ..
# 本机没装 Playwright 自带的 chromium 时直接用系统 Chrome（配置里已是 channel: 'chrome'）

# 替身模式（默认）：外部服务全部替身，完整主流程
E2E_MONGO_URL_FILE=~/secrets/mongo.url \
E2E_PYTHON=/path/to/venv/bin/python \
scripts/e2e.sh

# 真实模型冒烟：真智谱跑 小说（AI 写）→ 一键提取（资产 + 分镜）
E2E_REAL=1 E2E_ZHIPU_KEY_FILE=~/secrets/zhipu.key E2E_MONGO_URL_FILE=... scripts/e2e.sh
```

| 变量 | 说明 |
|---|---|
| `MONGODB_URL` / `E2E_MONGO_URL_FILE` | Mongo 连接串（二选一，文件里只放连接串） |
| `E2E_DB_NAME` | 测试库，默认 `dongai_e2e`；名字必须含 `e2e` 或 `test`，脚本拒绝碰 `dongai` |
| `E2E_JWT_SECRET_FILE` | 可选，不给则每次随机 |
| `E2E_ZHIPU_KEY_FILE` | `E2E_REAL=1` 时必需；只在运行时读，经接口写进测试库里测试用户的全局密钥，随测试库删除 |
| `E2E_PYTHON` | 后端 Python，默认 `backend/.venv/bin/python` |
| `E2E_BACKEND_PORT` / `E2E_FRONTEND_PORT` | 默认 8001 / 8081，不影响平时开发用的 8000 / 8080 |
| `E2E_KEEP_DB=1` | 跑完保留测试库，排查用 |

脚本做的事：快照主库各集合文档数 → 清空测试库并放 3 个替身视频账号 → 起后端（`:8001`，库 `dongai_e2e`，静态文件和剪映草稿写到临时目录）→ 起前端 dev server（`:8081`，`DONGAI_API_TARGET` 让代理指向 `:8001`）→ pytest → Playwright → 停服务、删测试库、对比主库快照。

## 报告在哪

默认 `e2e-report/`（已加入 .gitignore；真实冒烟在 `e2e-report/real/`）：

- `html/index.html`：Playwright HTML 报告，每个用例挂着该步截图，失败时附 trace
- `screenshots/`：每步截图，`main-flow-NN-*.png`、`empty-states-NN-*.png`
- `pytest.txt`、`pytest-junit.xml`：后端接口测试结果
- `backend.log`、`frontend.log`：本次起的服务日志
- `real-timings.json`：真实冒烟各步耗时

## 替身模式

后端环境变量 `DONGAI_FAKE_PROVIDERS=1` 时，外部服务都不访问，返回固定、合法的数据（`backend/core/providers/fake.py`）：

| 外部服务 | 切入点 | 替身返回 |
|---|---|---|
| 智谱 GLM | `DoubaoLLMProvider._chat_with_retry` / `_stream_chat`（HTTP 入口） | 按提示词类型返回小说正文、润色稿、资产提取 JSON、分镜 JSON；上层流式、`chat_json` 解析照常执行 |
| 文生图 | `DoubaoImageProvider.generate_image` | `backend/tests/fixtures/placeholder.png` |
| TTS | `DoubaoTTSProvider.generate_speech` | `backend/tests/fixtures/speech.mp3`（1 秒） |
| 豆包视频 | `DoubaoVideoGenerator.generate_batch` / `generate_parallel` | 拷贝 `fixtures/clip.mp4`，进度推送与写库回调照常 |
| 剪映 | 导出后不拉起桌面应用 | 草稿照常写到 `JIANYING_DRAFT_DIR`，模板用 `fixtures/jianying_template` |

每处只在入口判断一次 `fake.enabled()`，开关关闭时原代码路径不变。替身数据里的角色/场景/道具名与分镜绑定的名字一致，能走通“提取 → 分镜绑定资产 → 视频参考图”的整条链。

## 覆盖了什么

- `backend/tests/`（pytest + httpx，对真实运行的后端发请求）：鉴权、作品 CRUD 与用户隔离、主流程每个接口（小说 SSE、润色、全量/单类提取、出图与上传、剧集、拆分镜、改分镜、画面、单条/批量视频与 SSE 进度、补录视频、配音、字幕导出与下载、剪映导出）、错误与空状态（无密钥、无分镜、无角色、无视频、越权、非法 ID）。
  单独跑：`MONGODB_URL=... MONGODB_DB_NAME=dongai_e2e python -m pytest backend/tests`（没设 `DONGAI_API_BASE` 时会自己起一个替身模式后端）。
- `frontend/e2e/main-flow.spec.js`（Playwright）：浏览器注册 → 新建作品 → 小说（粘贴、AI 写）→ 一键提取 → 风格 → 角色三视图与配音色、场景道具参考图 → 分镜（编辑、生成画面、再拆）→ 单条与批量视频 → 配音与字幕下载 → 成片预览与导出剪映 → 管理剧集（新建、进入、重命名、导出、删除）→ 首页“接着做”。其中含失败/空状态：没小说时一键提取、未配密钥时一键提取。
- `frontend/e2e/empty-states.spec.js`：新作品各页的空状态与提示。
- `frontend/e2e/real-smoke.spec.js`：真实模型冒烟，仅 `E2E_REAL=1` 时运行。

选择器优先用可见文案和 role；画面框用基础组件 `MediaFrame` 上的 `data-testid="media-frame"`。
