# 🚀 DongAI 快速启动指南

## 最快3步启动

### 步骤1：准备环境变量（可选，使用默认配置也能启动）

```bash
# 后端已有默认配置，生产环境建议修改JWT_SECRET
# 前端已有默认配置，如需修改API地址：
# vim frontend/.env
```

### 步骤2：一键启动

```bash
# 在项目根目录执行
docker-compose up -d
```

### 步骤3：访问应用

打开浏览器访问: **http://localhost:8080**

✅ 完成！开始创作吧！

---

## 首次使用流程

1. **注册账号**
   - 打开 http://localhost:8080
   - 点击"注册"，填写用户名和密码
   
2. **配置API密钥**
   - 登录后点击右上角"配置API密钥"
   - 填入豆包API密钥和地址
   - 如何获取？访问: https://console.volcengine.com/ark

3. **创建第一个项目**
   - 点击"新建项目"
   - 输入项目名称

4. **生成小说**
   - 进入"编辑小说"
   - 填写题材、风格、梗概等信息
   - 点击"生成小说"，实时查看生成过程

5. **提取角色**
   - 进入"角色管理"
   - 点击"AI提取角色"
   - 为角色绑定TTS音色

6. **拆分分镜**
   - 进入"分镜工作台"
   - 粘贴小说段落
   - 点击"拆分分镜"

7. **生成素材**
   - 在分镜表格中点击"生成"按钮生成图片
   - 点击"配音"按钮生成语音

8. **导出字幕**
   - 点击"导出SRT字幕"
   - 用于后期视频制作

---

## 服务地址

- 🎨 **前端**: http://localhost:8080
- 🔧 **后端API**: http://localhost:8000
- 📚 **API文档**: http://localhost:8000/docs
- 💚 **健康检查**: http://localhost:8000/health

---

## 常用命令

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose stop

# 完全停止并删除容器
docker-compose down
```

---

## 需要帮助？

- 📖 完整部署指南: [DEPLOYMENT.md](./DEPLOYMENT.md)
- 📘 详细使用教程: [USAGE.md](./USAGE.md)
- 📄 项目说明: [README.md](./README.md)

---

## 系统要求

- ✅ Docker 20.10+
- ✅ Docker Compose 2.0+
- ✅ 8GB+ 内存
- ✅ 20GB+ 磁盘空间

---

**🎉 祝您使用愉快！**
