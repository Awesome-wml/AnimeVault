# DongAI 前端设计规格（水墨版）

设计稿：`docs/design/dongai-design.html`（双击打开，左侧菜单可点；产品首页 / 登录 / 首页 / 各功能页都在里面）。
水墨动画参考实现：`docs/design/ink-reference.js`（宣纸山水绘制 + 墨迹洇开着色器，已验证可用）。

本文件是实现时的唯一依据。**原则：先变量和组件，页面只组装。** 同一种视觉或逻辑只写一次。

## 1. 设计变量（`src/styles/tokens.css`，全部用 CSS 变量）

| 变量 | 值 | 用途 |
|---|---|---|
| `--ink` | `#26241F` | 正文、主按钮底色 |
| `--ink-muted` | `#676259` | 次要文字（对纸面对比度 ≥ 4.5） |
| `--paper` | `#FDFCFA` | 页面底色 |
| `--side` | `#F3F1EC` | 侧栏底色 |
| `--active` | `#E6E2D9` | 当前菜单 / 选中行 |
| `--line` | `#E8E5DE` | 分隔线、输入框边 |
| `--seal` | `#B5392A` | 印章、失败状态（全站唯一彩色） |
| `--ok` | `#3F6F55` | 已通过 |
| `--warn` | `#8A5A06` | 待审核 / 重试中 |
| `--tone-1..6` | `#DCE1DD #E4DED3 #D8DED6 #E6DFD2 #DEDCE3 #D9E0E2` | 无图时的占位色 |
| `--font-serif` | `'Songti SC','Noto Serif SC','STSong','SimSun',serif` | 标题、镜号、品牌 |
| `--font-sans` | `-apple-system,'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif` | 正文 |
| `--radius` | `8px` | 按钮、输入框、卡片图 |

页面标题 28px 宋体；正文 14px / 行高 1.7；每页**只有一个**实心主按钮（墨色），其余为描边或灰色文字按钮。不用渐变、毛玻璃、发光、emoji 图标。

## 2. 信息架构与路由

```
/                       产品首页（未登录可见）
/login  /register       登录、注册（同一组件，tab 切换）
/home                   工作首页：接着上次的作品 + 需要你处理 + 最近作品
/works                  全部作品
/projects/:pid/novel    故事 · 小说（含一键提取、AI 写小说折叠区；有剧本时一键提取基于剧本）
/projects/:pid/script   故事 · 剧本（小说转分场剧本、场次列表与编辑）
/projects/:pid/style    故事 · 风格
/projects/:pid/characters | scenes | props   资产
/projects/:pid/shots    制作 · 分镜（当前剧集用 ?ep=<video_set_id>）
/projects/:pid/voice    制作 · 配音与字幕
/projects/:pid/final    制作 · 成片（导出剪映、下载字幕）
/projects/:pid/episodes 制作 · 管理剧集（原“视频集”）
/settings/models | prompts | accounts   设置
```
旧路径（`/dashboard` `/projects` `/projects/:pid/workbench` `/prompts` `/models` `/accounts` 等）全部重定向到新路径。

侧栏两种：
- 全局：品牌 → 创作（首页、全部作品）→ 设置（模型、提示词、视频账号）。
- 作品内：‹ 全部作品 → 作品名（宋体）→ 故事（小说、剧本、风格）→ 资产（角色/场景/道具，带数量）→ 制作（剧集选择器 + 分镜〔失败数用 `--seal`〕、配音与字幕、成片、管理剧集）→ 底部“设置”。

## 3. 组件清单（建议目录）

```
src/styles/        tokens.css  base.css  element-theme.css（用变量覆盖 Element UI）  motion.css
src/layouts/       AppLayout.vue（侧栏 + 内容区）  SideNav.vue（数据驱动：groups/items/count/alert）
                   ProjectLayout.vue（作品内侧栏，读 store 里的当前作品、数量、剧集）
src/components/base/
                   PageHeader.vue（title / subtitle / #actions）  BaseButton.vue（variant: primary|secondary|text）
                   StatusText.vue（status → 文案 + 颜色，一处映射）  MediaFrame.vue（ratio；有 src 显示图/视频，无则占位色）
                   AssetCard.vue（角色/场景/道具共用）  EmptyState.vue  Seal.vue  FormField.vue
src/components/ink/  painting.js（绘制宣纸山水）  InkStage.vue（Three.js 着色器；无 WebGL 回退静态画；尊重 prefers-reduced-motion；离开页面停止渲染）
src/components/shot/ ShotList.vue  ShotRow.vue  ShotDetail.vue  BatchGenerateDialog.vue  ManualVideoDialog.vue（拆自 ShotPanel.vue）
src/store/modules/   project.js（当前作品、角色/场景/道具数量、剧集列表、当前剧集）
src/api/index.js     唯一请求入口；补齐 video-set、剪映导出等方法。**页面里不许出现 fetch / 写死的 localhost。**
```

## 4. 动效

- 水墨动画只在产品首页、登录/注册：墨迹约 9 秒洇开后静止，只剩薄雾慢流；标题墨迹淡入；红印“戏”+“开始创作”像落款。
- 工作台只保留：页面淡入、悬停底色、输入框聚焦。不加列表滑入、卡片上浮、呼吸等。
- `prefers-reduced-motion: reduce` 时全部关闭。

## 5. 不改的东西

后端接口、数据结构、业务逻辑保持不变；现有功能一个都不能丢（对照设计稿 README 中的功能去向表）。需要后端配合的能力（分镜审核状态/版本、成片预览、自动保存、真实提取进度）本期只留 UI 位置，不伪造数据。
