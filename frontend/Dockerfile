FROM node:18-alpine as build-stage

WORKDIR /app

# 复制依赖文件
COPY package*.json ./

# 安装依赖（容器内走国内镜像源，避免官方源拉包卡住）
RUN npm install --registry=https://registry.npmmirror.com --no-audit --no-fund

# 复制项目文件
COPY . .

# 构建
RUN npm run build

# 生产环境
FROM nginx:alpine as production-stage

# 复制构建产物
COPY --from=build-stage /app/dist /usr/share/nginx/html

# 复制nginx配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
