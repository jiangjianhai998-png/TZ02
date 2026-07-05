# coding=utf-8
"""Runtime compatibility patches for TZ02 GitHub Actions.

This file is imported automatically by Python when the repository root is on
sys.path. It keeps small production hotfixes isolated from large upstream files.
"""

from __future__ import annotations

import builtins
import html
import re
import sys
from typing import Any, Dict, List, Optional

_ORIGINAL_IMPORT = builtins.__import__
_PATCHED = False


_INTERNAL_KEYWORDS = (
    "总新闻",
    "热榜：",
    "RSS：",
    "类型：",
    "最热话题",
    "热点词汇统计",
    "更新时间",
    "增量分析",
    "错误报告",
    "异常报告",
    "AI 分析失败",
    "AI分析失败",
    "分析失败",
    "失败平台",
    "失败详情",
    "异常平台",
    "异常详情",
    "HTTPError",
    "Client Error",
    "Traceback",
    "Exception",
    "DeepSeek",
    "deepseek",
    "api.deepseek.com",
    "Payment Required",
    "402",
)


def _is_public_telegram_target(chat_id: str) -> bool:
    """Return True for Telegram channels/groups that should use public formatting."""
    chat_id_str = str(chat_id or "").strip()
    if not chat_id_str:
        return False

    lowered = chat_id_str.lower()
    # Channel usernames are usually used as @channel_name in TELEGRAM_CHAT_ID.
    # The original sender only treated negative numeric IDs as public, so @channels
    # were mistakenly handled as private debug targets and leaked batch/stat/error lines.
    if chat_id_str.startswith("@"):
        return True
    if lowered.startswith("t.me/") or lowered.startswith("https://t.me/"):
        return True
    if chat_id_str.startswith("-"):
        return True
    return False


def _plain(text: str) -> str:
    text = re.sub(r"<a\s+href=[\"'][^\"']+[\"']\s*>", "", str(text), flags=re.I)
    text = re.sub(r"</a>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _is_internal_line(line: str) -> bool:
    plain = _plain(line).strip()
    if not plain:
        return True
    if re.match(r"^\[第\s*\d+/\d+\s*批次\]", plain):
        return True
    return any(keyword in plain for keyword in _INTERNAL_KEYWORDS)


def _extract_public_item(raw_line: str) -> Optional[Dict[str, str]]:
    """Extract one channel-ready news item from a report line."""
    if not raw_line or _is_internal_line(raw_line):
        return None

    plain = _plain(raw_line).strip()
    if not re.match(r"^\s*\d+[\.|、)]\s+", plain):
        return None

    # Source and time come from the plain line because raw line may contain HTML links.
    source_match = re.match(r"^\s*\d+[\.|、)]\s*\[([^\]]+)\]", plain)
    source = source_match.group(1).strip() if source_match else "热点"

    time_match = re.search(r"[-–—]\s*(\d{1,2}:\d{2})\s*$", plain)
    item_time = time_match.group(1) if time_match else ""

    # Preserve original HTML anchor in the title when present.
    title_html = re.sub(r"^\s*\d+[\.|、)]\s*", "", raw_line.strip())
    title_html = re.sub(r"^\[[^\]]+\]\s*", "", title_html).strip()
    title_html = title_html.replace("🆕", "").strip()
    title_html = re.sub(r"\s*\[\d+\]\s*[-–—]\s*\d{1,2}:\d{2}\s*$", "", title_html).strip()
    title_html = re.sub(r"\s+", " ", title_html).strip()

    title_plain = _plain(title_html).strip()
    if not title_plain:
        return None

    return {"source": source, "title_html": title_html, "time": item_time}


def _compose_public_post(item: Dict[str, str], max_bytes: int = 4000) -> str:
    source = html.escape(item.get("source") or "热点")
    title = item.get("title_html") or ""
    item_time = item.get("time") or ""

    parts = [f"📰 <b>【{source}】</b>", title]
    if item_time:
        parts.extend(["", f"⏱ {item_time} 更新"])

    post = "\n".join(parts).strip()
    if len(post.encode("utf-8")) <= max_bytes:
        return post

    # Fallback: remove HTML and trim safely.
    plain_post = _plain(post)
    encoded = plain_post.encode("utf-8")[: max(200, max_bytes - 20)]
    return encoded.decode("utf-8", errors="ignore").rstrip() + "…"


def _public_micro_posts(content: str, *, batch_index: int, batch_total: int, max_bytes: int = 4000) -> List[str]:
    """Turn system report blocks into clean channel tweets.

    Public Telegram channels should receive only user-facing news posts. Batch
    headers, statistics, AI errors, and crawler diagnostics stay out of the channel.
    """
    items: List[Dict[str, str]] = []
    for raw_line in str(content or "").splitlines():
        item = _extract_public_item(raw_line)
        if item:
            items.append(item)

    if items:
        return [_compose_public_post(item, max_bytes=max_bytes) for item in items]

    # If we cannot identify individual items, still remove all internal lines.
    clean_lines = []
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if line and not _is_internal_line(line):
            clean_lines.append(line)
    if clean_lines:
        text = "\n".join(clean_lines).strip()
        if len(text.encode("utf-8")) > max_bytes:
            text = text.encode("utf-8")[: max(200, max_bytes - 20)].decode("utf-8", errors="ignore").rstrip() + "…"
        return [text]
    return []


def _public_micro_batch(content: str, *, batch_index: int, batch_total: int, max_bytes: int = 4000) -> str:
    posts = _public_micro_posts(content, batch_index=batch_index, batch_total=batch_total, max_bytes=max_bytes)
    return posts[0] if posts else ""


def _patch_senders(module: Any) -> None:
    global _PATCHED
    if _PATCHED or not module:
        return

    original_get_private_ids = getattr(module, "_get_telegram_private_chat_ids", None)

    def _is_telegram_private_target(chat_id: str) -> bool:
        chat_id_str = str(chat_id or "").strip()
        private_ids = set(original_get_private_ids() if original_get_private_ids else [])
        if chat_id_str in private_ids:
            return True
        # @channel_username and -100... IDs are public Telegram targets.
        # Only plain positive numeric user IDs are treated as private.
        return bool(chat_id_str) and not _is_public_telegram_target(chat_id_str)

    module._is_telegram_private_target = _is_telegram_private_target
    module._beautify_public_telegram_batches = _public_micro_posts
    module._beautify_public_telegram_batch = _public_micro_batch
    _PATCHED = True
    print("[TZ02] Telegram public channel micro-post patch enabled")


def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    try:
        senders = sys.modules.get("trendradar.notification.senders")
        if senders is not None:
            _patch_senders(senders)
    except Exception as exc:
        print(f"[TZ02] sitecustomize patch skipped: {exc}")
    return module


builtins.__import__ = _patched_import

# If senders was imported before this hook was installed, patch it immediately.
if "trendradar.notification.senders" in sys.modules:
    _patch_senders(sys.modules["trendradar.notification.senders"])
