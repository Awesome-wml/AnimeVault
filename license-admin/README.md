# DongAI 授权管理端（license-admin）

给我们自己用的授权后台：签发授权码、查看授权、延期/停用/恢复/吊销、管理员账号、审计日志。
独立于用户端 `frontend/`，独立构建、独立部署；后端是 `license-server/`（接口前缀 `/admin/api`）。
设计见 `docs/license-design.md` 第 7、9 节。

技术栈与 `frontend/` 一致：Vue 2 + Vue Router + Vuex + Element UI，Vue CLI 5，ESLint 7（`plugin:vue/essential` + `eslint:recommended`）。

## 目录

```
src/
  api/          唯一的请求层：http.js（axios 实例 + 拦截器）、auth / licenses / admins / audit
  config/       plans.js（套餐白名单、功能点候选）、roles.js（角色、权限、菜单）
  utils/        errors（错误码 -> 中文）、license（状态机、到期高亮）、machineCode（机器码初检）、
                time、session（sessionStorage）、validators、clipboard
  styles/       tokens.css（样式变量，全站颜色/字号/间距只从这里取）、base.css、element-theme.css
  components/
    base/       PageHeader、BaseTable（表格+分页）、StatusTag、ConfirmDialog、CopyButton、WarnBar、JsonFold
    license/    IssueDialog、LicenseDrawer、LicenseCode、LicenseActionButtons、LicenseActionHost
    admin/      AdminCreateDialog、AdminEditDialog
  layouts/      AdminLayout（侧边栏按角色显示菜单、顶部当前管理员与角色、退出）
  views/        Login、LicenseList、AdminList、AuditLog（页面只负责组装）
tests/unit/     单测（node --test）
e2e/            Playwright 联调用例、start_server.py、screenshots/
```

约定：页面里不写原始 axios，所有请求走 `src/api`；错误由拦截器按后端 `code` 映射成中文并弹提示
（登录接口除外，登录页自己展示，以便显示锁定倒计时）；401 自动清凭据回登录页。
登录凭据只放 `sessionStorage`（8 小时有效，关标签页即失效），不用 `localStorage`。

## 本地开发

```bash
# 1. 启动授权服务（端口 18100，见 license-server/README.md；本地演示可用内存仓库）
# 2. 启动管理端（端口 5180，/admin/api 代理到 18100）
cd license-admin
npm install
npm run serve            # http://127.0.0.1:5180
```

环境变量：`LICENSE_API_TARGET`（代理目标，默认 `http://127.0.0.1:18100`）、`PORT`（默认 5180）。
不要使用 8000 / 8080 / 8081 端口。

构建时可选：`VUE_APP_PLANS=trial,basic,pro` 覆盖套餐白名单（要与服务端 `LS_PLANS` 保持一致，
服务端目前没有接口暴露套餐，默认值在 `src/config/plans.js`）；`VUE_APP_API_BASE` 覆盖接口前缀（默认 `/admin/api`）。

## 测试

```bash
npm run lint          # ESLint
npm run test:unit     # 单测：错误映射、状态机按钮、到期高亮、机器码初检、会话、校验
npm run build         # 构建，产物在 dist/
npm run e2e           # Playwright 联调（见下）
```

### e2e 联调

`e2e/playwright.config.js` 会自动启动两个进程，不需要手工准备：

- `python3 e2e/start_server.py`：内存仓库的授权服务（端口 18100）。在系统临时目录用
  `license/scripts/gen_keys.py` 生成测试私钥（不进仓库，退出即删），`LS_JWT_SECRET` 随机，
  预建 `e2e_super` / `e2e_ops` / `e2e_readonly` 三个管理员，密码来自环境变量 `E2E_ADMIN_PASSWORD`。
  它还挂了一个仅 e2e 使用的 `/e2e/activate/{lid}`（把 pending 置为 active，因为客户端激活是 L-42，
  还没有对应的 HTTP 接口，而「停用」只能对 active 授权操作）。**不要用于生产。**
- `vue-cli-service serve`（端口 5180，代理到 18100）。

```bash
E2E_ADMIN_PASSWORD='至少12位的随机串' npm run e2e   # 不设置则本次运行随机生成
```

依赖：本机 Python 3 装好 `license-server/requirements.txt`，以及系统 Chrome（和 `frontend/` 一样用 `channel: 'chrome'`）。
机器码用 `license/dongai_license/machine_code.py` 生成本机真实机器码。截图输出在 `e2e/screenshots/`。

## 角色与页面

| 页面 | super | ops | readonly |
|---|---|---|---|
| 授权管理（列表、详情） | 全部 | 全部（含签发、延期、停用、恢复、吊销） | 只读，没有任何操作按钮 |
| 审计日志 | 可见 | 可见 | 不可见 |
| 管理员管理 | 可见 | 不可见 | 不可见 |

前端按角色隐藏只是体验，真正的权限以服务端为准（403 `FORBIDDEN` 会提示）。

## 部署

管理端是纯静态文件（`npm run build` 生成 `dist/`），由 nginx 托管，并把 `/admin/api` 反向代理到授权服务。
设计要求「管理端只允许内网或固定 IP 访问」，请在 nginx 里限制来源并用 HTTPS。

```nginx
server {
    listen 443 ssl;
    server_name license-admin.example.com;
    ssl_certificate     /etc/nginx/certs/license-admin.crt;
    ssl_certificate_key /etc/nginx/certs/license-admin.key;

    # 只允许内网 / 固定出口 IP
    allow 10.0.0.0/8;
    allow 203.0.113.10;
    deny  all;

    root /srv/license-admin/dist;
    index index.html;

    # 单页应用：前端路由回落到 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }
    location ~* \.(js|css|png|ico|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public";
        try_files $uri =404;
    }

    # 授权服务（同源转发，浏览器不需要 CORS）
    location /admin/api/ {
        proxy_pass http://127.0.0.1:18100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;   # 不透传客户端自带的 XFF
        proxy_read_timeout 30s;
    }
}
```

注意：授权服务登录限流和审计里的 IP 取自直连地址，放在 nginx 后面时需要让 uvicorn 带
`--proxy-headers --forwarded-allow-ips=<nginx 地址>`，否则所有登录和审计 IP 都是 nginx 的地址，
限流会变成「所有人共用一个计数」（见 `license-server/README.md` 部署注意）。
