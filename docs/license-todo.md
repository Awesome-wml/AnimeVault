# 授权/桌面发行 待办事项（需要负责人推进，卡发售）

> 本地文档，不在 taskhub 建任务。代码侧 L-29 已完成，以下是代码之外的阻塞项。

## 一、证书与主体（P0）
- [ ] 确定用哪个公司主体申请证书
- [ ] Apple Developer 账号（Developer ID + 公证），拿到后按 desktop/signing/README.md 实测签名与公证
- [ ] Windows 代码签名证书（向发证机构确认 SmartScreen 策略，以干净机实测为准），实测 sign_win.ps1 / verify_win.ps1

## 二、法务与协议（P0）
- [ ] 用户协议、隐私政策（L-90）
- [ ] 法务确认：mongod 的 SSPL、ffmpeg 的 LGPL 义务；是否自编译 macOS LGPL ffmpeg

## 三、密钥与授权服务部署（P0）
- [ ] 生成正式密钥对（私钥只放授权服务器），替换 backend/core/license_keys.py 占位公钥
- [ ] 确定授权服务域名与部署位置（HTTPS、反代、备份，L-28），替换 license_config.py 占位地址
- [ ] 正式构建后运行 desktop/check_release_build.py

## 四、发版前清单
- [ ] Electron Fuses 正式构建开启，移除测试专用调试放行
- [ ] mongod 开启认证（随机密码）
- [ ] 旧 Mongo 默认密码 dongai_mongo_2024 轮换（如曾用于线上），视情况清理 git 历史
- [ ] docker-compose 仍挂载 doubao_accounts.json，处理
- [ ] Windows 全链路实测；干净虚拟机验证（L-11）；Chrome 引导（L-07）
- [ ] 自动更新（L-65）、运营功能（L-60~63）
- [ ] Phase 4：LLM/图片网关与提示词模板下发、计费（两项决策待定）
