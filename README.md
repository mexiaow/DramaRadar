# DramaRadar

新剧上线监控（当前实现：猫眼「网播热度」新剧发现 → Telegram 群提醒）。

## 功能

- 每次抓取 `https://piaofang.maoyan.com/web-heat`
- 提取页面中出现过的电视剧片名（含平台/上线天数等简要信息）
- 用 SQLite 持久化去重记录（无需清理，扩展更方便）
- 发现新剧后通过 TG 机器人向群组发送提醒
- 首次运行只建立“基线”，不发送提醒（避免把存量剧集当成新剧刷屏）

## 快速开始

1. 复制配置模板为本地配置（该文件已在 `.gitignore` 中忽略，不会被提交）：

```powershell
New-Item -ItemType Directory -Force -Path "config" | Out-Null
Copy-Item "config/config.example.json" "config/local.json"
```

2. 编辑 `config/local.json`：

- `telegram.botToken`：你的机器人 Token（不要提交到仓库）
- `telegram.chatId`：群组 ID（例如：`-1001889081739`）

也支持环境变量（优先级更高）：`TG_BOT_TOKEN`、`TG_CHAT_ID`。

3. 手动运行一次：

```powershell
py "scripts/maoyan_web_heat_monitor.py"
```

仅演练不发 TG：

```powershell
py "scripts/maoyan_web_heat_monitor.py" --dry-run
```

## Windows 定时任务（推荐）

用“任务计划程序”创建一个“每日”任务，操作命令建议如下（按你的实际路径调整）：

```text
程序/脚本：py
添加参数：k:\Projects\DramaRadar\scripts\maoyan_web_heat_monitor.py
起始于：k:\Projects\DramaRadar
```

也可以用命令行创建（示例：每天 09:00 执行一次）：

```powershell
schtasks /Create /F /TN "DramaRadar_MaoyanWebHeat" /SC DAILY /ST 09:00 /TR "py \"k:\Projects\DramaRadar\scripts\maoyan_web_heat_monitor.py\""
```

## 关于机器人共用

同一个 Telegram Bot Token 可以被多个程序同时调用（例如都只调用 `sendMessage`），一般没问题。

可能的弊端：

- Token 一旦泄露，所有程序都受影响（建议仅放本地配置或环境变量）
- 多程序同时发消息会共享 Telegram 的限流/配额与消息顺序（可能出现“先后顺序不稳定”）

如果你希望隔离风险、区分来源或未来要做更复杂的交互，建议单独申请一个新机器人。
