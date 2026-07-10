# coding=utf-8
"""Telegram interactions for TZ02 final one-page menu."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

STATE_VERSION = 6
DEFAULT_STATE_PATH = 'data/telegram_interactions_state.json'
DEFAULT_POLL_SECONDS = 21000
DEFAULT_POLL_TIMEOUT = 20


def _load_state(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:
        data = {}
    data['version'] = STATE_VERSION
    data.setdefault('offset', 0)
    data.setdefault('likes', {})
    data.setdefault('liked_by', {})
    return data


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')


def _api(token: str, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Dict[str, Any]:
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(payload or {}, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout + 5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        print(f'[TG互动] API Error method={method}: {exc}')
        return {'ok': False, 'description': str(exc)}


def _menu_url(key: str) -> str:
    env_map = {
        'nba': 'TELEGRAM_MENU_NBA_URL', 'football': 'TELEGRAM_MENU_FOOTBALL_URL',
        'live': 'TELEGRAM_MENU_LIVE_URL', 'highlights': 'TELEGRAM_MENU_HIGHLIGHTS_URL',
        'baccarat': 'TELEGRAM_MENU_BACCARAT_URL', 'poker': 'TELEGRAM_MENU_POKER_URL',
        'dragon_tiger': 'TELEGRAM_MENU_DRAGON_TIGER_URL', 'egame': 'TELEGRAM_MENU_EGAME_URL',
    }
    return os.getenv(env_map.get(key, ''), '').strip()


def _channel_button(text: str, key: str) -> Dict[str, str]:
    url = _menu_url(key)
    if url.startswith(('http://', 'https://', 'tg://')):
        return {'text': text, 'url': url}
    return {'text': text, 'callback_data': f'tr_link:{key}'}


def _keyboard(like_count: int = 0) -> Dict[str, Any]:
    label = '👍 点赞' if like_count <= 0 else f'👍 {like_count}'
    return {'inline_keyboard': [
        [_channel_button('NBA', 'nba'), _channel_button('足球', 'football')],
        [_channel_button('直播', 'live'), _channel_button('集锦', 'highlights')],
        [_channel_button('百家乐', 'baccarat'), _channel_button('德州扑克', 'poker')],
        [_channel_button('龙虎斗', 'dragon_tiger'), _channel_button('电子游戏', 'egame')],
        [{'text': label, 'callback_data': 'tr_like'}, {'text': '💬 评论', 'callback_data': 'tr_comment'}],
    ]}


def _answer(token: str, callback_id: str, text: str) -> None:
    _api(token, 'answerCallbackQuery', {'callback_query_id': callback_id, 'text': text[:180], 'show_alert': False})


def _handle(token: str, state: Dict[str, Any], callback: Dict[str, Any]) -> bool:
    callback_id = str(callback.get('id') or '')
    data = str(callback.get('data') or '')
    message = callback.get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')
    message_id = message.get('message_id')
    user_id = str((callback.get('from') or {}).get('id') or '')
    if not callback_id or not chat_id or not message_id:
        return False
    key = f'{chat_id}:{message_id}'
    if data.startswith('tr_like'):
        liked = state.setdefault('liked_by', {}).setdefault(key, [])
        if user_id in liked:
            liked.remove(user_id)
            action = '已取消点赞'
        else:
            liked.append(user_id)
            action = '已点赞'
        count = len(liked)
        state.setdefault('likes', {})[key] = count
        _api(token, 'editMessageReplyMarkup', {'chat_id': chat_id, 'message_id': message_id, 'reply_markup': _keyboard(count)})
        _answer(token, callback_id, f'{action}，当前 {count} 个赞')
        return True
    if data.startswith('tr_comment'):
        _answer(token, callback_id, '请直接回复这条消息发表评论。')
        return False
    if data.startswith('tr_link:'):
        _answer(token, callback_id, '该频道链接尚未配置，请先在 GitHub Secrets 填写对应 TELEGRAM_MENU_*_URL。')
        return False
    return False


def poll(token: str, state_path: Path, poll_seconds: int, poll_timeout: int) -> None:
    _api(token, 'deleteWebhook', {'drop_pending_updates': False}, timeout=10)
    state = _load_state(state_path)
    started = time.time()
    while time.time() - started < poll_seconds:
        result = _api(token, 'getUpdates', {
            'offset': int(state.get('offset') or 0), 'timeout': poll_timeout,
            'allowed_updates': ['callback_query'],
        }, timeout=poll_timeout + 10)
        if not result.get('ok'):
            time.sleep(5)
            continue
        for update in result.get('result') or []:
            update_id = int(update.get('update_id') or 0)
            state['offset'] = max(int(state.get('offset') or 0), update_id + 1)
            if 'callback_query' in update:
                _handle(token, state, update['callback_query'])
            _save_state(state_path, state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default=os.getenv('TELEGRAM_INTERACTION_STATE', DEFAULT_STATE_PATH))
    parser.add_argument('--poll-seconds', type=int, default=int(os.getenv('TELEGRAM_INTERACTION_POLL_SECONDS', DEFAULT_POLL_SECONDS)))
    parser.add_argument('--poll-timeout', type=int, default=int(os.getenv('TELEGRAM_INTERACTION_POLL_TIMEOUT', DEFAULT_POLL_TIMEOUT)))
    args = parser.parse_args()
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        print('[TG互动] TELEGRAM_BOT_TOKEN is empty, skip.')
        return
    poll(token, Path(args.state), args.poll_seconds, args.poll_timeout)


if __name__ == '__main__':
    main()
