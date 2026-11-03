"""YouTube Data API v3 helpers: metadata enrichment and channel seeding.

Uses only metadata endpoints and embeds. No video or audio is downloaded.
Needs YOUTUBE_API_KEY (Google Cloud console > APIs & Services > Credentials > API key,
with "YouTube Data API v3" enabled). Quota: videos.list costs 1 unit per 50 videos.
"""
from __future__ import annotations

import os
import re

from .common import get_json

API = "https://www.googleapis.com/youtube/v3"


def _key() -> str:
    k = os.environ.get("YOUTUBE_API_KEY")
    if not k:
        raise SystemExit("Set YOUTUBE_API_KEY to enrich or seed videos.")
    return k


def iso_duration_seconds(d: str | None) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s


def videos(ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        body = get_json(f"{API}/videos", params={
            "part": "snippet,contentDetails,statistics,status",
            "id": ",".join(chunk), "key": _key(), "maxResults": 50,
        }, min_interval=0.1) or {}
        for it in body.get("items", []):
            sn, cd, st, stat = it["snippet"], it["contentDetails"], it.get("status", {}), it.get("statistics", {})
            out[it["id"]] = {
                "title": sn.get("title"),
                "channel": sn.get("channelTitle"),
                "channel_id": sn.get("channelId"),
                "published_at": sn.get("publishedAt"),
                "description": (sn.get("description") or "")[:3000],
                "tags": sn.get("tags", [])[:20],
                "duration_s": iso_duration_seconds(cd.get("duration")),
                "captions": cd.get("caption") == "true",
                "embeddable": st.get("embeddable", True),
                "privacy": st.get("privacyStatus"),
                "made_for_kids": st.get("madeForKids", False),
                "views": int(stat.get("viewCount", 0) or 0),
                "yt_likes": int(stat.get("likeCount", 0) or 0),
            }
    return out


def channel_uploads(handle: str, max_items: int = 5000) -> list[dict]:
    body = get_json(f"{API}/channels", params={
        "part": "contentDetails,snippet", "forHandle": handle, "key": _key()}) or {}
    items = body.get("items") or []
    if not items:
        print(f"  no channel found for {handle}")
        return []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    rows, token = [], None
    while len(rows) < max_items:
        params = {"part": "snippet,contentDetails", "playlistId": uploads,
                  "maxResults": 50, "key": _key()}
        if token:
            params["pageToken"] = token
        page = get_json(f"{API}/playlistItems", params=params, min_interval=0.1) or {}
        for it in page.get("items", []):
            rows.append({"video_id": it["contentDetails"]["videoId"],
                         "title": it["snippet"].get("title"),
                         "published_at": it["contentDetails"].get("videoPublishedAt")})
        token = page.get("nextPageToken")
        if not token:
            break
    return rows
