# coding=utf-8
"""Apply TZ02 Telegram public layout and interaction button patch.

This script is intentionally idempotent. GitHub Actions runs it before TrendRadar
or the Telegram interaction worker starts, so the upstream source can stay small
while TZ02 keeps its custom public-channel layout.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENDERS_PATH = ROOT / "trendradar" / "notification" / "senders.py"
INTERACTIONS_PATH = ROOT / "trendradar" / "notification" / "telegram_interactions.py"

SENDERS_HELPER = r'''

def _get_public_telegram_menu_items() -> list:
    """Return public channel menu buttons.

    Optional custom format:
      TELEGRAM_MENU_ITEMS="🏀 NBA|https://t.me/xxx;🎰 百家樂|https://t.me/yyy"

    Built-in secrets/envs:
      TELEGRAM_MENU_NBA_URL
      TELEGRAM_MENU_BACCARAT_URL
      TELEGRAM_MENU_POKER_URL
      TELEGRAM_MENU_NEWS_URL
      TELEGRAM_MENU_ANTI_GAMBLING_URL
    """
    items = []
    custom = os.environ.get("TELEGRAM_MENU_ITEMS", "").strip()
    if custom:
        for index, part in enumerate(custom.split(";"), 1):
            part = part.strip()
            if not part or "|" not in part:
                continue
            text, url = part.split("|", 1)
            text = text.strip()
            url = url.strip()
            if text:
                items.append((text, url, f"custom_{index}"))

    defaults = [
        ("🏀 NBA", "TELEGRAM_MENU_NBA_URL", "nba"),
        ("🎰 百家樂", "TELEGRAM_MENU_BACCARAT_URL", "baccarat"),
        ("🃏 德州扑克", "TELEGRAM_MENU_POKER_URL", "poker"),
        ("📰 博彩热点", "TELEGRAM_MENU_NEWS_URL", "news"),
        ("🚫 反赌内容", "TELEGRAM_MENU_ANTI_GAMBLING_URL", "anti_gambling"),
    ]
    for text, env_name, key in defaults:
        url = os.environ.get(env_name, "").strip()
        items.append((text, url, key))
    return items


def _build_public_telegram_reply_markup(like_count: Optional[int] = None) -> Dict[str, Any]:
    """Build the public inline menu: like/comment first, then channel buttons."""
    like_label = "👍 点赞" if like_count is None or like_count <= 0 else f"👍 {like_count}"
    keyboard = [
        [
            {"text": like_label, "callback_data": "tr_like"},
            {"text": "💬 评论", "callback_data": "tr_comment"},
        ]
    ]

    menu_buttons = []
    for text, url, key in _get_public_telegram_menu_items():
        if url.startswith(("http://", "https://", "tg://")):
            menu_buttons.append({"text": text, "url": url})
        else:
            menu_buttons.append({"text": text, "callback_data": f"tr_menu:{key}"})

    for index in range(0, len(menu_buttons), 2):
        keyboard.append(menu_buttons[index:index + 2])

    return {"inline_keyboard": keyboard}
'''

INTERACTIONS_CONTENT = r'''# coding=utf-8
"""Telegram public post interactions for TZ02.

Public posts use a custom inline keyboard:
- 👍 点赞：stored in data/telegram_interactions_state.json and updates the button count.
- 💬 评论：kept as a local callback; it does not jump to the source link.
- Channel menu buttons：jump to configured Telegram channels when URL secrets are set.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_VERSION = 3
DEFAULT_STATE_PATH = "data/telegram_interactions_state.json"
DEFAULT_POLL_SECONDS = 21000
DEFAULT_POLL_TIMEOUT = 20


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "offset": 0, "likes": {}, "liked_by": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data["version"] = STATE_VERSION
    data.setdefault("offset", 0)
    data.setdefault("likes", {})
    data.setdefault("liked_by", {})
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


def _get_public_telegram_menu_items() -> list:
    items = []
    custom = os.environ.get("TELEGRAM_MENU_ITEMS", "").strip()
    if custom:
        for index, part in enumerate(custom.split(";"), 1):
            part = part.strip()
            if not part or "|" not in part:
                continue
            text, url = part.split("|", 1)
            text = text.strip()
            url = url.strip()
            if text:
                items.append((text, url, f"custom_{index}"))

    defaults = [
        ("🏀 NBA", "TELEGRAM_MENU_NBA_URL", "nba"),
        ("🎰 百家樂", "TELEGRAM_MENU_BACCARAT_URL", "baccarat"),
        ("🃏 德州扑克", "TELEGRAM_MENU_POKER_URL", "poker"),
        ("📰 博彩热点", "TELEGRAM_MENU_NEWS_URL", "news"),
        ("🚫 反赌内容", "TELEGRAM_MENU_ANTI_GAMBLING_URL", "anti_gambling"),
    ]
    for text, env_name, key in defaults:
        url = os.environ.get(env_name, "").strip()
        items.append((text, url, key))
    return items


def _build_reply_markup(like_count: int = 0) -> Dict[str, Any]:
    like_label = "👍 点赞" if like_count <= 0 else f"👍 {like_count}"
    keyboard = [
        [
            {"text": like_label, "callback_data": "tr_like"},
            {"text": "💬 评论", "callback_data": "tr_comment"},
        ]
    ]
    menu_buttons = []
    for text, url, key in _get_public_telegram_menu_items():
        if url.startswith(("http://", "https://", "tg://")):
            menu_buttons.append({"text": text, "url": url})
        else:
            menu_buttons.append({"text": text, "callback_data": f"tr_menu:{key}"})
    for index in range(0, len(menu_buttons), 2):
        keyboard.append(menu_buttons[index:index + 2])
    return {"inline_keyboard": keyboard}


def _edit_markup(token: str, message: Dict[str, Any], like_count: int) -> bool:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return False
    result = _api(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": _build_reply_markup(like_count),
    })
    if result.get("ok"):
        print(f"[TG互动] 已更新按钮 chat={chat_id} message={message_id} likes={like_count}")
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
        _edit_markup(token, message, like_count)
        _answer(token, callback_id, f"{action_text}，当前 {like_count} 个赞")
        return True

    if data.startswith("tr_comment"):
        _answer(token, callback_id, "评论按钮已保留；当前不会跳转源链接，可在频道/群组消息下方留言互动。")
        return False

    if data.startswith("tr_menu:"):
        menu_key = data.split(":", 1)[-1]
        _answer(token, callback_id, f"{menu_key} 频道入口还没配置链接，请先在 GitHub Secrets 设置对应 TELEGRAM_MENU_*_URL。")
        return False

    _answer(token, callback_id, "按钮已收到。")
    return False


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _prepare_bot(token)
    state = _load_state(state_path)
    changed = False
    started_at = time.time()
    print(f"[TG互动] custom-buttons worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")

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
    print("[TG互动] custom-buttons worker finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram custom buttons worker")
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

    if "def _build_public_telegram_reply_markup" not in text:
        marker = "\ndef _extract_ai_stats(ai_analysis)"
        if marker not in text:
            raise RuntimeError("Cannot locate _extract_ai_stats marker in senders.py")
        text = text.replace(marker, SENDERS_HELPER + marker, 1)
        changed = True

    old_payload = '''        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
'''
    new_payload = '''        payload = {
            "chat_id": chat_id,
            "text": batch_content,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if not is_private_target:
            payload["reply_markup"] = _build_public_telegram_reply_markup()
'''
    if old_payload in text and 'payload["reply_markup"] = _build_public_telegram_reply_markup()' not in text:
        text = text.replace(old_payload, new_payload, 1)
        changed = True

    old_fallback = '''                fallback_payload = {
                    "chat_id": chat_id,
                    "text": _telegram_plain_fallback(batch_content),
                    "disable_web_page_preview": True,
                }
'''
    new_fallback = '''                fallback_payload = {
                    "chat_id": chat_id,
                    "text": _telegram_plain_fallback(batch_content),
                    "disable_web_page_preview": True,
                }
                if not is_private_target:
                    fallback_payload["reply_markup"] = _build_public_telegram_reply_markup()
'''
    if old_fallback in text and 'fallback_payload["reply_markup"] = _build_public_telegram_reply_markup()' not in text:
        text = text.replace(old_fallback, new_fallback, 1)
        changed = True

    if changed:
        SENDERS_PATH.write_text(text, encoding="utf-8")
        print("[TZ02] Patched Telegram public sender layout/menu buttons.")
    else:
        print("[TZ02] Telegram sender layout already patched.")


def patch_interactions() -> None:
    current = INTERACTIONS_PATH.read_text(encoding="utf-8") if INTERACTIONS_PATH.exists() else ""
    if "custom-buttons worker" in current and "def _build_reply_markup" in current:
        print("[TZ02] Telegram interactions already patched.")
        return
    INTERACTIONS_PATH.write_text(INTERACTIONS_CONTENT, encoding="utf-8")
    print("[TZ02] Patched Telegram custom interactions worker.")


def main() -> None:
    patch_senders()
    patch_interactions()


if __name__ == "__main__":
    main()
