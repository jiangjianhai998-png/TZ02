# coding=utf-8
"""
Telegram 公开频道卡片包装层。

目标：不大改原 senders.py，只在公开群/频道发送阶段补充频道卡片样式。
当前能力：
- 公开群/频道按“短视频/图片 → 要点评论文 → 按钮”的频道卡片结构展示；
- 直链图片优先 sendPhoto，直链视频优先 sendVideo；
- 非直链媒体保留文字卡片，并提供“短视频/图片”入口；
- 增加点赞、评论、功能菜单按钮；
- GitHub Actions 日志输出 Telegram 推送预览，方便远程验证；
- 私聊完整内部报告不处理，仍保持原样。
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, Optional, Tuple

from . import senders as _senders

_ORIGINAL_SEND_TO_TELEGRAM = _senders.send_to_telegram

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v", ".webm")
_MEDIA_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "douyin.com",
    "x.com",
    "twitter.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
)


def _plain_text(text: str) -> str:
    """提取纯文本，方便判断与生成短评论。"""
    if not text:
        return ""
    text = unescape(str(text))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_urls(text: str) -> list:
    """从 HTML 链接或纯文本里提取 URL 列表。"""
    if not text:
        return []

    urls = []
    urls.extend(
        match.strip()
        for match in re.findall(r'<a\s+href=["\']([^"\']+)["\']', text, flags=re.IGNORECASE)
        if match.strip()
    )
    urls.extend(
        match.strip().rstrip("，。；;、)")
        for match in re.findall(r"https?://[^\s<>'\"]+", text)
        if match.strip()
    )

    deduped = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def _extract_first_url(text: str) -> str:
    """从 HTML 链接或纯文本里提取第一个 URL。"""
    urls = _extract_urls(text)
    return urls[0] if urls else ""


def _is_direct_image_url(url: str) -> bool:
    clean = url.split("?", 1)[0].split("#", 1)[0].lower()
    return clean.endswith(_IMAGE_EXTENSIONS)


def _is_direct_video_url(url: str) -> bool:
    clean = url.split("?", 1)[0].split("#", 1)[0].lower()
    return clean.endswith(_VIDEO_EXTENSIONS)


def _looks_like_media_page(url: str) -> bool:
    lowered = url.lower()
    return any(domain in lowered for domain in _MEDIA_DOMAINS)


def _pick_media_url(content: str) -> Tuple[str, str]:
    """
    选择媒体 URL。

    Returns:
        (media_type, url)
        media_type: photo / video / link / ""
    """
    urls = _extract_urls(content)
    for url in urls:
        if _is_direct_video_url(url):
            return "video", url
    for url in urls:
        if _is_direct_image_url(url):
            return "photo", url
    for url in urls:
        if _looks_like_media_page(url):
            return "link", url
    return ("link", urls[0]) if urls else ("", "")


def _is_public_telegram_payload(payload: Dict[str, Any]) -> bool:
    """只处理群组/频道公开推送，私聊不加卡片按钮。"""
    chat_id = str(payload.get("chat_id", "")).strip()
    if not chat_id:
        return False
    return not _senders._is_telegram_private_target(chat_id)


def _mask_chat_id(chat_id: Any) -> str:
    """日志里隐藏完整 chat_id，只保留可识别尾号。"""
    raw = str(chat_id or "").strip()
    if not raw:
        return "empty"
    if len(raw) <= 4:
        return "***"
    prefix = "-" if raw.startswith("-") else ""
    return f"{prefix}***{raw[-4:]}"


def _url_host(url: str) -> str:
    """日志只展示 URL 域名，不打印完整链接。"""
    match = re.match(r"https?://([^/]+)", str(url or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _preview_text(text: str, max_chars: int = 500) -> str:
    """生成安全预览：去 HTML、隐藏完整 URL、限制长度。"""
    preview = _plain_text(text)
    preview = re.sub(r"https?://[^\s<>'\"]+", "[URL]", preview)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + "..."
    return preview


def _button_preview(reply_markup: Any) -> str:
    """提取按钮文字，方便日志验证按钮是否存在。"""
    if not isinstance(reply_markup, dict):
        return "none"
    rows = reply_markup.get("inline_keyboard") or []
    rendered_rows = []
    for row in rows:
        labels = [str(button.get("text", "")).strip() for button in row if isinstance(button, dict)]
        labels = [label for label in labels if label]
        if labels:
            rendered_rows.append(" | ".join(labels))
    return " / ".join(rendered_rows) if rendered_rows else "none"


def _log_public_payload_preview(method: str, payload: Dict[str, Any], *, stage: str) -> None:
    """在 GitHub Actions 日志输出 Telegram 推送预览，不打印 token 和完整 chat_id。"""
    if not _is_public_telegram_payload(payload):
        return

    text = str(payload.get("caption") or payload.get("text") or "")
    media_url = str(payload.get("photo") or payload.get("video") or "")
    media_host = _url_host(media_url)
    media_type = "photo" if payload.get("photo") else "video" if payload.get("video") else "text"

    print("\n[TG预览]━━━━━━━━━━━━━━━━━━━━")
    print(f"[TG预览] stage={stage} method={method} chat={_mask_chat_id(payload.get('chat_id'))} media={media_type}")
    if media_host:
        print(f"[TG预览] media_host={media_host}")
    print(f"[TG预览] buttons={_button_preview(payload.get('reply_markup'))}")
    print("[TG预览] content_start")
    print(_preview_text(text))
    print("[TG预览] content_end")
    print("[TG预览]━━━━━━━━━━━━━━━━━━━━\n")


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
    plain_lines = [line.strip() for line in _plain_text(text).splitlines() if line.strip()]
    for line in plain_lines:
        if line.startswith("📰"):
            return line.lstrip("📰").strip()
    for line in plain_lines:
        if line and not line.startswith(("🔥", "📍", "🧭", "⏱", "🗞️", "━", "📦")):
            return line[:120]
    return ""


def _extract_context_line(text: str) -> str:
    """提取栏目/来源信息。"""
    for line in _plain_text(text).splitlines():
        line = line.strip()
        if line.startswith("📍"):
            return line.lstrip("📍").strip(" ：:")
    return ""


def _extract_meta_lines(text: str) -> list:
    """提取重点话题和时间等辅助信息。"""
    meta = []
    for line in _plain_text(text).splitlines():
        line = line.strip()
        if line.startswith(("🧭", "⏱")):
            meta.append(line)
    return meta[:2]


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """按 UTF-8 字节安全截断。"""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    raw = text.encode("utf-8")[:max_bytes]
    while raw:
        try:
            result = raw.decode("utf-8")
            break
        except UnicodeDecodeError:
            raw = raw[:-1]
    else:
        return ""
    last_newline = result.rfind("\n")
    if last_newline > 200:
        result = result[:last_newline]
    return result.rstrip() + "\n…"


def _make_commentary_lines(news_line: str) -> list:
    """生成短评式要点评论。"""
    core = news_line[:80] if news_line else "本条内容具备继续跟进价值"
    return [
        "🧠 <b>要点评论</b>",
        f"• 核心看点：{core}",
        "• 传播价值：适合做热点跟进、短视频剪辑和频道讨论。",
        "• 行业观察：重点关注热度变化、评论反馈和后续事件发展。",
    ]


def _compose_public_card_text(original_text: str, *, include_media_block: bool) -> str:
    """
    重新组织公开推送展示顺序：
    短视频/图片 → 要点评论文 → 正文。
    """
    media_type, media_url = _pick_media_url(original_text)
    news_line = _extract_news_line(original_text)
    context_line = _extract_context_line(original_text)
    meta_lines = _extract_meta_lines(original_text)

    parts = []

    if include_media_block:
        parts.append("🎬 <b>短视频/图片</b>")
        if media_url:
            label = "点击查看原视频/图片" if media_type in ("video", "photo", "link") else "点击查看素材"
            parts.append(f'<a href="{media_url}">{label}</a>')
        else:
            parts.append("暂无直接媒体链接，优先展示文字快报。")
        parts.append("━━━━━━━━━━━━━━")

    parts.append("🔥 <b>TrendRadar 热点快报</b>")
    if context_line:
        parts.append(f"📍 <b>{context_line}</b>")
    parts.extend(meta_lines)
    parts.append("━━━━━━━━━━━━━━")
    parts.extend(_make_commentary_lines(news_line))
    parts.append("━━━━━━━━━━━━━━")
    if news_line:
        parts.append(f"📰 {news_line}")
    else:
        parts.append(original_text.strip())

    return "\n".join(part for part in parts if part).strip()


def _patch_public_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把公开 Telegram payload 包装成频道卡片文字版。"""
    if not _is_public_telegram_payload(payload):
        return payload

    patched = dict(payload)
    content = str(patched.get("text") or patched.get("caption") or "")
    content = _compose_public_card_text(content, include_media_block=True)

    if "text" in patched:
        patched["text"] = _truncate_utf8(content, 3900)
    elif "caption" in patched:
        patched["caption"] = _truncate_utf8(content, 950)

    patched["reply_markup"] = _build_inline_keyboard(content)
    return patched


def _build_media_payload(payload: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """如果有直链图片/视频，把 sendMessage 转成 sendPhoto/sendVideo。"""
    if not _is_public_telegram_payload(payload):
        return None

    original_content = str(payload.get("text") or payload.get("caption") or "")
    media_type, media_url = _pick_media_url(original_content)
    if media_type not in ("photo", "video") or not media_url:
        return None

    caption = _compose_public_card_text(original_content, include_media_block=False)
    media_payload: Dict[str, Any] = {
        "chat_id": payload.get("chat_id"),
        "caption": _truncate_utf8(caption, 950),
        "parse_mode": payload.get("parse_mode", "HTML"),
        "reply_markup": _build_inline_keyboard(original_content),
    }
    if media_type == "photo":
        media_payload["photo"] = media_url
        return "sendPhoto", media_payload
    media_payload["video"] = media_url
    return "sendVideo", media_payload


def send_to_telegram(*args: Any, **kwargs: Any) -> bool:
    """
    包装原 send_to_telegram：
    - 公开群/频道：有直链媒体时优先发图片/视频，没有直链时发文字卡片；
    - 私聊：保持原始完整内部报告。
    """
    real_post = _senders.requests.post

    def patched_post(url, *post_args, **post_kwargs):
        payload = post_kwargs.get("json")
        if isinstance(payload, dict) and "/sendMessage" in str(url):
            media_result = _build_media_payload(payload)
            if media_result:
                method, media_payload = media_result
                media_url = str(url).replace("/sendMessage", f"/{method}")
                media_kwargs = dict(post_kwargs)
                media_kwargs["json"] = media_payload
                _log_public_payload_preview(method, media_payload, stage="media")
                response = real_post(media_url, *post_args, **media_kwargs)
                try:
                    result = response.json()
                except ValueError:
                    result = {"ok": False}
                if response.status_code == 200 and result.get("ok"):
                    return response
                print(f"[TG预览] 媒体发送失败，自动退回文字卡片。status={response.status_code}")

            post_kwargs["json"] = _patch_public_payload(payload)
            _log_public_payload_preview("sendMessage", post_kwargs["json"], stage="text")
        return real_post(url, *post_args, **post_kwargs)

    _senders.requests.post = patched_post
    try:
        return _ORIGINAL_SEND_TO_TELEGRAM(*args, **kwargs)
    finally:
        _senders.requests.post = real_post
