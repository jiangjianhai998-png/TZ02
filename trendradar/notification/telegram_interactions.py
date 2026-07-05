# coding=utf-8
"""Telegram native comments compatibility worker.

当前频道采用 Telegram 原生评论区。注意：Bot 自定义 inline keyboard 会覆盖/挤掉
Telegram 频道原生“留言/评论”入口，所以这里不再给频道帖子添加自定义点赞按钮。
如果旧消息上还有历史按钮，点击后会自动清除旧按钮，让原生评论入口恢复。
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

STATE_VERSION = 2
DEFAULT_STATE_PATH = "data/telegram_interactions_state.json"
DEFAULT_POLL_SECONDS = 21000
DEFAULT_POLL_TIMEOUT = 20


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "offset": 0, "legacy_buttons_cleared": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("version", STATE_VERSION)
    data.setdefault("offset", 0)
    data.setdefault("legacy_buttons_cleared", {})
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


def _clear_legacy_buttons(token: str, message: Dict[str, Any]) -> bool:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return False
    result = _api(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": []},
    })
    if result.get("ok"):
        print(f"[TG互动] 已清除旧自定义按钮 chat={chat_id} message={message_id}")
        return True
    print(f"[TG互动] 清除旧按钮失败 result={result}")
    return False


def _handle_callback(token: str, state: Dict[str, Any], callback: Dict[str, Any]) -> bool:
    callback_id = str(callback.get("id") or "")
    data = str(callback.get("data") or "")
    message = callback.get("message") or {}
    if not callback_id or not data.startswith("tr_"):
        return False

    chat_id, message_id = _message_ref(message)
    key = f"{chat_id}:{message_id}"
    changed = False
    if key not in state.setdefault("legacy_buttons_cleared", {}):
        changed = _clear_legacy_buttons(token, message)
        if changed:
            state["legacy_buttons_cleared"][key] = int(time.time())

    if data.startswith("tr_like:"):
        _answer(token, callback_id, "已切换为 Telegram 原生反应，请使用帖子下方系统反应/评论。")
    elif data.startswith("tr_comment:"):
        _answer(token, callback_id, "请使用帖子下方 Telegram 原生评论入口。")
    else:
        _answer(token, callback_id, "已切换为 Telegram 原生评论/反应模式。")
    return changed


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _prepare_bot(token)
    state = _load_state(state_path)
    changed = False
    started_at = time.time()
    print(f"[TG互动] native-comments worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")

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
    print("[TG互动] native-comments worker finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram native comments compatibility worker")
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
