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
- `TG_CHAT_ID`：群组/频道 ID（例如：`-10010000000`）
- `TG_API_BASE_URL`：Telegram API 代理地址（可选；不设置则默认 `https://api.telegram.org`）
- `DRAMARADAR_TOP_N`：抓取榜单前 N（可选；默认 10）

直接用 `py` 运行时，脚本会自动读取当前目录下的 `.env` 并加载到环境变量（也可用 `DRAMARADAR_ENV_FILE` 指定 `.env` 路径）。

1. 运行一次（推荐用 Docker，避免依赖宿主机 Python）：见下方「Docker 运行」。

## Docker 运行（推荐）

### 方式A：直接使用官方 Python 镜像

```bash
docker run --rm \
  --env-file "/mnt/user/appdata/DramaRadar/.env" \
  -v "/mnt/user/appdata/DramaRadar:/app" \
  -v "/mnt/user/appdata/DramaRadar/data:/app/data" \
  -w /app \
  python:3.13-slim \
  python scripts/maoyan_web_heat_monitor.py
```

仅演练不发 TG：

```bash
docker run --rm \
  --env-file "/mnt/user/appdata/DramaRadar/.env" \
  -v "/mnt/user/appdata/DramaRadar:/app" \
  -w /app \
  python:3.13-slim \
  python scripts/maoyan_web_heat_monitor.py --dry-run
```

### 方式B：构建本项目镜像（可选）

构建镜像：

```bash
docker build -t dramaradar .
```

运行一次（将 `data/` 挂载出来以持久化数据库）：

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  dramaradar
```
