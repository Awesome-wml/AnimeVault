# 修复总结：资产管理页面角色显示问题

## 问题描述
前端资产管理页面中，角色选项卡返回了4条数据，但只显示2条。控制台报错：
```
AssetManage.vue:282 TypeError: Cannot read properties of undefined (reading 'staticUrl')
```

## 根本原因
在 Vue 2 中，模板直接访问导入的 `api` 对象会失败，因为导入的变量不会自动暴露给模板。
模板中使用了 `api.staticUrl(scope.row.image_path)`，但 `api` 在模板作用域中是 `undefined`。

## 解决方案
1. **创建辅助方法**：在 `methods` 中添加 `getStaticUrl(path)` 方法来封装 `api.staticUrl()` 调用
2. **更新模板引用**：将所有模板中的 `api.staticUrl()` 调用替换为 `getStaticUrl()`

## 修改文件
- `frontend/src/views/AssetManage.vue`

## 具体修改

### 1. 添加辅助方法（在 methods 中）
```javascript
methods: {
  // 辅助方法：获取静态资源URL
  getStaticUrl(path) {
    return api.staticUrl(path)
  },
  // ... 其他方法
}
```

### 2. 更新模板引用（共3处）

#### 角色表格 - 三视图列
```vue
<!-- 修改前 -->
<img v-if="scope.row.image_path" :src="api.staticUrl(scope.row.image_path)" class="thumb" />

<!-- 修改后 -->
<img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
```

#### 道具表格 - 参考图列
```vue
<!-- 修改前 -->
<img v-if="scope.row.image_path" :src="api.staticUrl(scope.row.image_path)" class="thumb" />

<!-- 修改后 -->
<img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
```

#### 场景表格 - 参考图列
```vue
<!-- 修改前 -->
<img v-if="scope.row.image_path" :src="api.staticUrl(scope.row.image_path)" class="thumb" />

<!-- 修改后 -->
<img v-if="scope.row.image_path" :src="getStaticUrl(scope.row.image_path)" class="thumb" />
```

## 部署步骤
```bash
# 1. 停止并删除旧容器
docker-compose stop frontend
docker-compose rm -f frontend

# 2. 无缓存重新构建
docker-compose build --no-cache frontend

# 3. 创建并启动新容器
docker-compose create frontend
docker-compose start frontend

# 4. 验证所有服务运行正常
docker-compose ps
```

## 验证结果
- ✅ 前端容器成功重新构建（文件哈希从 app.088c7a88.js 变为 app.f8c828c0.js）
- ✅ `getStaticUrl` 方法已包含在新构建的文件中
- ✅ 所有服务（frontend, backend, mongodb, redis）正常运行
- ✅ 前端服务运行在 http://localhost:8080

## 测试建议
1. 清除浏览器缓存（强制刷新：Cmd+Shift+R 或 Ctrl+Shift+R）
2. 打开资产管理页面
3. 检查角色选项卡是否能正常显示所有4条数据
4. 确认控制台没有错误信息

## 相关文件
- 前端代码：`frontend/src/views/AssetManage.vue`
- API 定义：`frontend/src/api/index.js`
- Docker 配置：`docker-compose.yml`
