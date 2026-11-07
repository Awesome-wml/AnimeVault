# DongAI 样式设计指南

## 📋 概述

本项目采用统一的设计系统，确保所有页面具有一致的视觉风格和用户体验。

## 🎨 设计原则

### 1. 统一性
- 所有页面使用统一的颜色、字体、间距和圆角
- 组件样式保持一致，提升用户体验

### 2. 简洁性
- 清晰的视觉层次
- 减少不必要的装饰
- 关注内容本身

### 3. 响应式
- 适配不同屏幕尺寸
- 移动端友好

## 🎨 设计令牌 (Design Tokens)

### 颜色系统

```css
/* 主题色 - 渐变紫蓝色调 */
--primary: #6366f1;
--primary-light: #818cf8;
--primary-dark: #4f46e5;
--primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

/* 功能色 */
--success: #10b981;  /* 成功 */
--warning: #f59e0b;  /* 警告 */
--danger: #ef4444;   /* 危险 */
--info: #3b82f6;     /* 信息 */

/* 背景色 */
--bg-dark-primary: #0f172a;    /* 暗色主背景 */
--bg-dark-secondary: #1e293b;  /* 暗色次背景 */
--bg-dark-tertiary: #334155;   /* 暗色三级背景 */
--bg-light: #f8fafc;           /* 浅色背景 */
--bg-white: #ffffff;           /* 白色背景 */

/* 文字色 */
--text-dark: #1e293b;      /* 标题深色 */
--text-primary: #334155;   /* 主要文字 */
--text-secondary: #64748b; /* 次要文字 */
--text-tertiary: #94a3b8;  /* 辅助文字 */
--text-light: #f1f5f9;     /* 浅色文字 */
```

### 间距系统

```css
--spacing-xs: 4px;
--spacing-sm: 8px;
--spacing-md: 16px;
--spacing-lg: 24px;
--spacing-xl: 32px;
--spacing-2xl: 48px;
```

### 圆角系统

```css
--radius-sm: 6px;   /* 小圆角 */
--radius: 8px;      /* 标准圆角 */
--radius-md: 12px;  /* 中等圆角 */
--radius-lg: 16px;  /* 大圆角 */
--radius-xl: 20px;  /* 超大圆角 */
--radius-full: 9999px; /* 完全圆角 */
```

### 阴影系统

```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
--shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.1);
--shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.12);
--shadow-xl: 0 16px 48px rgba(0, 0, 0, 0.15);
```

### 过渡效果

```css
--transition-fast: 150ms ease;
--transition: 300ms ease;
--transition-slow: 500ms ease;
```

## 🧩 组件样式

### 页面容器

```css
.page-container {
  min-height: 100vh;
  background: var(--bg-light);
}
```

### 页面头部

```html
<el-header>
  <div class="header-content">
    <el-button icon="el-icon-back">返回</el-button>
    <h3>页面标题</h3>
    <div class="header-actions">
      <!-- 操作按钮 -->
    </div>
  </div>
</el-header>
```

### 卡片组件

```html
<el-card class="content-card">
  <div slot="header" class="card-header">
    <span class="card-title">卡片标题</span>
    <div class="card-actions">
      <!-- 操作按钮 -->
    </div>
  </div>
  <!-- 卡片内容 -->
</el-card>
```

### 工具栏

```html
<div class="toolbar">
  <h3 class="toolbar-title">列表标题</h3>
  <div class="toolbar-actions">
    <el-button type="primary">主要操作</el-button>
  </div>
</div>
```

### 数据表格

```html
<el-table class="data-table" :data="tableData">
  <!-- 表格列 -->
</el-table>
```

## 📱 响应式设计

### 断点

- 移动端：< 768px
- 平板：768px - 1024px
- 桌面：> 1024px

### 响应式示例

```css
@media (max-width: 768px) {
  .page-main {
    padding: 16px;
  }
  
  .toolbar {
    flex-direction: column;
  }
}
```

## 🎯 最佳实践

### 1. 使用设计令牌

❌ 不推荐：
```css
.my-component {
  color: #333;
  padding: 20px;
  border-radius: 8px;
}
```

✅ 推荐：
```css
.my-component {
  color: var(--text-primary);
  padding: var(--spacing-lg);
  border-radius: var(--radius);
}
```

### 2. 保持一致的间距

使用标准间距系统，避免随意设置数值。

### 3. 合理使用阴影

- 卡片：使用 `--shadow`
- 悬浮效果：使用 `--shadow-md` 或 `--shadow-lg`
- 模态框：使用 `--shadow-xl`

### 4. 颜色使用场景

- 主要操作按钮：`--primary`
- 成功提示：`--success`
- 警告提示：`--warning`
- 错误提示：`--danger`

## 🔧 自定义 Element UI 样式

### 全局覆盖

在 `global.css` 中覆盖 Element UI 默认样式：

```css
.el-button--primary {
  background: var(--primary-gradient);
  border: none;
}

.el-card {
  border-radius: var(--radius-md);
  box-shadow: var(--shadow);
  border: 1px solid var(--border-color);
}
```

### 组件内覆盖

使用深度选择器 `>>>`：

```css
.my-component >>> .el-input__inner {
  border-radius: var(--radius);
}
```

## 📦 文件结构

```
frontend/src/assets/styles/
├── global.css    # 全局样式和设计令牌
└── pages.css     # 页面通用样式类
```

## 🚀 使用示例

### 标准页面结构

```vue
<template>
  <div class="page-container">
    <el-header>
      <div class="header-content">
        <el-button icon="el-icon-back" @click="$router.back()">返回</el-button>
        <h3>页面标题</h3>
        <div class="header-actions">
          <el-button type="primary">主要操作</el-button>
        </div>
      </div>
    </el-header>
    
    <el-main class="page-main">
      <div class="page-main-content">
        <el-card class="content-card">
          <div slot="header" class="card-header">
            <span class="card-title">卡片标题</span>
          </div>
          <!-- 内容 -->
        </el-card>
      </div>
    </el-main>
  </div>
</template>

<style scoped>
.page-container {
  min-height: 100vh;
  background: var(--bg-light);
}

.el-header {
  background: var(--bg-white);
  box-shadow: var(--shadow-sm);
  border-bottom: 1px solid var(--border-color);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  max-width: 1600px;
  margin: 0 auto;
}

.header-content h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-dark);
  flex: 1;
  text-align: center;
}
</style>
```

## 🎨 渐变背景

项目提供了多种预定义渐变：

```css
.gradient-bg          /* 主渐变：紫蓝色 */
.gradient-bg-blue     /* 蓝色渐变 */
.gradient-bg-purple   /* 紫色渐变 */
.gradient-bg-green    /* 绿色渐变 */
.gradient-bg-orange   /* 橙色渐变 */
```

## 📝 更新日志

### 2024-11 样式系统升级

- ✅ 建立统一的设计令牌系统
- ✅ 优化所有页面的视觉一致性
- ✅ 改进卡片、表格、表单样式
- ✅ 增强响应式设计
- ✅ 优化登录页面和仪表板
- ✅ 统一颜色、间距、圆角和阴影

---

**维护者**: DongAI 团队  
**最后更新**: 2024-11
