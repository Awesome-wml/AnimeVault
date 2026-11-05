#!/bin/bash
cd "$(dirname "$0")"
export MONGODB_URL="mongodb://admin:dongai_mongo_2024@localhost:27017/"
export MONGODB_DB_NAME=dongai
export REDIS_URL="redis://localhost:6379/0"
export STATIC_DIR="/Users/dongxiangyu/PycharmProjects/dongai/static"
export TZ=Asia/Shanghai
.venv-host/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
