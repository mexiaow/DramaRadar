#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import gzip
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Optional
from zoneinfo import ZoneInfo


MAOYAN_URL = "https://piaofang.maoyan.com/web-heat"
MAOYAN_REFERER = "https://piaofang.maoyan.com/"
try:
    TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
except Exception:
    # 容器缺少 tzdata 时的兜底（仍尽量用北京时间）
    TZ_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DEFAULT_TOP_N = 30


@dataclass(frozen=True)
class DramaItem:
    name: str
    platform: str
    is_first_day: bool
    online_desc: str


class MaoyanWebHeatParser(HTMLParser):
    """
    解析猫眼「网播热度」页面：提取 .video-name 与 .web-info。
    采用标准库 HTMLParser，避免引入第三方依赖。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._current: Optional[str] = None  # "name" | "info" | None
        self._buffer: list[str] = []
        self.names: list[str] = []
        self.infos: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "p":
            return

        classes = ""
        for k, v in attrs:
            if k == "class" and v:
                classes = v
                break

        class_list = set(classes.split())
        if "video-name" in class_list:
            self._current = "name"
            self._buffer = []
        elif "web-info" in class_list:
            self._current = "info"
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if data:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "p" or self._current is None:
            return

        text = " ".join("".join(self._buffer).split()).strip()
        if self._current == "name":
            if text:
                self.names.append(text)
        elif self._current == "info":
            # 原始信息：如“腾讯视频独播 上线8天”“芒果TV独播 上线首日”
            self.infos.append(text)

        self._current = None
        self._buffer = []


def now_shanghai() -> datetime:
    return datetime.now(tz=TZ_SHANGHAI)


def shanghai_date_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def shanghai_datetime_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def load_telegram_from_env() -> dict[str, str]:
    bot_token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    return {"bot_token": bot_token, "chat_id": chat_id}


def load_dotenv_if_present(env_path: str) -> None:
    """
    轻量 .env 加载器（不依赖第三方库）。
    规则：
    - 仅在环境变量未设置时才从 .env 填充（避免覆盖部署环境/容器传入值）
    - 支持 KEY=VALUE，忽略空行与 # 注释
    - 支持 export KEY=VALUE
    - 支持用单/双引号包裹的值
    """
    if not env_path:
        return
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower().startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key:
                    continue
                if key in os.environ and os.environ.get(key, "").strip():
                    continue
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                os.environ[key] = value
    except OSError as e:
        raise RuntimeError(f"读取 .env 失败：{env_path}；原因：{e}") from e


def get_telegram_api_base_url() -> str:
    """
    Telegram API Base URL（用于代理）。
    - 未设置时：默认 https://api.telegram.org
    - 设置 TG_API_BASE_URL 时：使用该地址（会自动去掉末尾 /）
    """
    default_base = "https://api.telegram.org"
    raw = os.environ.get("TG_API_BASE_URL", "").strip()
    if not raw:
        return default_base

    base = raw.rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("TG_API_BASE_URL 格式不正确：必须是 http/https URL，例如 https://tg.example.com")
    return base


def fetch_maoyan_html(timeout_sec: int = 15, retries: int = 3, verbose: bool = False) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip",
        "Referer": MAOYAN_REFERER,
    }

    last_error: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(MAOYAN_URL, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding", "")
                if encoding.lower() == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = e
            if verbose:
                print(f"[WARN] 抓取失败（第{attempt}/{retries}次）：{e}", file=sys.stderr)
            if attempt < retries:
                time.sleep(0.8 * attempt)

    raise RuntimeError(f"抓取失败：已耗尽重试次数；最后错误：{last_error}")


def extract_platform(info: str) -> str:
    """
    从“平台 + 上线X天/首日”中提取稳定的“平台”部分，避免天数导致每日无意义变化。
    """
    if not info:
        return ""
    idx = info.find("上线")
    base = info[:idx] if idx >= 0 else info
    return " ".join(base.split()).strip()


def is_first_day_info(info: str) -> bool:
    return "上线首日" in (info or "")


def extract_online_desc(info: str) -> str:
    """
    提取“上线X天/上线首日”等动态信息，仅用于通知/日志展示，不写入数据库。
    """
    if not info:
        return ""
    idx = info.find("上线")
    if idx < 0:
        return ""
    return " ".join(info[idx:].split()).strip()


def parse_drama_items(html: str) -> list[DramaItem]:
    parser = MaoyanWebHeatParser()
    parser.feed(html)

    if not parser.names:
        raise RuntimeError("未解析到任何片名：可能页面结构已变化或被反爬拦截")

    items: list[DramaItem] = []
    for i, name in enumerate(parser.names):
        raw_info = parser.infos[i] if i < len(parser.infos) else ""
        items.append(
            DramaItem(
                name=name,
                platform=extract_platform(raw_info),
                is_first_day=is_first_day_info(raw_info),
                online_desc=extract_online_desc(raw_info),
            )
        )

    # 去重：同名只保留首次出现的那条
    unique: dict[str, DramaItem] = {}
    for it in items:
        if it.name not in unique:
            unique[it.name] = it
    return list(unique.values())


def open_db(db_path: str) -> sqlite3.Connection:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    ensure_db_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )
    return conn


def open_db_readonly(db_path: str) -> sqlite3.Connection:
    # 只读模式：用于 --dry-run，避免创建/修改DB文件
    uri = f"file:{db_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def ensure_db_schema(conn: sqlite3.Connection) -> None:
    """
    维护数据库表结构：
    - 当前版本不再把 URL/source 存入数据库（避免无意义冗余）
    - 若发现旧库仍含 source 且为 NOT NULL，则自动迁移到新结构
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dramas (
          name TEXT PRIMARY KEY,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          last_info TEXT NOT NULL
        )
        """
    )

    cols = [row[1] for row in conn.execute("PRAGMA table_info(dramas)")]
    if "source" not in cols:
        return

    # 旧库迁移：重建表以移除 source 列（兼容 SQLite 版本，不依赖 DROP COLUMN）
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dramas_new (
              name TEXT PRIMARY KEY,
              first_seen TEXT NOT NULL,
              last_seen TEXT NOT NULL,
              last_info TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO dramas_new(name, first_seen, last_seen, last_info)
            SELECT name, first_seen, last_seen, last_info FROM dramas
            """
        )
        conn.execute("DROP TABLE dramas")
        conn.execute("ALTER TABLE dramas_new RENAME TO dramas")


def db_is_empty(conn: sqlite3.Connection) -> bool:
    cur = conn.execute("SELECT COUNT(1) FROM dramas")
    count = int(cur.fetchone()[0])
    return count == 0


def db_insert_baseline(conn: sqlite3.Connection, items: list[DramaItem], dt: datetime) -> None:
    day = shanghai_date_str(dt)
    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO dramas(name, first_seen, last_seen, last_info)
            VALUES(?, ?, ?, ?)
            """,
            [(it.name, day, day, it.platform) for it in items],
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("last_run_at", dt.isoformat()),
        )


def db_find_new_items(conn: sqlite3.Connection, items: list[DramaItem]) -> list[DramaItem]:
    new_items: list[DramaItem] = []
    for it in items:
        cur = conn.execute("SELECT 1 FROM dramas WHERE name = ? LIMIT 1", (it.name,))
        if cur.fetchone() is None:
            new_items.append(it)
    return new_items


def db_upsert_items(conn: sqlite3.Connection, items: list[DramaItem], dt: datetime) -> None:
    day = shanghai_date_str(dt)
    with conn:
        for it in items:
            conn.execute(
                """
                INSERT INTO dramas(name, first_seen, last_seen, last_info)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  last_seen=excluded.last_seen,
                  last_info=CASE WHEN excluded.last_info != '' THEN excluded.last_info ELSE dramas.last_info END
                """,
                (it.name, day, day, it.platform),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("last_run_at", dt.isoformat()),
        )


def build_telegram_text(new_items: list[DramaItem], dt: datetime) -> str:
    lines: list[str] = [f"🎯 发现猫眼网播热度新剧（{len(new_items)}部）"]
    for it in new_items:
        parts: list[str] = []
        if it.platform:
            parts.append(it.platform)
        if it.online_desc:
            parts.append(it.online_desc)
        if parts:
            lines.append(f"- {it.name}（{'；'.join(parts)}）")
        else:
            lines.append(f"- {it.name}")
    lines.append(f"来源：{MAOYAN_URL}")
    lines.append(f"时间：{shanghai_datetime_str(dt)}")
    return "\n".join(lines)


def format_item_for_log(it: DramaItem) -> str:
    parts: list[str] = []
    if it.platform:
        parts.append(it.platform)
    if it.online_desc:
        parts.append(it.online_desc)
    if parts:
        return f"- {it.name}（{'；'.join(parts)}）"
    return f"- {it.name}"


def log_items(title: str, items: list[DramaItem], limit: int = 200) -> None:
    print(f"[INFO] {title}（{len(items)}部）")
    shown = items[:limit]
    for it in shown:
        print(format_item_for_log(it))
    if len(items) > limit:
        print(f"[INFO] 仅展示前 {limit} 部，剩余 {len(items) - limit} 部已省略")


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout_sec: int = 15) -> None:
    if not bot_token or not chat_id:
        raise RuntimeError("缺少TG配置：请设置环境变量 TG_BOT_TOKEN / TG_CHAT_ID")

    base_url = get_telegram_api_base_url()
    url = f"{base_url}/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status != 200:
                raise RuntimeError(f"TG发送失败：HTTP {resp.status}：{body[:300]}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TG发送失败：HTTP {e.code}：{detail[:300]}") from e


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="猫眼网播热度新剧监控（发现新剧后TG提醒）")
    parser.add_argument("--dry-run", action="store_true", help="演练模式：不写DB、不发TG")
    parser.add_argument("--no-telegram", action="store_true", help="不发送TG（但仍更新DB）")
    parser.add_argument("--verbose", action="store_true", help="输出更多日志")
    parser.add_argument("--db-path", default=os.environ.get("DRAMARADAR_DB_PATH", "data/dramaradar.db"))
    return parser.parse_args(argv)


def get_top_n_from_env() -> int:
    raw = os.environ.get("DRAMARADAR_TOP_N", "").strip()
    if not raw:
        return DEFAULT_TOP_N
    try:
        n = int(raw)
    except ValueError as e:
        raise RuntimeError("DRAMARADAR_TOP_N 必须是整数，例如 10") from e
    if n <= 0 or n > 100:
        raise RuntimeError("DRAMARADAR_TOP_N 范围应为 1~100")
    return n


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    load_dotenv_if_present(os.environ.get("DRAMARADAR_ENV_FILE", ".env"))
    tg = load_telegram_from_env()

    html = fetch_maoyan_html(verbose=bool(args.verbose))
    items = parse_drama_items(html)
    top_n = get_top_n_from_env()
    items = items[:top_n]
    log_items("本次抓取到的剧集", items)

    dt = now_shanghai()
    db_path = str(args.db_path)

    if args.dry_run and not os.path.exists(db_path):
        print(f"[DRY] 首次运行将建立基线（{len(items)}部），不创建DB、不写入、不发送TG")
        return 0

    conn: sqlite3.Connection
    if args.dry_run:
        conn = open_db_readonly(db_path)
    else:
        conn = open_db(db_path)

    try:
        if db_is_empty(conn):
            # 首次运行：建立“基线”，不提醒（避免把存量剧集当成新剧刷屏）
            if args.dry_run:
                print(f"[DRY] 首次运行将建立基线（{len(items)}部），不写入、不发送TG")
                return 0
            db_insert_baseline(conn, items, dt)
            print(f"[OK] 首次运行已建立基线（{len(items)}部），未发送TG提醒；DB：{db_path}")
            return 0

        new_items = db_find_new_items(conn, items)
        if new_items:
            log_items("本次新出现的剧集", new_items)
        else:
            print("[INFO] 本次无新剧出现")

        if args.dry_run:
            print(f"[DRY] 本次抓取到 {len(items)} 部；新增 {len(new_items)} 部；不写入、不发送TG")
            if new_items:
                print(build_telegram_text(new_items, dt))
            return 0

        if new_items and not args.no_telegram:
            text = build_telegram_text(new_items, dt)
            send_telegram_message(tg["bot_token"], tg["chat_id"], text)
            print("[OK] 已发送TG提醒")
        elif new_items and args.no_telegram:
            print("[OK] 检测到新剧，但按参数跳过TG发送（--no-telegram）")

        db_upsert_items(conn, items, dt)
        print(f"[OK] 本次抓取到 {len(items)} 部；新增 {len(new_items)} 部；DB：{db_path}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as e:
        print(f"[ERR] {e}", file=sys.stderr)
        raise SystemExit(1)
