# coding=utf-8
"""Telegram inline button and reply handler for TrendRadar.

Run this process with TELEGRAM_BOT_TOKEN. It handles:
- Like button: one Telegram user can like one bot post once.
- Comment button: shows an instruction popup.
- Replies to bot posts in groups: counted as comments and reflected in the button count.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

STATE_PATH = Path(".tg_interactions/state.json")
RUN_SECONDS = int(os.getenv("TG_INTERACTIONS_RUN_SECONDS", "18000"))
POLL_TIMEOUT = int(os.getenv("TG_INTERACTIONS_POLL_TIMEOUT", "20"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"posts": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"posts": {}}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _commit_state() -> None:
    if not os.getenv("GITHUB_ACTIONS"):
        return
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=False)
        subprocess.run(["git", "add", str(STATE_PATH)], check=False)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "chore: update telegram interaction state [skip ci]"], check=False)
            subprocess.run(["git", "pull", "--rebase", "--autostash"], check=False)
            subprocess.run(["git", "push"], check=False)
    except Exception as exc:
        print(f"[TG互动] state commit skipped: {exc}")


def _api(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = requests.post(f"{API_BASE}/{method}", json=payload, timeout=30)
        data = response.json()
        if not data.get("ok"):
            print(f"[TG互动] API {method} failed: {data}")
        return data
    except Exception as exc:
        print(f"[TG互动] API {method} exception: {exc}")
        return {"ok": False, "result": None}


def _post_key(chat_id: Any, message_id: Any) -> str:
    return _hash(f"{chat_id}:{message_id}")


def _post_state(state: Dict[str, Any], chat_id: Any, message_id: Any) -> Dict[str, Any]:
    posts = state.setdefault("posts", {})
    key = _post_key(chat_id, message_id)
    return posts.setdefault(key, {"likes": [], "comments": []})


def _keyboard(likes: int, comments: int) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": f"👍 点赞 {likes}", "callback_data": "tr_like"},
                {"text": f"💬 评论 {comments}", "callback_data": "tr_comment"},
            ],
            [{"text": "☰ 功能菜单", "callback_data": "tr_menu"}],
        ]
    }


def _refresh_buttons(chat_id: Any, message_id: Any, post: Dict[str, Any]) -> None:
    _api(
        "editMessageReplyMarkup",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": _keyboard(len(post.get("likes", [])), len(post.get("comments", []))),
        },
    )


def _answer_callback(callback_id: str, text: str, alert: bool = False) -> None:
    _api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text, "show_alert": alert})


def _handle_callback(update: Dict[str, Any], state: Dict[str, Any]) -> bool:
    cb = update.get("callback_query") or {}
    data = cb.get("data")
    if data not in {"tr_like", "tr_comment", "tr_menu"}:
        return False

    message = cb.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    user_id = (cb.get("from") or {}).get("id")
    callback_id = cb.get("id")

    if not chat_id or not message_id or not callback_id:
        return False

    post = _post_state(state, chat_id, message_id)
    user_hash = _hash(user_id)

    if data == "tr_like":
        likes = post.setdefault("likes", [])
        if user_hash in likes:
            _answer_callback(callback_id, f"你已经点过赞了。当前点赞 {len(likes)}")
            return False
        likes.append(user_hash)
        _refresh_buttons(chat_id, message_id, post)
        _answer_callback(callback_id, f"点赞成功。当前点赞 {len(likes)}")
        return True

    if data == "tr_comment":
        _answer_callback(callback_id, "请直接回复这条推文发表评论，系统会自动统计评论数。", True)
        return False

    _answer_callback(callback_id, "功能菜单已收到，后续会继续扩展。")
    return False


def _handle_reply_comment(update: Dict[str, Any], state: Dict[str, Any]) -> bool:
    message = update.get("message") or {}
    reply_to = message.get("reply_to_message") or {}
    if not reply_to:
        return False

    chat_id = (message.get("chat") or {}).get("id")
    source_message_id = reply_to.get("message_id")
    user_id = (message.get("from") or {}).get("id")
    text = (message.get("text") or message.get("caption") or "").strip()
    if not chat_id or not source_message_id or not user_id or not text:
        return False

    post = _post_state(state, chat_id, source_message_id)
    comments = post.setdefault("comments", [])
    comments.append({"user": _hash(user_id), "text": text[:300], "ts": int(time.time())})
    _refresh_buttons(chat_id, source_message_id, post)
    print(f"[TG互动] comment saved for post={_post_key(chat_id, source_message_id)} total={len(comments)}")
    return True


def main() -> None:
    if not BOT_TOKEN:
        print("[TG互动] TELEGRAM_BOT_TOKEN is empty, exit.")
        return

    print(f"[TG互动] polling started, run_seconds={RUN_SECONDS}")
    state = _load_state()
    offset: Optional[int] = None
    changed = False
    started = time.monotonic()

    while time.monotonic() - started < RUN_SECONDS:
        params = {"timeout": POLL_TIMEOUT, "allowed_updates": ["callback_query", "message"]}
        if offset is not None:
            params["offset"] = offset
        result = _api("getUpdates", params)
        updates = result.get("result") or []
        for update in updates:
            offset = int(update.get("update_id", 0)) + 1
            if _handle_callback(update, state):
                changed = True
            if _handle_reply_comment(update, state):
                changed = True
            if changed:
                _save_state(state)
                _commit_state()
                changed = False

    _save_state(state)
    _commit_state()
    print("[TG互动] polling finished")


if __name__ == "__main__":
    main()
