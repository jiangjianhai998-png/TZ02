# coding=utf-8
from __future__ import annotations

import hashlib
import os
import re
from html import escape, unescape
from typing import Any, Dict, Optional, Tuple

from . import senders as _senders

_ORIGINAL_SEND_TO_TELEGRAM = _senders.send_to_telegram
_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.gif')
_VIDEO_EXTENSIONS = ('.mp4', '.mov', '.m4v', '.webm')


class _BufferedTelegramResponse:
    """Pretend a buffered public batch was accepted by Telegram."""

    status_code = 200
    text = '{"ok": true}'

    @staticmethod
    def json() -> Dict[str, Any]:
        return {'ok': True, 'result': {'message_id': 0}}


def _plain_text(text: str) -> str:
    if not text:
        return ''
    text = unescape(str(text))
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    urls.extend(re.findall(r'<a\s+href=["\']([^"\']+)["\']', text or '', flags=re.IGNORECASE))
    urls.extend(re.findall(r'https?://[^\s<>\'\"]+', text or ''))
    result: list[str] = []
    seen: set[str] = set()
    for url in urls:
        value = str(url).strip().rstrip('，。；;、)')
        if value and value not in seen:
            seen.add(value)
            result.append(value)
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
    return '', ''


def _post_id(content: str) -> str:
    base = _plain_text(content)[:500] or str(content)[:500]
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:16]


def _is_public_telegram_payload(payload: Dict[str, Any]) -> bool:
    chat_id = str(payload.get('chat_id', '')).strip()
    return bool(chat_id) and not _senders._is_telegram_private_target(chat_id)


def _menu_url(key: str) -> str:
    env_map = {
        'nba': 'TELEGRAM_MENU_NBA_URL',
        'football': 'TELEGRAM_MENU_FOOTBALL_URL',
        'live': 'TELEGRAM_MENU_LIVE_URL',
        'highlights': 'TELEGRAM_MENU_HIGHLIGHTS_URL',
        'baccarat': 'TELEGRAM_MENU_BACCARAT_URL',
        'poker': 'TELEGRAM_MENU_POKER_URL',
        'dragon_tiger': 'TELEGRAM_MENU_DRAGON_TIGER_URL',
        'egame': 'TELEGRAM_MENU_EGAME_URL',
    }
    return os.getenv(env_map.get(key, ''), '').strip()


def _channel_button(text: str, key: str) -> Dict[str, str]:
    url = _menu_url(key)
    if url.startswith(('http://', 'https://', 'tg://')):
        return {'text': text, 'url': url}
    return {'text': text, 'callback_data': f'tr_link:{key}'}


def _build_inline_keyboard(content: str) -> Dict[str, list]:
    post_id = _post_id(content)
    return {
        'inline_keyboard': [
            [_channel_button('NBA', 'nba'), _channel_button('足球', 'football')],
            [_channel_button('直播', 'live'), _channel_button('集锦', 'highlights')],
            [_channel_button('百家乐', 'baccarat'), _channel_button('德州扑克', 'poker')],
            [_channel_button('龙虎斗', 'dragon_tiger'), _channel_button('电子游戏', 'egame')],
            [{'text': '👍 点赞', 'callback_data': f'tr_like:{post_id}'}],
        ]
    }


_REMOVE_MARKERS = (
    'TrendRadar 原创编辑快报', 'TrendRadar 热点快报', 'TrendRadar',
    '要点评论', '核心看点', '传播价值', '行业观察', '编辑短文',
    '短视频/图片', '热点短视频/图片', '当前先编辑为自有短文',
    '不把评论按钮跳转到源链接', '这条内容不是简单转发源链接',
    '我们会把信息提取、压缩、改写成自己的视频文章结构',
    '标题、导语、看点、评论点和互动问题', '功能菜单',
)

_BATCH_OR_STATS = re.compile(
    r'^(?:\[?第\s*\d+\s*/\s*\d+\s*批次\]?|总新闻|新增|热榜|RSS|时间|类型|报告类型|更新时间)'
)


def _extract_short_comment(original_text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in _plain_text(original_text).splitlines():
        line = raw.strip()
        if not line or line.startswith('━'):
            continue
        if _BATCH_OR_STATS.match(line) or ('批次' in line and '总新闻' in line):
            continue
        if any(marker in line for marker in _REMOVE_MARKERS):
            continue
        line = re.sub(r'^[🧠📝📰🎬🔥📍🧭⏱🗞️📦]\s*', '', line).strip()
        line = re.sub(r'^[•\-*]\s*', '', line).strip()
        line = re.sub(r'^\d+[\.、)]\s*', '', line).strip()
        if not line or line in {'AI原创短评', '今日头条', '热点快报'}:
            continue
        if line not in seen:
            seen.add(line)
            lines.append(line)
        if len(' '.join(lines)) >= 60:
            break
    comment = ' '.join(lines).strip()
    if not comment:
        comment = '本轮热点已完成筛选与二次整理，重点信息将持续更新，并同步到对应内容频道。'
    comment = re.sub(r'\s+', ' ', comment)
    return comment[:87].rstrip() + '...' if len(comment) > 90 else comment


def _compose_public_card_text(original_text: str) -> str:
    comment = escape(_extract_short_comment(original_text), quote=False)
    return '\n'.join([
        'AI原创短评',
        '',
        comment,
        '',
        '━━━━━━━━━━━━━━',
    ]).strip()


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


def _patch_public_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _is_public_telegram_payload(payload):
        return payload
    patched = dict(payload)
    original_content = str(patched.get('text') or patched.get('caption') or '')
    content = _compose_public_card_text(original_content)
    patched.pop('caption', None)
    patched['text'] = _truncate_utf8(content, 3900)
    patched['reply_markup'] = _build_inline_keyboard(original_content)
    patched['parse_mode'] = 'HTML'
    patched['disable_web_page_preview'] = True
    return patched


def _build_media_payload(payload: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    if not _is_public_telegram_payload(payload):
        return None
    original_content = str(payload.get('text') or payload.get('caption') or '')
    media_type, media_url = _pick_media_url(original_content)
    if media_type not in ('photo', 'video') or not media_url:
        return None
    media_payload: Dict[str, Any] = {
        'chat_id': payload.get('chat_id'),
        'caption': _truncate_utf8(_compose_public_card_text(original_content), 950),
        'parse_mode': 'HTML',
        'reply_markup': _build_inline_keyboard(original_content),
    }
    if media_type == 'photo':
        media_payload['photo'] = media_url
        return 'sendPhoto', media_payload
    media_payload['video'] = media_url
    return 'sendVideo', media_payload


def _preferred_ai_content(kwargs: Dict[str, Any]) -> str:
    ai_analysis = kwargs.get('ai_analysis')
    if not ai_analysis:
        return ''
    try:
        return str(_senders._render_ai_analysis(ai_analysis, 'telegram') or '').strip()
    except Exception:
        return str(ai_analysis).strip()


def _response_ok(response: Any) -> bool:
    try:
        result = response.json()
    except Exception:
        result = {'ok': False}
    return bool(getattr(response, 'status_code', 0) == 200 and result.get('ok'))


def send_to_telegram(*args: Any, **kwargs: Any) -> bool:
    """Send one public card per report while keeping private reports unchanged."""

    real_post = _senders.requests.post
    buffered: list[Tuple[str, tuple[Any, ...], Dict[str, Any], Dict[str, Any]]] = []

    def patched_post(url: str, *post_args: Any, **post_kwargs: Any):
        payload = post_kwargs.get('json')
        if (
            isinstance(payload, dict)
            and '/sendMessage' in str(url)
            and _is_public_telegram_payload(payload)
        ):
            buffered.append((str(url), post_args, dict(post_kwargs), dict(payload)))
            return _BufferedTelegramResponse()
        return real_post(url, *post_args, **post_kwargs)

    _senders.requests.post = patched_post
    try:
        original_ok = bool(_ORIGINAL_SEND_TO_TELEGRAM(*args, **kwargs))
    finally:
        _senders.requests.post = real_post

    if not buffered:
        return original_ok

    first_url, first_args, first_kwargs, first_payload = buffered[0]
    combined_batches = '\n\n'.join(
        str(payload.get('text') or payload.get('caption') or '')
        for _, _, _, payload in buffered
    )
    preferred = _preferred_ai_content(kwargs)
    source_content = '\n\n'.join(part for part in (preferred, combined_batches) if part.strip())

    final_payload = dict(first_payload)
    final_payload['text'] = source_content
    final_payload.pop('caption', None)

    media_result = _build_media_payload(final_payload)
    send_url = first_url
    send_payload: Dict[str, Any]
    if media_result:
        method, send_payload = media_result
        send_url = first_url.replace('/sendMessage', f'/{method}')
    else:
        send_payload = _patch_public_payload(final_payload)

    final_kwargs = dict(first_kwargs)
    final_kwargs['json'] = send_payload
    response = real_post(send_url, *first_args, **final_kwargs)
    if not _response_ok(response):
        try:
            description = response.json().get('description')
        except Exception:
            description = getattr(response, 'text', '')
        print(f"Telegram公开卡片发送失败：{description}")
        return False

    print(f"Telegram公开卡片已合并 {len(buffered)} 个批次并单条发送")
    return original_ok
