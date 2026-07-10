# coding=utf-8
"""Telegram interactions for TZ02 final one-page menu."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_VERSION = 5
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
    except Exception as exc:
        print(f"[TG互动] API Error method={method}: {exc}")
        return {"ok": False, "description": str(exc)}


def _message_ref(message: Dict[str, Any]) -> tuple[Any, Any]:
    chat = message.get("chat") or {}
    return chat.get("id"), message.get("message_id")


def _answer(token: str, callback_id: str, text: str = "") -> None:
    payload: Dict[str, Any] = {"callback_query_id": callback_id, "show_alert": False, "cache_time": 0}
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


def _channel_button(text: str, key: str) -> Dict[str, str]:
    url = _button_url(key)
    if url.startswith(("http://", "https://", "tg://")):
        return {"text": text, "url": url}
    return {"text": text, "callback_data": f"tr_link:{key}"}


def _build_reply_markup(like_count: int = 0) -> Dict[str, Any]:
    like_label = "👍 点赞" if like_count <= 0 else f"👍 {like_count}"
    return {
        "inline_keyboard": [
            [_channel_button("NBA", "nba"), _channel_button("足球", "football")],
            [_channel_button("直播", "live"), _channel_button("集锦", "highlights")],
            [_channel_button("百家乐", "baccarat"), _channel_button("德州扑克", "poker")],
            [_channel_button("龙虎斗", "dragon_tiger"), _channel_button("电子游戏", "egame")],
            [{"text": like_label, "callback_data": "tr_like"}, {"text": "💬 评论", "callback_data": "tr_comment"}],
        ]
    }


def _edit_markup(token: str, message: Dict[str, Any], like_count: int) -> bool:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return False
    result = _api(token, "editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id, "reply_markup": _build_reply_markup(like_count)})
    return bool(result.get("ok"))


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
        liked = state.setdefault("liked_by", {}).setdefault(key, [])
        if user_id and user_id in liked:
            liked.remove(user_id)
            action = "已取消点赞"
        else:
            if user_id:
                liked.append(user_id)
            action = "已点赞"
        count = len(liked)
        state.setdefault("likes", {})[key] = count
        _edit_markup(token, message, count)
        _answer(token, callback_id, f"{action}，当前 {count} 个赞")
        return True
    if data.startswith("tr_comment"):
        _answer(token, callback_id, "评论入口已保留。可以在消息下方留言互动，不会跳转源链接。")
        return False
    if data.startswith("tr_link:"):
        link_key = data.split(":", 1)[-1]
        _answer(token, callback_id, f"{link_key} 频道链接还没配置，请先在 GitHub Secrets 设置对应 TELEGRAM_MENU_*_URL。")
        return False
    _answer(token, callback_id, "按钮已收到。")
    return False


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _api(token, "deleteWebhook", {"drop_pending_updates": False}, timeout=10)
    state = _load_state(state_path)
    changed = False
    started_at = time.time()
    print(f"[TG互动] final-menu worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")
    while time.time() - started_at < poll_seconds:
        result = _api(token, "getUpdates", {"offset": int(state.get("offset") or 0), "timeout": poll_timeout, "allowed_updates": ["callback_query"]}, timeout=poll_timeout + 10)
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
    print("[TG互动] final-menu worker finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram TZ02 final menu worker")
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
