#!/usr/bin/env python3
"""Search YouTube for reusable material candidates.

This module only searches metadata through YouTube Data API v3. It does not
and must not download videos. It is designed for n8n Execute Command nodes or
manual CLI use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import requests

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


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
    score: float
    reason: str


def _request(url: str, params: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text[:800]
        raise RuntimeError(f"YouTube API request failed: {response.status_code} {detail}") from exc
    return response.json()


def _score_candidate(item: dict[str, Any], owned_channel_ids: set[str]) -> Candidate:
    snippet = item.get("snippet") or {}
    status = item.get("status") or {}
    content = item.get("contentDetails") or {}
    statistics = item.get("statistics") or {}

    video_id = str(item.get("id", ""))
    channel_id = str(snippet.get("channelId", ""))
    license_name = str(status.get("license", "youtube"))
    embeddable = bool(status.get("embeddable", False))
    is_owned = channel_id in owned_channel_ids
    is_cc = license_name == "creativeCommon"

    if is_owned:
        risk_level = "green"
        reusable = True
        reason = "Video belongs to an explicitly configured owned channel."
    elif is_cc:
        risk_level = "green"
        reusable = True
        reason = "Video is marked Creative Commons by YouTube; attribution and source verification are still required."
    else:
        risk_level = "red"
        reusable = False
        reason = "Standard YouTube license; use for topic discovery only unless separate permission is documented."

    views = int(statistics.get("viewCount", 0) or 0)
    likes = int(statistics.get("likeCount", 0) or 0)
    score = 0.0
    score += 45.0 if reusable else 0.0
    score += 10.0 if embeddable else 0.0
    score += 5.0 if str(content.get("definition", "")) == "hd" else 0.0
    score += min(20.0, views / 50_000.0)
    score += min(10.0, likes / 5_000.0)

    thumbnails = snippet.get("thumbnails") or {}
    thumbnail = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}

    return Candidate(
        video_id=video_id,
        title=str(snippet.get("title", "")),
        description=str(snippet.get("description", "")),
        channel_id=channel_id,
        channel_title=str(snippet.get("channelTitle", "")),
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
        score=round(score, 2),
        reason=reason,
    )


def search_materials(
    query: str,
    *,
    api_key: str,
    max_results: int = 10,
    creative_commons_only: bool = True,
    published_after: str | None = None,
    region_code: str | None = None,
    owned_channel_ids: set[str] | None = None,
) -> dict[str, Any]:
    owned_channel_ids = owned_channel_ids or set()
    search_params: dict[str, Any] = {
        "key": api_key,
        "part": "snippet",
        "q": query,
        "type": "video",
        "maxResults": min(max(max_results, 1), 50),
        "order": "relevance",
        "safeSearch": "moderate",
        "videoEmbeddable": "true",
    }
    if creative_commons_only:
        search_params["videoLicense"] = "creativeCommon"
    if published_after:
        search_params["publishedAfter"] = published_after
    if region_code:
        search_params["regionCode"] = region_code

    search_data = _request(SEARCH_URL, search_params)
    ids = [
        str((item.get("id") or {}).get("videoId", ""))
        for item in search_data.get("items", [])
        if (item.get("id") or {}).get("videoId")
    ]

    candidates: list[Candidate] = []
    if ids:
        videos_data = _request(
            VIDEOS_URL,
            {
                "key": api_key,
                "part": "snippet,contentDetails,status,statistics",
                "id": ",".join(ids),
                "maxResults": len(ids),
            },
        )
        candidates = [_score_candidate(item, owned_channel_ids) for item in videos_data.get("items", [])]
        candidates.sort(key=lambda item: item.score, reverse=True)

    return {
        "query": query,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "creative_commons_only": creative_commons_only,
        "candidate_count": len(candidates),
        "reusable_count": sum(item.reusable for item in candidates),
        "candidates": [asdict(item) for item in candidates],
        "policy": {
            "green": "Owned or Creative Commons candidate; verify attribution and the uploader's authority before reuse.",
            "red": "Standard-license candidate; discovery only unless separate permission is recorded.",
            "download_performed": False,
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search YouTube material candidates for TZ02/n8n")
    parser.add_argument("query", help="Search topic or keywords")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--all-licenses", action="store_true", help="Include standard-license videos as discovery-only candidates")
    parser.add_argument("--published-after", help="RFC3339 timestamp, for example 2026-07-01T00:00:00Z")
    parser.add_argument("--region-code", default=os.getenv("YOUTUBE_REGION_CODE", "US"))
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"error": "YOUTUBE_API_KEY is not configured"}, ensure_ascii=False), file=sys.stderr)
        return 2

    owned_channels = {
        value.strip()
        for value in os.getenv("YOUTUBE_OWNED_CHANNEL_IDS", "").split(",")
        if value.strip()
    }
    try:
        result = search_materials(
            args.query,
            api_key=api_key,
            max_results=args.max_results,
            creative_commons_only=not args.all_licenses,
            published_after=args.published_after,
            region_code=args.region_code,
            owned_channel_ids=owned_channels,
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
