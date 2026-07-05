# coding=utf-8
"""Runtime compatibility patches for TZ02 GitHub Actions.

This file is imported automatically by Python when the repository root is on
sys.path. It keeps small production hotfixes isolated from large upstream files.
"""

from __future__ import annotations

import builtins
import sys
from typing import Any

_ORIGINAL_IMPORT = builtins.__import__
_PATCHED = False


def _is_public_telegram_target(chat_id: str) -> bool:
    """Return True for Telegram channels/groups that should use public formatting."""
    chat_id_str = str(chat_id or "").strip()
    if not chat_id_str:
        return False

    lowered = chat_id_str.lower()
    # Channel usernames are usually used as @channel_name in TELEGRAM_CHAT_ID.
    # The original sender only treated negative numeric IDs as public, so @channels
    # were mistakenly handled as private debug targets and leaked batch/stat/error lines.
    if chat_id_str.startswith("@"):
        return True
    if lowered.startswith("t.me/") or lowered.startswith("https://t.me/"):
        return True
    if chat_id_str.startswith("-"):
        return True
    return False


def _patch_senders(module: Any) -> None:
    global _PATCHED
    if _PATCHED or not module:
        return

    original_get_private_ids = getattr(module, "_get_telegram_private_chat_ids", None)

    def _is_telegram_private_target(chat_id: str) -> bool:
        chat_id_str = str(chat_id or "").strip()
        private_ids = set(original_get_private_ids() if original_get_private_ids else [])
        if chat_id_str in private_ids:
            return True
        # @channel_username and -100... IDs are public Telegram targets.
        # Only plain positive numeric user IDs are treated as private.
        return bool(chat_id_str) and not _is_public_telegram_target(chat_id_str)

    module._is_telegram_private_target = _is_telegram_private_target
    _PATCHED = True
    print("[TZ02] Telegram public channel formatting patch enabled")


def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
    try:
        senders = sys.modules.get("trendradar.notification.senders")
        if senders is not None:
            _patch_senders(senders)
    except Exception as exc:
        print(f"[TZ02] sitecustomize patch skipped: {exc}")
    return module


builtins.__import__ = _patched_import

# If senders was imported before this hook was installed, patch it immediately.
if "trendradar.notification.senders" in sys.modules:
    _patch_senders(sys.modules["trendradar.notification.senders"])
