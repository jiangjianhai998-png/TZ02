# coding=utf-8
"""
Telegram 公开频道卡片包装层。

目标：不大改原 senders.py，只在公开群/频道发送阶段补充频道卡片样式。
当前能力：
- 为每条公开推送增加“要点评论”区块；
- 增加点赞、评论、功能菜单按钮；
- 私聊完整内部报告不处理，仍保持原样。
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict

from . import senders as _senders

_ORIGINAL_SEND_TO_TELEGRAM = _senders.send_to_telegram


def _plain_text(text: str) -> str:
    """提取纯文本，方便判断与生成短评论。"""
    if not text:
        return ""
    text = unescape(str(text))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_first_url(text: str) -> str:
    """从 HTML 链接或纯文本里提取第一个 URL。"""
    if not text:
        return ""
    html_match = re.search(r'<a\s+href=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
    if html_match:
        return html_match.group(1).strip()
    plain_match = re.search(r"https?://[^\s<>'\"]+", text)
    return plain_match.group(0).strip() if plain_match else ""


def _is_public_telegram_payload(payload: Dict[str, Any]) -> bool:
    """只处理群组/频道公开推送，私聊不加卡片按钮。"""
    chat_id = str(payload.get("chat_id", "")).strip()
    if not chat_id:
        return False
    return not _senders._is_telegram_private_target(chat_id)


def _build_inline_keyboard(content: str) -> Dict[str, list]:
    """生成点赞、评论、功能菜单按钮。"""
    link_url = _extract_first_url(content)
    return {
        "inline_keyboard": [
            [
                {"text": "👍 点赞", "callback_data": "like"},
                {"text": "💬 评论", "url": link_url} if link_url else {"text": "💬 评论", "callback_data": "comment"},
            ],
            [
                {"text": "☰ 功能菜单", "url": link_url} if link_url else {"text": "☰ 功能菜单", "callback_data": "menu"},
            ],
        ]
    }


def _extract_news_line(text: str) -> str:
    """从当前单条推送中提取新闻/视频标题。"""
    for line in _plain_text(text).splitlines():
        line = line.strip()
        if line.startswith("📰"):
            return line.lstrip("📰").strip()
    return ""


def _ensure_commentary_block(text: str) -> str:
    """补充要点评论文，保持短评风格。"""
    if not text or "🧠 <b>要点评论</b>" in text:
        return text

    news_line = _extract_news_line(text)
    if not news_line:
        return text

    commentary = [
        "",
        "🧠 <b>要点评论</b>",
        f"• 核心看点：{news_line[:80]}",
        "• 观察方向：热度变化、传播价值、行业影响。",
        "• 后续跟进：适合继续观察原文、视频或评论区反馈。",
    ]

    marker = "\n━━━━━━━━━━━━━━\n📰"
    if marker in text:
        return text.replace(marker, "\n━━━━━━━━━━━━━━" + "\n".join(commentary) + "\n━━━━━━━━━━━━━━\n📰", 1)
    return text + "\n" + "\n".join(commentary)


def _patch_public_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把公开 Telegram payload 包装成频道卡片。"""
    if not _is_public_telegram_payload(payload):
        return payload

    patched = dict(payload)
    content = str(patched.get("text") or patched.get("caption") or "")
    content = _ensure_commentary_block(content)

    if "text" in patched:
        patched["text"] = content
    elif "caption" in patched:
        patched["caption"] = content

    patched["reply_markup"] = _build_inline_keyboard(content)
    return patched


def send_to_telegram(*args: Any, **kwargs: Any) -> bool:
    """包装原 send_to_telegram：公开群/频道增加卡片按钮和要点评论。"""
    real_post = _senders.requests.post

    def patched_post(url, *post_args, **post_kwargs):
        payload = post_kwargs.get("json")
        if isinstance(payload, dict) and "/sendMessage" in str(url):
            post_kwargs["json"] = _patch_public_payload(payload)
        return real_post(url, *post_args, **post_kwargs)

    _senders.requests.post = patched_post
    try:
        return _ORIGINAL_SEND_TO_TELEGRAM(*args, **kwargs)
    finally:
        _senders.requests.post = real_post
