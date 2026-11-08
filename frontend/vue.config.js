const { defineConfig } = require('@vue/cli-service')
module.exports = defineConfig({
  transpileDependencies: true,
  lintOnSave: false,  // 禁用ESLint检查以避免构建失败
  devServer: {
    // 前端默认同源请求 /api 与 /static，开发时转发给后端（线上由 nginx 转发）
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/static': { target: 'http://127.0.0.1:8000', changeOrigin: true }
    },
    // 关闭压缩，避免 SSE（小说生成、视频进度）被缓冲
    compress: false,
    client: {
      overlay: {
        warnings: false,
        errors: true,
        // 非 Error 的 Promise 拒绝（常见于浏览器扩展）不弹遮罩，控制台仍可见
        runtimeErrors: (error) => error.message !== '[object Object]'
      }
    }
  }
})
