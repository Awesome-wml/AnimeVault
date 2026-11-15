const { defineConfig } = require('@vue/cli-service')

// 授权服务地址（开发代理用）。端口 18100 是授权服务；不要用 8000/8080/8081。
const API_TARGET = process.env.LICENSE_API_TARGET || 'http://127.0.0.1:18100'
module.exports = defineConfig({
  transpileDependencies: true,
  lintOnSave: false,
  devServer: {
    port: Number(process.env.PORT) || 5180,
    // 浏览器扩展（Vue DevTools、钱包、翻译等）注入脚本抛出的未处理 Promise 错误会被弹层显示成 [object Object]，
    // 与本项目代码无关；运行时错误弹层关闭，编译错误仍会提示。
    client: { overlay: { errors: true, warnings: false, runtimeErrors: false } },
    proxy: {
      '/admin/api': { target: API_TARGET, changeOrigin: true }
    }
  }
})
