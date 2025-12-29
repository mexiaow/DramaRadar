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
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Optional
from zoneinfo import ZoneInfo


MAOYAN_URL = "https://piaofang.maoyan.com/web-heat"
MAOYAN_REFERER = "https://piaofang.maoyan.com/"
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DramaItem:
    name: str
    platform: str
    is_first_day: bool


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


def read_json_file(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config(config_path: str) -> dict[str, str]:
    cfg: dict[str, Any] = {}
    if os.path.exists(config_path):
        cfg = read_json_file(config_path)

    telegram = cfg.get("telegram", {}) if isinstance(cfg, dict) else {}
    bot_token = os.environ.get("TG_BOT_TOKEN") or telegram.get("botToken") or ""
    chat_id = os.environ.get("TG_CHAT_ID") or telegram.get("chatId") or ""

    return {"bot_token": str(bot_token), "chat_id": str(chat_id)}


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
            )
        )

    # 去重：同名只保留首次出现的那条
    unique: dict[str, DramaItem] = {}
    for it in items:
        if it.name not in unique:
            unique[it.name] = it
    return list(unique.values())


def open_db(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dramas (
          name TEXT PRIMARY KEY,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          last_info TEXT NOT NULL,
          source TEXT NOT NULL
        )
        """
    )
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


def db_is_empty(conn: sqlite3.Connection) -> bool:
    cur = conn.execute("SELECT COUNT(1) FROM dramas")
    count = int(cur.fetchone()[0])
    return count == 0


def db_insert_baseline(conn: sqlite3.Connection, items: list[DramaItem], dt: datetime) -> None:
    day = shanghai_date_str(dt)
    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO dramas(name, first_seen, last_seen, last_info, source)
            VALUES(?, ?, ?, ?, ?)
            """,
            [(it.name, day, day, it.platform, MAOYAN_URL) for it in items],
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
                INSERT INTO dramas(name, first_seen, last_seen, last_info, source)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  last_seen=excluded.last_seen,
                  last_info=CASE WHEN excluded.last_info != '' THEN excluded.last_info ELSE dramas.last_info END
                """,
                (it.name, day, day, it.platform, MAOYAN_URL),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("last_run_at", dt.isoformat()),
        )


def build_telegram_text(new_items: list[DramaItem], dt: datetime) -> str:
    lines: list[str] = [f"🎯 发现猫眼网播热度新剧（{len(new_items)}部）"]
    for it in new_items:
        if it.platform and it.is_first_day:
            lines.append(f"- {it.name}（{it.platform}；上线首日）")
        elif it.platform:
            lines.append(f"- {it.name}（{it.platform}）")
        else:
            lines.append(f"- {it.name}")
    lines.append(f"来源：{MAOYAN_URL}")
    lines.append(f"时间：{shanghai_datetime_str(dt)}")
    return "\n".join(lines)


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout_sec: int = 15) -> None:
    if not bot_token or not chat_id:
        raise RuntimeError("缺少TG配置：请设置TG_BOT_TOKEN/TG_CHAT_ID或在config/local.json中配置")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
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
    parser.add_argument("--config-path", default=os.environ.get("DRAMARADAR_CONFIG_PATH", "config/local.json"))
    parser.add_argument("--db-path", default=os.environ.get("DRAMARADAR_DB_PATH", "data/maoyan_web_heat.sqlite3"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config_path)

    html = fetch_maoyan_html(verbose=bool(args.verbose))
    items = parse_drama_items(html)

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

        if args.dry_run:
            print(f"[DRY] 本次抓取到 {len(items)} 部；新增 {len(new_items)} 部；不写入、不发送TG")
            if new_items:
                print(build_telegram_text(new_items, dt))
            return 0

        if new_items and not args.no_telegram:
            text = build_telegram_text(new_items, dt)
            send_telegram_message(cfg["bot_token"], cfg["chat_id"], text)
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
