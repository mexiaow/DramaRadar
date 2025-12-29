#!/bin/bash
set -euo pipefail

# Unraid 建议把项目放到类似目录：
# /mnt/user/appdata/DramaRadar
APP_DIR="${APP_DIR:-/mnt/user/appdata/DramaRadar}"
BASE_IMAGE="${BASE_IMAGE:-dramaradar-python:3.13}"

# 仅首次或镜像不存在时构建基础镜像（日常定时不需要每次构建）
if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  docker build -t "$BASE_IMAGE" -f "$APP_DIR/Dockerfile.base" "$APP_DIR"
fi

docker run --rm \
  --name dramaradar_job \
  --env-file "$APP_DIR/.env" \
  -v "$APP_DIR:/app" \
  -v "$APP_DIR/data:/app/data" \
  -w /app \
  "$BASE_IMAGE" \
  python scripts/maoyan_web_heat_monitor.py
