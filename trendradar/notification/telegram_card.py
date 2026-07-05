# coding=utf-8
from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, Optional, Tuple

from . import senders as _senders

_ORIGINAL_SEND_TO_TELEGRAM = _senders.send_to_telegram
_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.m4v', '.webm')


def _plain_text(text: str) -> str:
    if not text:
        return ''
    text = unescape(str(text))
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _extract_urls(text: str) -> list:
    urls = []
    urls.extend(re.findall(r'<a\s+href=["\']([^"\']+)["\']', text or '', flags=re.IGNORECASE))
    urls.extend(re.findall(r'https?://[^\s<>\'\"]+', text or ''))
    result = []
    seen = set()
    for url in urls:
        url = str(url).strip().rstrip('，。；;、)')
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def _is_direct_image_url(url: str) -> bool:
    return url.split('?', 1)[0].split('#', 1)[0].lower().endswith(_IMAGE_EXTENSIONS)


def _is_direct_video_url(url: str) -> bool:
    return url.split('?', 1)[0].split('#', 1)[0].lower().endswith(_VIDEO_EXTENSIONS)


def _pick_media_url(content: str) -> Tuple[str, str]:
    urls = _extract_urls(content)
    for url in urls:
        if _is_direct_video_url(url):
            return 'video', url
    for url in urls:
        if _is_direct_image_url(url):
            return 'photo', url
    return ('', '')


def _is_public_telegram_payload(payload: Dict[str, Any]) -> bool:
    chat_id = str(payload.get('chat_id', '')).strip()
    return bool(chat_id) and not _senders._is_telegram_private_target(chat_id)


def _mask_chat_id(chat_id: Any) -> str:
    raw = str(chat_id or '').strip()
    if len(raw) <= 4:
        return '***'
    prefix = '-' if raw.startswith('-') else ''
    return f'{prefix}***{raw[-4:]}'


def _preview_text(text: str, max_chars: int = 500) -> str:
    preview = _plain_text(text)
    preview = re.sub(r'https?://[^\s<>\'\"]+', '[URL]', preview)
    return preview[:max_chars].rstrip() + ('...' if len(preview) > max_chars else '')


def _button_preview(reply_markup: Any) -> str:
    if not isinstance(reply_markup, dict):
        return 'none'
    rows = reply_markup.get('inline_keyboard') or []
    return ' / '.join(' | '.join(str(b.get('text', '')).strip() for b in row if isinstance(b, dict)) for row in rows)


def _log_public_payload_preview(method: str, payload: Dict[str, Any], stage: str) -> None:
    if not _is_public_telegram_payload(payload):
        return
    text = str(payload.get('caption') or payload.get('text') or '')
    media_type = 'photo' if payload.get('photo') else 'video' if payload.get('video') else 'text'
    print('\n[TG预览]━━━━━━━━━━━━━━━━━━━━')
    print(f'[TG预览] stage={stage} method={method} chat={_mask_chat_id(payload.get("chat_id"))} media={media_type}')
    print(f'[TG预览] buttons={_button_preview(payload.get("reply_markup"))}')
    print('[TG预览] content_start')
    print(_preview_text(text))
    print('[TG预览] content_end')
    print('[TG预览]━━━━━━━━━━━━━━━━━━━━\n')


def _build_inline_keyboard(content: str) -> Dict[str, list]:
    return {
        'inline_keyboard': [
            [
                {'text': '👍 点赞 0', 'callback_data': 'tr_like'},
                {'text': '💬 评论 0', 'callback_data': 'tr_comment'},
            ],
            [{'text': '☰ 功能菜单', 'callback_data': 'tr_menu'}],
        ]
    }


def _extract_news_line(text: str) -> str:
    for line in _plain_text(text).splitlines():
        line = line.strip()
        if line.startswith('📰'):
            return line.lstrip('📰').strip()
    for line in _plain_text(text).splitlines():
        line = line.strip()
        if line and not line.startswith(('🔥', '📍', '🧭', '⏱', '🗞️', '━', '📦')):
            return line[:120]
    return ''


def _truncate_utf8(text: str, max_bytes: int) -> str:
    if len(text.encode('utf-8')) <= max_bytes:
        return text
    raw = text.encode('utf-8')[:max_bytes]
    while raw:
        try:
            return raw.decode('utf-8').rstrip() + '\n…'
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ''


def _compose_public_card_text(original_text: str, include_media_block: bool) -> str:
    media_type, media_url = _pick_media_url(original_text)
    title = _extract_news_line(original_text)
    parts = []
    if include_media_block:
        parts.append('🎬 <b>短视频/图片</b>')
        if media_type in ('photo', 'video') and media_url:
            parts.append('已提取到可展示媒体素材，优先以图片/视频卡片展示。')
        else:
            parts.append('当前先编辑为自有短文，不把评论按钮跳转到源链接。')
        parts.append('━━━━━━━━━━━━━━')
    parts.extend([
        '🔥 <b>TrendRadar 热点快报</b>',
        '━━━━━━━━━━━━━━',
        '🧠 <b>要点评论</b>',
        f'• 核心看点：{(title or "本条内容具备继续跟进价值")[:80]}',
        '• 传播价值：适合做热点跟进、短视频剪辑和频道讨论。',
        '• 行业观察：重点关注热度变化、评论反馈和后续事件发展。',
        '━━━━━━━━━━━━━━',
        '📝 <b>编辑短文</b>',
        f'这条内容不是简单转发源链接，而是围绕“{(title or "本条热点")[:60]}”做二次整理。',
        '后续适合剪成自己的短视频文章：标题吸引注意力，正文解释背景、影响和可讨论点。',
        '━━━━━━━━━━━━━━',
        f'📰 {title}' if title else _plain_text(original_text)[:500],
    ])
    return '\n'.join(part for part in parts if part).strip()


def _patch_public_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _is_public_telegram_payload(payload):
        return payload
    patched = dict(payload)
    content = _compose_public_card_text(str(patched.get('text') or patched.get('caption') or ''), True)
    if 'text' in patched:
        patched['text'] = _truncate_utf8(content, 3900)
    elif 'caption' in patched:
        patched['caption'] = _truncate_utf8(content, 950)
    patched['reply_markup'] = _build_inline_keyboard(content)
    return patched


def _build_media_payload(payload: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not _is_public_telegram_payload(payload):
        return None
    original_content = str(payload.get('text') or payload.get('caption') or '')
    media_type, media_url = _pick_media_url(original_content)
    if media_type not in ('photo', 'video') or not media_url:
        return None
    caption = _compose_public_card_text(original_content, False)
    media_payload: Dict[str, Any] = {
        'chat_id': payload.get('chat_id'),
        'caption': _truncate_utf8(caption, 950),
        'parse_mode': payload.get('parse_mode', 'HTML'),
        'reply_markup': _build_inline_keyboard(original_content),
    }
    if media_type == 'photo':
        media_payload['photo'] = media_url
        return 'sendPhoto', media_payload
    media_payload['video'] = media_url
    return 'sendVideo', media_payload


def send_to_telegram(*args: Any, **kwargs: Any) -> bool:
    real_post = _senders.requests.post

    def patched_post(url, *post_args, **post_kwargs):
        payload = post_kwargs.get('json')
        if isinstance(payload, dict) and '/sendMessage' in str(url):
            media_result = _build_media_payload(payload)
            if media_result:
                method, media_payload = media_result
                media_url = str(url).replace('/sendMessage', f'/{method}')
                media_kwargs = dict(post_kwargs)
                media_kwargs['json'] = media_payload
                _log_public_payload_preview(method, media_payload, 'media')
                response = real_post(media_url, *post_args, **media_kwargs)
                try:
                    result = response.json()
                except ValueError:
                    result = {'ok': False}
                if response.status_code == 200 and result.get('ok'):
                    return response
                print(f'[TG预览] 媒体发送失败，自动退回文字卡片。status={response.status_code}')
            post_kwargs['json'] = _patch_public_payload(payload)
            _log_public_payload_preview('sendMessage', post_kwargs['json'], 'text')
        return real_post(url, *post_args, **post_kwargs)

    _senders.requests.post = patched_post
    try:
        return _ORIGINAL_SEND_TO_TELEGRAM(*args, **kwargs)
    finally:
        _senders.requests.post = real_post
