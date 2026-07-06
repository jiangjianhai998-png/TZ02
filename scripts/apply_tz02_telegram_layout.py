# coding=utf-8
"""Apply TZ02 Telegram final one-page UI.

最终版面：
- 正文只保留：AI原创短评
- 频道按钮直接全部展示：NBA/足球/直播/集锦/百家乐/德州扑克/龙虎斗/电子游戏
- 点赞/评论放在最底部
- 不再使用二级菜单，不再需要返回主菜单
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENDERS_PATH = ROOT / "trendradar" / "notification" / "senders.py"
INTERACTIONS_PATH = ROOT / "trendradar" / "notification" / "telegram_interactions.py"

SENDERS_HELPER = r'''

def _tz02_button_url(key: str) -> str:
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


def _tz02_channel_button(text: str, key: str) -> Dict[str, str]:
    url = _tz02_button_url(key)
    if url.startswith(("http://", "https://", "tg://")):
        return {"text": text, "url": url}
    return {"text": text, "callback_data": f"tr_link:{key}"}


def _build_public_telegram_reply_markup(like_count: Optional[int] = None) -> Dict[str, Any]:
    """Final TZ02 one-page keyboard. Like/comment are always at the bottom."""
    like_label = "👍 点赞" if like_count is None or like_count <= 0 else f"👍 {like_count}"
    return {
        "inline_keyboard": [
            [_tz02_channel_button("NBA", "nba"), _tz02_channel_button("足球", "football")],
            [_tz02_channel_button("直播", "live"), _tz02_channel_button("集锦", "highlights")],
            [_tz02_channel_button("百家乐", "baccarat"), _tz02_channel_button("德州扑克", "poker")],
            [_tz02_channel_button("龙虎斗", "dragon_tiger"), _tz02_channel_button("电子游戏", "egame")],
            [
                {"text": like_label, "callback_data": "tr_like"},
                {"text": "💬 评论", "callback_data": "tr_comment"},
            ],
        ]
    }


def _tz02_strip_public_old_template(text: str) -> str:
    if not text:
        return ""
    plain = _telegram_plain_fallback(str(text))
    remove_contains = (
        "TrendRadar 原创编辑快报",
        "TrendRadar 热点快报",
        "TrendRadar",
        "要点评论",
        "核心看点",
        "传播价值",
        "行业观察",
        "编辑短文",
        "今日头条",
        "当前先编辑为自有短文",
        "不把评论按钮跳转到源链接",
        "这条内容不是简单转发源链接",
        "我们会把信息提取、压缩、改写成自己的视频文章结构",
        "标题、导语、看点、评论点和互动问题",
        "功能菜单",
    )
    cleaned = []
    for raw in plain.splitlines():
        line = raw.strip()
        if not line or line.startswith("━"):
            continue
        if any(token in line for token in remove_contains):
            continue
        line = re.sub(r"^📰\s*", "", line).strip()
        line = re.sub(r"^[-•]\s*", "", line).strip()
        if line:
            cleaned.append(line)

    result = []
    seen = set()
    for line in cleaned:
        key = line[:100]
        if key in seen:
            continue
        seen.add(key)
        result.append(line)
    return "\n".join(result).strip()


def _tz02_extract_short_comment(text: str) -> str:
    body = _tz02_strip_public_old_template(text)
    if not body:
        return "这条热点内容已完成二次整理，适合继续剪辑成短视频，并引导用户进入相关频道。"
    lines = [line for line in body.splitlines() if line.strip()]
    picked = " ".join(lines[:2]).strip()
    picked = re.sub(r"\s+", " ", picked)
    if len(picked) > 90:
        picked = picked[:87].rstrip() + "..."
    return picked or "这条热点内容已完成二次整理，适合继续剪辑成短视频，并引导用户进入相关频道。"


def _format_tz02_public_post(text: str, max_bytes: int = 3900) -> str:
    """Final public message body. Video/image preview is shown by Telegram itself."""
    comment = _tz02_extract_short_comment(text)
    result = "\n".join([
        "AI原创短评",
        "",
        comment,
        "",
        "━━━━━━━━━━━━━━",
    ]).strip()
    if len(result.encode("utf-8")) > max_bytes:
        result = "AI原创短评\n\n" + comment[:160].rstrip()
    return result
'''

INTERACTIONS_CONTENT = r'''# coding=utf-8
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
            [
                {"text": like_label, "callback_data": "tr_like"},
                {"text": "💬 评论", "callback_data": "tr_comment"},
            ],
        ]
    }


def _edit_markup(token: str, message: Dict[str, Any], like_count: int) -> bool:
    chat_id, message_id = _message_ref(message)
    if not chat_id or not message_id:
        return False
    result = _api(token, "editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": _build_reply_markup(like_count=like_count),
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
        _answer(token, callback_id, "评论入口已保留。可以在消息下方留言互动，不会跳转源链接。")
        return False

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
    print(f"[TG互动] final-menu worker started, poll_seconds={poll_seconds}, timeout={poll_timeout}, offset={state.get('offset')}")

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
'''


def patch_senders() -> None:
    text = SENDERS_PATH.read_text(encoding="utf-8")
    changed = False

    end = text.find("\ndef _extract_ai_stats(ai_analysis)")
    if end == -1:
        raise RuntimeError("Cannot locate _extract_ai_stats marker in senders.py")

    starts = [
        text.find("\ndef _get_public_telegram_menu_items()"),
        text.find("\ndef _tz02_button_url(key: str)"),
    ]
    starts = [s for s in starts if s != -1 and s < end]
    if starts:
        start = min(starts)
        text = text[:start] + SENDERS_HELPER + text[end:]
        changed = True
    elif "def _build_public_telegram_reply_markup" not in text:
        text = text[:end] + SENDERS_HELPER + text[end:]
        changed = True

    # Remove old public beautifier block usage so final text is always TZ02 V4.
    old_block = '''    # 群组/频道公开版做美观优化，并按“每条新闻/推文/视频一条消息”拆开发送；
    # 私聊保留完整内部报告原貌，方便排错。
    if not is_private_target:
        total_batches = len(batches)
        single_post_batches = []
        for index, batch_content in enumerate(batches, 1):
            single_post_batches.extend(
                _beautify_public_telegram_batches(
                    batch_content,
                    batch_index=index,
                    batch_total=total_batches,
                    max_bytes=batch_size,
                )
            )
        batches = single_post_batches or [
            _beautify_public_telegram_batch(
                batch_content,
                batch_index=index,
                batch_total=total_batches,
                max_bytes=batch_size,
            )
            for index, batch_content in enumerate(batches, 1)
        ]
'''
    if old_block in text:
        text = text.replace(old_block, '''    # TZ02 V4: 公开群/频道不再使用旧 TrendRadar 版面；发送前统一压成最终短评模板。
''', 1)
        changed = True

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
            payload["reply_markup"] = _build_public_telegram_reply_markup()
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
                    fallback_payload["reply_markup"] = _build_public_telegram_reply_markup()
'''
    if fallback_marker in text:
        text = text.replace(fallback_marker, fallback_replacement, 1)
        changed = True

    if changed:
        SENDERS_PATH.write_text(text, encoding="utf-8")
        print("[TZ02] Patched Telegram final one-page layout.")
    else:
        print("[TZ02] Telegram sender already patched.")


def patch_interactions() -> None:
    current = INTERACTIONS_PATH.read_text(encoding="utf-8") if INTERACTIONS_PATH.exists() else ""
    if "final-menu worker" in current and "百家乐" in current and "德州扑克" in current:
        print("[TZ02] Telegram interactions already patched.")
        return
    INTERACTIONS_PATH.write_text(INTERACTIONS_CONTENT, encoding="utf-8")
    print("[TZ02] Patched Telegram final one-page interactions worker.")


def main() -> None:
    patch_senders()
    patch_interactions()


if __name__ == "__main__":
    main()
