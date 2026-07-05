# coding=utf-8
"""Telegram inline button interaction worker.

处理机器人推文按钮：
- 点赞：每个 Telegram 账号对同一条推文只能点一次，并更新点赞总数；
- 评论：不跳转源链接，在 Telegram 内提示用户直接回复推文；
- 菜单：在 Telegram 内弹出说明；
- 状态保存到 data/telegram_interactions_state.json。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_VERSION = 1
DEFAULT_STATE_PATH = "data/telegram_interactions_state.json"
DEFAULT_POLL_SECONDS = 21000
DEFAULT_POLL_TIMEOUT = 20
COMMENT_TTL_SECONDS = 30 * 60


def _now() -> int:
    return int(time.time())


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "offset": 0, "likes": {}, "comments": {}, "pending_comments": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    data.setdefault("version", STATE_VERSION)
    data.setdefault("offset", 0)
    data.setdefault("likes", {})
    data.setdefault("comments", {})
    data.setdefault("pending_comments", {})
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
    # getUpdates 和 webhook 不能同时使用；这里主动关闭 webhook，但不丢弃未处理点击。
    result = _api(token, "deleteWebhook", {"drop_pending_updates": False}, timeout=10)
    print(f"[TG互动] deleteWebhook ok={result.get('ok')}")
    info = _api(token, "getMe", {}, timeout=10)
    if info.get("ok"):
        username = (info.get("result") or {}).get("username", "")
        print(f"[TG互动] bot connected @{username}")


def _user_key(token: str, user_id: Any) -> str:
    raw = str(user_id or "")
    return hmac.new(token.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _safe_name(user: Dict[str, Any]) -> str:
    name = " ".join(str(user.get(k, "")).strip() for k in ("first_name", "last_name") if user.get(k))
    return name or str(user.get("username") or "用户")


def _post_buttons(post_id: str, like_count: int, comment_count: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": f"👍 点赞 {like_count}", "callback_data": f"tr_like:{post_id}"},
                {"text": f"💬 评论 {comment_count}", "callback_data": f"tr_comment:{post_id}"},
            ],
            [{"text": "☰ 功能菜单", "callback_data": f"tr_menu:{post_id}"}],
        ]
    }


def _counts(state: Dict[str, Any], post_id: str) -> tuple[int, int]:
    like_entry = state.setdefault("likes", {}).setdefault(post_id, {"users": []})
    comments = state.setdefault("comments", {}).setdefault(post_id, [])
    return len(like_entry.setdefault("users", [])), len(comments)


def _message_ref(message: Dict[str, Any]) -> tuple[Any, Any]:
    chat = message.get("chat") or {}
    return chat.get("id"), message.get("message_id")


def _edit_buttons(token: str, message: Dict[str, Any], post_id: str, state: Dict[str, Any]) -> None:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return
    like_count, comment_count = _counts(state, post_id)
    result = _api(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": _post_buttons(post_id, like_count, comment_count),
    })
    if not result.get("ok"):
        print(f"[TG互动] 更新按钮失败 post={post_id} result={result}")


def _answer(token: str, callback_id: str, text: str, show_alert: bool = False) -> None:
    _api(token, "answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text[:180],
        "show_alert": show_alert,
        "cache_time": 0,
    })


def _send_comment_prompt(token: str, message: Dict[str, Any]) -> None:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return
    _api(token, "sendMessage", {
        "chat_id": chat_id,
        "reply_to_message_id": message_id,
        "allow_sending_without_reply": True,
        "text": "💬 请直接回复这条推文写评论。评论会留在 Telegram 内，不会跳转到源链接。",
    })


def _handle_callback(token: str, state: Dict[str, Any], callback: Dict[str, Any]) -> bool:
    callback_id = str(callback.get("id") or "")
    data = str(callback.get("data") or "")
    user = callback.get("from") or {}
    message = callback.get("message") or {}
    if not callback_id or not data.startswith("tr_"):
        return False

    action, _, post_id = data.partition(":")
    post_id = post_id or "default"
    user_hash = _user_key(token, user.get("id"))

    if action == "tr_like":
        like_entry = state.setdefault("likes", {}).setdefault(post_id, {"users": []})
        users = like_entry.setdefault("users", [])
        if user_hash in users:
            like_count, _ = _counts(state, post_id)
            _answer(token, callback_id, f"你已经点赞过了。当前点赞 {like_count}")
            return False
        users.append(user_hash)
        like_entry["updated_at"] = _now()
        _edit_buttons(token, message, post_id, state)
        like_count, _ = _counts(state, post_id)
        _answer(token, callback_id, f"点赞成功，当前点赞 {like_count}")
        print(f"[TG互动] 点赞成功 post={post_id} likes={like_count}")
        return True

    if action == "tr_comment":
        chat_id, message_id = _message_ref(message)
        pending_key = f"{chat_id}:{user_hash}"
        state.setdefault("pending_comments", {})[pending_key] = {
            "post_id": post_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "expires_at": _now() + COMMENT_TTL_SECONDS,
        }
        _answer(token, callback_id, "请直接回复这条推文写评论，评论不会跳转到源链接。", show_alert=True)
        _send_comment_prompt(token, message)
        print(f"[TG互动] 评论入口 post={post_id}")
        return True

    if action == "tr_menu":
        _answer(token, callback_id, "功能菜单：点赞统计、Telegram 内评论、后续可扩展收藏/分享/客服入口。", show_alert=True)
        return False

    return False


def _handle_message(token: str, state: Dict[str, Any], message: Dict[str, Any]) -> bool:
    user = message.get("from") or {}
    chat = message.get("chat") or {}
    text = str(message.get("text") or message.get("caption") or "").strip()
    if not user.get("id") or not chat.get("id") or not text:
        return False

    user_hash = _user_key(token, user.get("id"))
    pending_key = f"{chat.get('id')}:{user_hash}"
    pending = state.setdefault("pending_comments", {})
    entry = pending.get(pending_key)
    if not entry:
        return False
    if int(entry.get("expires_at") or 0) < _now():
        pending.pop(pending_key, None)
        return True

    post_id = str(entry.get("post_id") or "default")
    state.setdefault("comments", {}).setdefault(post_id, []).append({
        "user": _safe_name(user)[:40],
        "text": text[:300],
        "created_at": _now(),
    })
    pending.pop(pending_key, None)

    _api(token, "sendMessage", {
        "chat_id": entry.get("chat_id"),
        "reply_to_message_id": entry.get("message_id"),
        "allow_sending_without_reply": True,
        "text": f"💬 {_safe_name(user)} 评论：\n{text[:500]}",
    })
    _api(token, "editMessageReplyMarkup", {
        "chat_id": entry.get("chat_id"),
        "message_id": entry.get("message_id"),
        "reply_markup": _post_buttons(post_id, *_counts(state, post_id)),
    })
    _, comment_count = _counts(state, post_id)
    print(f"[TG互动] 收到评论 post={post_id} comments={comment_count}")
    return True


def _cleanup_pending(state: Dict[str, Any]) -> bool:
    changed = False
    pending = state.setdefault("pending_comments", {})
    for key in list(pending.keys()):
        if int(pending[key].get("expires_at") or 0) < _now():
            pending.pop(key, None)
            changed = True
    return changed


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _prepare_bot(token)
    state = _load_state(state_path)
    changed = _cleanup_pending(state)
    started_at = time.time()
    print(f"[TG互动] worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")

    while time.time() - started_at < poll_seconds:
        result = _api(token, "getUpdates", {
            "offset": int(state.get("offset") or 0),
            "timeout": poll_timeout,
            "allowed_updates": ["callback_query", "message"],
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
            elif "message" in update:
                changed = _handle_message(token, state, update["message"]) or changed
            if changed:
                _save_state(state_path, state)

    if changed:
        _save_state(state_path, state)
    print("[TG互动] worker finished")


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram interaction worker")
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
