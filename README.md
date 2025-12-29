# DramaRadar

新剧上线监控（当前实现：猫眼「网播热度」新剧发现 → Telegram 提醒）。

## 功能

- 每次抓取 `https://piaofang.maoyan.com/web-heat`
- 仅提取榜单前 10 的电视剧片名（含平台/上线天数等简要信息）
- 用 SQLite 持久化去重记录（无需清理，扩展更方便）
- 发现新剧后通过 TG 机器人向群组发送提醒
- 首次运行只建立“基线”，不发送提醒（避免把存量剧集当成新剧刷屏）

## 快速开始

1. 准备 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 填入以下变量：

- `TG_BOT_TOKEN`：你的机器人 Token
- `TG_CHAT_ID`：群组/频道 ID（例如：`-1001889081739`）
- `TG_API_BASE_URL`：Telegram API 代理地址（可选；不设置则默认 `https://api.telegram.org`）
- `DRAMARADAR_TOP_N`：抓取榜单前 N（可选；默认 10）

直接用 `py` 运行时，脚本会自动读取当前目录下的 `.env` 并加载到环境变量（也可用 `DRAMARADAR_ENV_FILE` 指定 `.env` 路径）。

1. 运行一次（推荐用 Docker，避免依赖宿主机 Python）：见下方「Docker 运行」。

## Docker 运行（推荐）

### 方式A：构建本项目镜像（推荐）

在 Unraid 上（示例路径：`/mnt/user/appdata/DramaRadar`）构建一次：

```bash
docker build -t dramaradar:latest /mnt/user/appdata/DramaRadar
```

```bash
docker run --rm \
  --env-file "/mnt/user/appdata/DramaRadar/.env" \
  -v "/mnt/user/appdata/DramaRadar/data:/app/data" \
  dramaradar:latest
```

通用构建命令（在仓库目录执行）：

构建镜像：

```bash
docker build -t dramaradar:latest .
```

运行一次（将 `data/` 挂载出来以持久化数据库）：

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  dramaradar:latest
```

## 定时执行（Unraid 推荐）

这个项目不需要常驻运行，按计划每天跑一次即可。

推荐安装 Unraid 的 `User Scripts` 插件，然后创建一个“每日”脚本执行一次容器：

```bash
#!/bin/bash
set -euo pipefail

APP_DIR="/mnt/user/appdata/DramaRadar"
IMAGE_NAME="dramaradar:latest"

# 首次或镜像不存在才构建；平时定时任务只跑容器
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
  docker build -t "$IMAGE_NAME" "$APP_DIR"
fi

docker run --rm \
  --name dramaradar_job \
  --env-file "$APP_DIR/.env" \
  -v "$APP_DIR/data:/app/data" \
  "$IMAGE_NAME"
```

同样的脚本模板也在仓库里：`scripts/run_unraid.sh`。

### 方式B：直接使用官方 Python 镜像（备选）

不构建镜像，直接用官方 Python 镜像临时运行：

```bash
docker run --rm \
  --env-file "/mnt/user/appdata/DramaRadar/.env" \
  -v "/mnt/user/appdata/DramaRadar:/app" \
  -v "/mnt/user/appdata/DramaRadar/data:/app/data" \
  -w /app \
  python:3.13-slim \
  python scripts/maoyan_web_heat_monitor.py
```
