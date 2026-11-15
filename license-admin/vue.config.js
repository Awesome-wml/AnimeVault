const { defineConfig } = require('@vue/cli-service')

// 授权服务地址（开发代理用）。端口 18100 是授权服务；不要用 8000/8080/8081。
const API_TARGET = process.env.LICENSE_API_TARGET || 'http://127.0.0.1:18100'
module.exports = defineConfig({
  transpileDependencies: true,
  lintOnSave: false,
  devServer: {
    port: Number(process.env.PORT) || 5180,
    proxy: {
      '/admin/api': { target: API_TARGET, changeOrigin: true }
    }
  }
})
