# coding=utf-8
"""Apply TZ02 Telegram public layout and two-level menu patch.

目标版面：
1. 短视频/图片内容
2. AI原创短评
3. 点赞/评论
4. 体育赛事 / 博彩娱乐 二级菜单

按钮逻辑：
- 主菜单：🏀 体育赛事 / 🎰 博彩娱乐
- 体育赛事：NBA / 足球 / 直播 / 集锦 / 返回主菜单
- 博彩娱乐：百家乐 / 德州扑克 / 龙虎斗 / 电子游戏 / 返回主菜单
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENDERS_PATH = ROOT / "trendradar" / "notification" / "senders.py"
INTERACTIONS_PATH = ROOT / "trendradar" / "notification" / "telegram_interactions.py"

SENDERS_HELPER = r'''

def _tz02_button_url(key: str) -> str:
    """Read menu target URL from env/secrets."""
    env_map = {
        "nba": "TELEGRAM_MENU_NBA_URL",
        "football": "TELEGRAM_MENU_FOOTBALL_URL",
        "live": "TELEGRAM_MENU_LIVE_URL",
        "highlights": "TELEGRAM_MENU_HIGHLIGHTS_URL",
        "baccarat": "TELEGRAM_MENU_BACCARAT_URL",
        "poker": "TELEGRAM_MENU_POKER_URL",
        "dragon_tiger": "TELEGRAM_MENU_DRAGON_TIGER_URL",
        "egame": "TELEGRAM_MENU_EGAME_URL",
    }
    return os.environ.get(env_map.get(key, ""), "").strip()


def _build_public_telegram_reply_markup(view: str = "main", like_count: Optional[int] = None) -> Dict[str, Any]:
    """Build TZ02 two-level Telegram inline menu."""
    like_label = "👍 点赞" if like_count is None or like_count <= 0 else f"👍 {like_count}"
    keyboard = [[
        {"text": like_label, "callback_data": "tr_like"},
        {"text": "💬 评论", "callback_data": "tr_comment"},
    ]]

    def item(text: str, key: str) -> Dict[str, str]:
        url = _tz02_button_url(key)
        if url.startswith(("http://", "https://", "tg://")):
            return {"text": text, "url": url}
        return {"text": text, "callback_data": f"tr_link:{key}"}

    if view == "sports":
        keyboard.extend([
            [item("🏀 NBA", "nba"), item("⚽ 足球", "football")],
            [item("📺 直播", "live"), item("🏆 集锦", "highlights")],
            [{"text": "🔙 返回主菜单", "callback_data": "tr_menu:main"}],
        ])
    elif view == "casino":
        keyboard.extend([
            [item("🎰 百家樂", "baccarat"), item("🃏 德州扑克", "poker")],
            [item("🐉 龙虎斗", "dragon_tiger"), item("🎮 电子游戏", "egame")],
            [{"text": "🔙 返回主菜单", "callback_data": "tr_menu:main"}],
        ])
    else:
        keyboard.extend([
            [
                {"text": "🏀 体育赛事", "callback_data": "tr_menu:sports"},
                {"text": "🎰 博彩娱乐", "callback_data": "tr_menu:casino"},
            ]
        ])
    return {"inline_keyboard": keyboard}


def _tz02_strip_public_old_template(text: str) -> str:
    """Remove old public template labels while preserving useful article text."""
    if not text:
        return ""
    plain = _telegram_plain_fallback(str(text))
    remove_contains = (
        "TrendRadar 原创编辑快报",
        "TrendRadar 热点快报",
        "要点评论",
        "核心看点",
        "传播价值",
        "行业观察",
        "编辑短文",
        "当前先编辑为自有短文",
        "不把评论按钮跳转到源链接",
        "这条内容不是简单转发源链接",
        "我们会把信息提取、压缩、改写成自己的视频文章结构",
    )
    cleaned = []
    for raw in plain.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("━"):
            continue
        if any(token in line for token in remove_contains):
            continue
        line = re.sub(r"^📰\s*", "", line).strip()
        if line:
            cleaned.append(line)

    # 去重，避免旧模板里标题重复出现。
    result = []
    seen = set()
    for line in cleaned:
        key = line[:120]
        if key in seen:
            continue
        seen.add(key)
        result.append(line)
    return "\n".join(result).strip()


def _tz02_extract_short_comment(text: str) -> str:
    """Create a short own-comment paragraph from available content."""
    body = _tz02_strip_public_old_template(text)
    if not body:
        return "这条热点内容已完成二次整理，适合继续剪辑成短视频，并引导用户进入相关频道讨论。"
    lines = [line for line in body.splitlines() if line.strip()]
    picked = " ".join(lines[:2]).strip()
    picked = re.sub(r"\s+", " ", picked)
    if len(picked) > 90:
        picked = picked[:87].rstrip() + "..."
    return picked or "这条热点内容已完成二次整理，适合继续剪辑成短视频，并引导用户进入相关频道讨论。"


def _format_tz02_public_post(text: str, max_bytes: int = 3900) -> str:
    """Force final Telegram public post into TZ02 layout before sending."""
    source = _tz02_strip_public_old_template(text)
    comment = _tz02_extract_short_comment(text)

    if not source:
        source = "热点视频/图片内容已抓取，等待进一步剪辑与分发。"

    # 内容区尽量短，避免 Telegram 4000 字节限制。
    if len(source) > 650:
        source = source[:647].rstrip() + "..."

    parts = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🎬 <b>热点短视频/图片</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        source,
        "━━━━━━━━━━━━━━━━━━━━━━",
        "📝 <b>AI原创短评</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        comment,
        "━━━━━━━━━━━━━━━━━━━━━━",
        "🏀 <b>体育赛事</b>",
        "🎰 <b>博彩娱乐</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    result = "\n".join(parts).strip()
    if len(result.encode("utf-8")) > max_bytes:
        result = "\n".join([
            "🎬 <b>热点短视频/图片</b>",
            source[:450].rstrip() + ("..." if len(source) > 450 else ""),
            "━━━━━━━━━━━━━━",
            "📝 <b>AI原创短评</b>",
            comment,
            "━━━━━━━━━━━━━━",
            "🏀 <b>体育赛事</b>",
            "🎰 <b>博彩娱乐</b>",
        ]).strip()
    return result
'''

INTERACTIONS_CONTENT = r'''# coding=utf-8
"""Telegram custom interactions for TZ02 two-level menu."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_VERSION = 4
DEFAULT_STATE_PATH = "data/telegram_interactions_state.json"
DEFAULT_POLL_SECONDS = 21000
DEFAULT_POLL_TIMEOUT = 20


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "offset": 0, "likes": {}, "liked_by": {}, "views": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data["version"] = STATE_VERSION
    data.setdefault("offset", 0)
    data.setdefault("likes", {})
    data.setdefault("liked_by", {})
    data.setdefault("views", {})
    return data


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _api(token: str, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout + 5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"[TG互动] API HTTPError method={method} status={exc.code} body={body[:300]}")
        return {"ok": False, "error_code": exc.code, "description": body}
    except Exception as exc:
        print(f"[TG互动] API Error method={method}: {exc}")
        return {"ok": False, "description": str(exc)}


def _prepare_bot(token: str) -> None:
    result = _api(token, "deleteWebhook", {"drop_pending_updates": False}, timeout=10)
    print(f"[TG互动] deleteWebhook ok={result.get('ok')}")
    info = _api(token, "getMe", {}, timeout=10)
    if info.get("ok"):
        username = (info.get("result") or {}).get("username", "")
        print(f"[TG互动] bot connected @{username}")


def _message_ref(message: Dict[str, Any]) -> tuple[Any, Any]:
    chat = message.get("chat") or {}
    return chat.get("id"), message.get("message_id")


def _answer(token: str, callback_id: str, text: str = "") -> None:
    payload: Dict[str, Any] = {
        "callback_query_id": callback_id,
        "show_alert": False,
        "cache_time": 0,
    }
    if text:
        payload["text"] = text[:180]
    _api(token, "answerCallbackQuery", payload)


def _button_url(key: str) -> str:
    env_map = {
        "nba": "TELEGRAM_MENU_NBA_URL",
        "football": "TELEGRAM_MENU_FOOTBALL_URL",
        "live": "TELEGRAM_MENU_LIVE_URL",
        "highlights": "TELEGRAM_MENU_HIGHLIGHTS_URL",
        "baccarat": "TELEGRAM_MENU_BACCARAT_URL",
        "poker": "TELEGRAM_MENU_POKER_URL",
        "dragon_tiger": "TELEGRAM_MENU_DRAGON_TIGER_URL",
        "egame": "TELEGRAM_MENU_EGAME_URL",
    }
    return os.environ.get(env_map.get(key, ""), "").strip()


def _url_or_callback(text: str, key: str) -> Dict[str, str]:
    url = _button_url(key)
    if url.startswith(("http://", "https://", "tg://")):
        return {"text": text, "url": url}
    return {"text": text, "callback_data": f"tr_link:{key}"}


def _build_reply_markup(view: str = "main", like_count: int = 0) -> Dict[str, Any]:
    like_label = "👍 点赞" if like_count <= 0 else f"👍 {like_count}"
    keyboard = [[
        {"text": like_label, "callback_data": "tr_like"},
        {"text": "💬 评论", "callback_data": "tr_comment"},
    ]]

    if view == "sports":
        keyboard.extend([
            [_url_or_callback("🏀 NBA", "nba"), _url_or_callback("⚽ 足球", "football")],
            [_url_or_callback("📺 直播", "live"), _url_or_callback("🏆 集锦", "highlights")],
            [{"text": "🔙 返回主菜单", "callback_data": "tr_menu:main"}],
        ])
    elif view == "casino":
        keyboard.extend([
            [_url_or_callback("🎰 百家樂", "baccarat"), _url_or_callback("🃏 德州扑克", "poker")],
            [_url_or_callback("🐉 龙虎斗", "dragon_tiger"), _url_or_callback("🎮 电子游戏", "egame")],
            [{"text": "🔙 返回主菜单", "callback_data": "tr_menu:main"}],
        ])
    else:
        keyboard.append([
            {"text": "🏀 体育赛事", "callback_data": "tr_menu:sports"},
            {"text": "🎰 博彩娱乐", "callback_data": "tr_menu:casino"},
        ])
    return {"inline_keyboard": keyboard}


def _edit_markup(token: str, message: Dict[str, Any], view: str, like_count: int) -> bool:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return False
    result = _api(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": _build_reply_markup(view=view, like_count=like_count),
    })
    if result.get("ok"):
        print(f"[TG互动] 已更新按钮 chat={chat_id} message={message_id} view={view} likes={like_count}")
        return True
    print(f"[TG互动] 更新按钮失败 result={result}")
    return False


def _handle_callback(token: str, state: Dict[str, Any], callback: Dict[str, Any]) -> bool:
    callback_id = str(callback.get("id") or "")
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    user = callback.get("from") or {}
    user_id = str(user.get("id") or "")
    if not callback_id or not data.startswith("tr_"):
        return False

    chat_id, message_id = _message_ref(message)
    key = f"{chat_id}:{message_id}"
    like_count = int(state.setdefault("likes", {}).get(key, 0) or 0)
    current_view = state.setdefault("views", {}).get(key, "main")

    if data.startswith("tr_like"):
        liked_map = state.setdefault("liked_by", {})
        liked_users = liked_map.setdefault(key, [])
        if user_id and user_id in liked_users:
            liked_users.remove(user_id)
            action_text = "已取消点赞"
        else:
            if user_id:
                liked_users.append(user_id)
            action_text = "已点赞"
        like_count = len(liked_users)
        state.setdefault("likes", {})[key] = like_count
        _edit_markup(token, message, current_view, like_count)
        _answer(token, callback_id, f"{action_text}，当前 {like_count} 个赞")
        return True

    if data.startswith("tr_comment"):
        _answer(token, callback_id, "评论入口已保留。可以在消息下方留言互动，不会跳转源链接。")
        return False

    if data.startswith("tr_menu:"):
        view = data.split(":", 1)[-1] or "main"
        if view not in {"main", "sports", "casino"}:
            view = "main"
        state.setdefault("views", {})[key] = view
        _edit_markup(token, message, view, like_count)
        if view == "main":
            _answer(token, callback_id, "已返回主菜单")
        elif view == "sports":
            _answer(token, callback_id, "体育赛事菜单")
        else:
            _answer(token, callback_id, "博彩娱乐菜单")
        return True

    if data.startswith("tr_link:"):
        link_key = data.split(":", 1)[-1]
        _answer(token, callback_id, f"{link_key} 频道链接还没配置，请先在 GitHub Secrets 设置对应 TELEGRAM_MENU_*_URL。")
        return False

    _answer(token, callback_id, "按钮已收到。")
    return False


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _prepare_bot(token)
    state = _load_state(state_path)
    changed = False
    started_at = time.time()
    print(f"[TG互动] two-level-menu worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")

    while time.time() - started_at < poll_seconds:
        result = _api(token, "getUpdates", {
            "offset": int(state.get("offset") or 0),
            "timeout": poll_timeout,
            "allowed_updates": ["callback_query"],
        }, timeout=poll_timeout + 10)
        if not result.get("ok"):
            time.sleep(5)
            continue

        for update in result.get("result") or []:
            update_id = int(update.get("update_id") or 0)
            if update_id >= int(state.get("offset") or 0):
                state["offset"] = update_id + 1
                changed = True
            if "callback_query" in update:
                changed = _handle_callback(token, state, update["callback_query"]) or changed
            if changed:
                _save_state(state_path, state)

    if changed:
        _save_state(state_path, state)
    print("[TG互动] two-level-menu worker finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram TZ02 two-level menu worker")
    parser.add_argument("--state", default=os.getenv("TELEGRAM_INTERACTION_STATE", DEFAULT_STATE_PATH))
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("TELEGRAM_INTERACTION_POLL_SECONDS", DEFAULT_POLL_SECONDS)))
    parser.add_argument("--poll-timeout", type=int, default=int(os.getenv("TELEGRAM_INTERACTION_POLL_TIMEOUT", DEFAULT_POLL_TIMEOUT)))
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("[TG互动] TELEGRAM_BOT_TOKEN is empty, skip.")
        return
    poll(token, Path(args.state), args.poll_seconds, args.poll_timeout)


if __name__ == "__main__":
    main()
'''


def patch_senders() -> None:
    text = SENDERS_PATH.read_text(encoding="utf-8")
    changed = False

    # Replace old helper if present, otherwise insert before _extract_ai_stats.
    start = text.find("\ndef _get_public_telegram_menu_items()")
    end = text.find("\ndef _extract_ai_stats(ai_analysis)")
    if end == -1:
        raise RuntimeError("Cannot locate _extract_ai_stats marker in senders.py")
    if start != -1 and start < end:
        text = text[:start] + SENDERS_HELPER + text[end:]
        changed = True
    elif "def _build_public_telegram_reply_markup" not in text:
        text = text[:end] + SENDERS_HELPER + text[end:]
        changed = True

    # Force final public Telegram body into the new TZ02 layout immediately before payload creation.
    marker = '''        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
'''
    replacement = '''        if not is_private_target:
            batch_content = _format_tz02_public_post(batch_content, max_bytes=batch_size - 100)

        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if not is_private_target:
            payload["reply_markup"] = _build_public_telegram_reply_markup("main")
'''
    if marker in text:
        text = text.replace(marker, replacement, 1)
        changed = True
    elif "_format_tz02_public_post(batch_content" not in text:
        raise RuntimeError("Cannot locate Telegram payload marker in senders.py")

    fallback_marker = '''                fallback_payload = {
                    "chat_id": chat_id,
                    "text": _telegram_plain_fallback(batch_content),
                    "disable_web_page_preview": True,
                }
'''
    fallback_replacement = '''                fallback_payload = {
                    "chat_id": chat_id,
                    "text": _telegram_plain_fallback(batch_content),
                    "disable_web_page_preview": True,
                }
                if not is_private_target:
                    fallback_payload["reply_markup"] = _build_public_telegram_reply_markup("main")
'''
    if fallback_marker in text:
        text = text.replace(fallback_marker, fallback_replacement, 1)
        changed = True

    if changed:
        SENDERS_PATH.write_text(text, encoding="utf-8")
        print("[TZ02] Patched Telegram final layout and two-level menu.")
    else:
        print("[TZ02] Telegram sender already patched.")


def patch_interactions() -> None:
    current = INTERACTIONS_PATH.read_text(encoding="utf-8") if INTERACTIONS_PATH.exists() else ""
    if "two-level-menu worker" in current and "tr_menu:sports" in current:
        print("[TZ02] Telegram interactions already patched.")
        return
    INTERACTIONS_PATH.write_text(INTERACTIONS_CONTENT, encoding="utf-8")
    print("[TZ02] Patched Telegram two-level interactions worker.")


def main() -> None:
    patch_senders()
    patch_interactions()


if __name__ == "__main__":
    main()
