#!/usr/bin/env python3
"""Search YouTube metadata for reusable, relevant material candidates."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_EXCLUDE_PATTERNS = (
    "tiktok", "compilation", "reaction", "reupload", "re-upload",
    "fan channel", "shorts compilation", "top 10", "2k gameplay",
)


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load simple KEY=VALUE pairs without adding a dependency."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Candidate:
    video_id: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    duration: str
    definition: str
    embeddable: bool
    license: str
    view_count: int
    like_count: int
    thumbnail_url: str
    watch_url: str
    risk_level: str
    reusable: bool
    relevance_score: float
    quality_score: float
    score: float
    excluded: bool
    reason: str


def _request(url: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"YouTube API request failed: {response.status_code} {response.text[:800]}"
        ) from exc
    return response.json()


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._'-]{1,}", text or "")
        if len(token) >= 2
    }


def _relevance(title: str, description: str, query: str, keywords: list[str]) -> float:
    haystack = f"{title} {description}".lower()
    query_tokens = _tokens(query)
    keyword_tokens = {k.lower().strip() for k in keywords if k.strip()}
    wanted = query_tokens | keyword_tokens
    if not wanted:
        return 0.0
    title_lower = title.lower()
    title_hits = sum(1 for token in wanted if token in title_lower)
    body_hits = sum(1 for token in wanted if token in haystack)
    phrase_bonus = 20.0 if query.lower().strip() in haystack else 0.0
    return min(100.0, phrase_bonus + title_hits * 14.0 + body_hits * 5.0)


def _is_excluded(title: str, channel: str, patterns: list[str]) -> tuple[bool, str]:
    text = f"{title} {channel}".lower()
    for pattern in patterns:
        value = pattern.lower().strip()
        if value and value in text:
            return True, f"Excluded by pattern: {pattern}"
    return False, ""


def _score_candidate(
    item: dict[str, Any],
    owned_channel_ids: set[str],
    query: str,
    keywords: list[str],
    exclude_patterns: list[str],
    min_relevance: float,
) -> Candidate:
    snippet = item.get("snippet") or {}
    status = item.get("status") or {}
    content = item.get("contentDetails") or {}
    statistics = item.get("statistics") or {}

    video_id = str(item.get("id", ""))
    title = str(snippet.get("title", ""))
    description = str(snippet.get("description", ""))
    channel_id = str(snippet.get("channelId", ""))
    channel_title = str(snippet.get("channelTitle", ""))
    license_name = str(status.get("license", "youtube"))
    embeddable = bool(status.get("embeddable", False))
    is_owned = channel_id in owned_channel_ids
    is_cc = license_name == "creativeCommon"

    excluded, exclusion_reason = _is_excluded(title, channel_title, exclude_patterns)
    relevance_score = _relevance(title, description, query, keywords)
    low_relevance = relevance_score < min_relevance

    reusable = (is_owned or is_cc) and embeddable and not excluded and not low_relevance
    if excluded:
        risk_level, reason = "red", exclusion_reason
    elif low_relevance:
        risk_level, reason = "yellow", f"Low topic relevance: {relevance_score:.1f} < {min_relevance:.1f}"
    elif is_owned:
        risk_level, reason = "green", "Owned channel and topic match passed."
    elif is_cc:
        risk_level, reason = "green", "Creative Commons candidate; attribution and uploader authority still require verification."
    else:
        risk_level, reason = "red", "Standard YouTube license; discovery only unless separate permission is documented."

    views = int(statistics.get("viewCount", 0) or 0)
    likes = int(statistics.get("likeCount", 0) or 0)
    quality_score = 0.0
    quality_score += 10.0 if embeddable else 0.0
    quality_score += 8.0 if str(content.get("definition", "")) == "hd" else 0.0
    quality_score += min(12.0, math.log10(max(views, 1)) * 2.0)
    quality_score += min(10.0, math.log10(max(likes, 1)) * 2.0)
    rights_score = 35.0 if (is_owned or is_cc) else 0.0
    score = max(0.0, rights_score + relevance_score * 0.45 + quality_score - (40.0 if excluded else 0.0))

    thumbnails = snippet.get("thumbnails") or {}
    thumbnail = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
    return Candidate(
        video_id=video_id,
        title=title,
        description=description,
        channel_id=channel_id,
        channel_title=channel_title,
        published_at=str(snippet.get("publishedAt", "")),
        duration=str(content.get("duration", "")),
        definition=str(content.get("definition", "")),
        embeddable=embeddable,
        license=license_name,
        view_count=views,
        like_count=likes,
        thumbnail_url=str(thumbnail.get("url", "")),
        watch_url=f"https://www.youtube.com/watch?v={video_id}",
        risk_level=risk_level,
        reusable=reusable,
        relevance_score=round(relevance_score, 2),
        quality_score=round(quality_score, 2),
        score=round(score, 2),
        excluded=excluded,
        reason=reason,
    )


def _telegram_approval(query: str, candidates: list[Candidate]) -> dict[str, Any]:
    selected = [c for c in candidates if c.reusable][:3]
    lines = [f"🎬 YouTube 素材候选", f"主题：{query}", ""]
    keyboard: list[list[dict[str, str]]] = []
    for index, item in enumerate(selected, 1):
        lines.extend([
            f"{index}. {item.title[:80]}",
            f"频道：{item.channel_title}｜相关度：{item.relevance_score:.0f}｜总分：{item.score:.0f}",
            f"许可：{item.license}",
            "",
        ])
        keyboard.append([
            {"text": f"▶️ 查看 {index}", "url": item.watch_url},
            {"text": f"✅ 批准 {index}", "callback_data": f"yt_approve:{item.video_id}"},
            {"text": f"❌ 拒绝 {index}", "callback_data": f"yt_reject:{item.video_id}"},
        ])
    if not selected:
        lines.append("没有通过版权与相关性门槛的候选素材。")
    return {
        "text": "\n".join(lines).strip(),
        "reply_markup": {"inline_keyboard": keyboard},
        "candidate_video_ids": [item.video_id for item in selected],
    }


def search_materials(
    query: str,
    *,
    api_key: str,
    max_results: int = 10,
    creative_commons_only: bool = True,
    published_after: str | None = None,
    region_code: str | None = None,
    owned_channel_ids: set[str] | None = None,
    keywords: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    min_relevance: float = 20.0,
) -> dict[str, Any]:
    owned_channel_ids = owned_channel_ids or set()
    keywords = keywords or []
    exclude_patterns = exclude_patterns or list(DEFAULT_EXCLUDE_PATTERNS)
    params: dict[str, Any] = {
        "key": api_key, "part": "snippet", "q": query, "type": "video",
        "maxResults": min(max(max_results, 1), 50), "order": "relevance",
        "safeSearch": "moderate", "videoEmbeddable": "true",
    }
    if creative_commons_only:
        params["videoLicense"] = "creativeCommon"
    if published_after:
        params["publishedAfter"] = published_after
    if region_code:
        params["regionCode"] = region_code

    search_data = _request(SEARCH_URL, params)
    ids = [str((x.get("id") or {}).get("videoId", "")) for x in search_data.get("items", [])]
    ids = [x for x in ids if x]
    candidates: list[Candidate] = []
    if ids:
        details = _request(VIDEOS_URL, {
            "key": api_key, "part": "snippet,contentDetails,status,statistics",
            "id": ",".join(ids), "maxResults": len(ids),
        })
        candidates = [
            _score_candidate(x, owned_channel_ids, query, keywords, exclude_patterns, min_relevance)
            for x in details.get("items", [])
        ]
        candidates.sort(key=lambda x: (x.reusable, x.score), reverse=True)

    return {
        "query": query,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "creative_commons_only": creative_commons_only,
        "min_relevance": min_relevance,
        "candidate_count": len(candidates),
        "reusable_count": sum(x.reusable for x in candidates),
        "candidates": [asdict(x) for x in candidates],
        "telegram_approval": _telegram_approval(query, candidates),
        "policy": {
            "green": "Owned or Creative Commons, embeddable, and relevant; verify attribution/uploader authority.",
            "yellow": "Rights may be acceptable but topic relevance is below threshold.",
            "red": "Excluded or standard-license discovery-only candidate.",
            "download_performed": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search and rank YouTube material candidates for TZ02/n8n")
    parser.add_argument("query")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--all-licenses", action="store_true")
    parser.add_argument("--published-after")
    parser.add_argument("--region-code", default=os.getenv("YOUTUBE_REGION_CODE", "US"))
    parser.add_argument("--keywords", default="", help="Comma-separated required topic hints, e.g. Lakers,LeBron")
    parser.add_argument("--exclude", default="", help="Additional comma-separated exclusion patterns")
    parser.add_argument("--min-relevance", type=float, default=20.0)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    _load_dotenv()
    args = _parse_args()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"error": "YOUTUBE_API_KEY is not configured"}, ensure_ascii=False), file=sys.stderr)
        return 2
    owned = {x.strip() for x in os.getenv("YOUTUBE_OWNED_CHANNEL_IDS", "").split(",") if x.strip()}
    keywords = [x.strip() for x in args.keywords.split(",") if x.strip()]
    excludes = list(DEFAULT_EXCLUDE_PATTERNS) + [x.strip() for x in args.exclude.split(",") if x.strip()]
    try:
        result = search_materials(
            args.query, api_key=api_key, max_results=args.max_results,
            creative_commons_only=not args.all_licenses,
            published_after=args.published_after, region_code=args.region_code,
            owned_channel_ids=owned, keywords=keywords,
            exclude_patterns=excludes, min_relevance=args.min_relevance,
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
