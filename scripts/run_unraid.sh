#!/bin/bash
set -euo pipefail

# Unraid 建议把项目放到类似目录：
# /mnt/user/appdata/DramaRadar
APP_DIR="${APP_DIR:-/mnt/user/appdata/DramaRadar}"
IMAGE_NAME="${IMAGE_NAME:-dramaradar:latest}"

# 仅首次或镜像不存在时构建；平时定时任务只需要 docker run
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  docker build -t "$IMAGE_NAME" "$APP_DIR"
fi

docker run --rm \
  --name dramaradar_job \
  --env-file "$APP_DIR/.env" \
  -v "$APP_DIR/data:/app/data" \
  "$IMAGE_NAME"

