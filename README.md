# DramaRadar

新剧上线监控（当前实现：猫眼「网播热度」新剧发现 → Telegram 群提醒）。

## 功能

- 每次抓取 `https://piaofang.maoyan.com/web-heat`
- 提取页面中出现过的电视剧片名（含平台/上线天数等简要信息）
- 用 SQLite 持久化去重记录（无需清理，扩展更方便）
- 发现新剧后通过 TG 机器人向群组发送提醒
- 首次运行只建立“基线”，不发送提醒（避免把存量剧集当成新剧刷屏）

## 快速开始

1. 设置环境变量（建议用 `.env` 或你的部署平台密钥管理，不要提交到仓库）：

- `TG_BOT_TOKEN`：你的机器人 Token
- `TG_CHAT_ID`：群组 ID（例如：`-1001889081739`）

1. 手动运行一次：

```powershell
py "scripts/maoyan_web_heat_monitor.py"
```

仅演练不发 TG：

```powershell
py "scripts/maoyan_web_heat_monitor.py" --dry-run
```

## Docker 运行（推荐）

构建镜像：

```bash
docker build -t dramaradar .
```

运行一次（将 `data/` 挂载出来以持久化数据库）：

```bash
docker run --rm \
  -e TG_BOT_TOKEN="你的token" \
  -e TG_CHAT_ID="-1001889081739" \
  -v "$(pwd)/data:/app/data" \
  dramaradar
```
