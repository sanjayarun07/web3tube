"""Provisional video metadata without a YouTube API key.

    python -m pipeline.meta_fallback

For every mentioned video that has no real metadata yet, take a title from (in order):
  1. the Devcon Archive / StreamETH seed record (title, speakers, duration, date),
  2. Discourse's own embed (data-video-title on the lazy-video container),
  3. the anchor text of the link, when it is not just the URL.
Rows are marked "meta_source": "fallback". `make enrich` replaces them with real YouTube metadata
(and drops videos that turn out to be deleted or private). Fallback rows have no views, captions or
channel id, so treat the resulting catalog as a preview.
"""
from __future__ import annotations

import html
import re
from collections import defaultdict

from bs4 import BeautifulSoup

from .common import DATA, RAW, read_jsonl, write_jsonl
from .extract import video_id_from_url

LAZY = re.compile(r'data-video-id="([A-Za-z0-9_-]{11})"\s+data-video-title="([^"]*)"')


def titles_from_posts(wanted: set[str]) -> dict[str, str]:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for path in sorted(RAW.glob("*.jsonl")):
        if path.name == "seeds.jsonl":
            continue
        for p in read_jsonl(path):
            cooked = p.get("cooked") or ""
            if "youtu" not in cooked:
                continue
            for vid, title in LAZY.findall(cooked):
                if vid in wanted and title.strip():
                    votes[vid][html.unescape(title).strip()] += 3
            for a in BeautifulSoup(cooked, "html.parser").find_all("a", href=True):
                vid = video_id_from_url(a["href"])
                text = a.get_text(" ", strip=True)
                if (vid in wanted and text and len(text) > 8 and "youtu" not in text.lower()
                        and not text.lower().startswith("http")):
                    votes[vid][re.sub(r"^\[(video|talk|youtube)\]\s*", "", text, flags=re.I)] += 1
    return {v: max(t.items(), key=lambda kv: kv[1])[0] for v, t in votes.items()}


def main() -> None:
    mentioned = {m["video_id"] for m in read_jsonl(DATA / "mentions.jsonl")}
    meta = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    seeds = {r["video_id"]: r for r in read_jsonl(RAW / "seeds.jsonl")}
    wanted = {v for v in mentioned if v not in meta or meta[v].get("meta_source") == "fallback"}
    titles = titles_from_posts(wanted)
    n_seed = n_post = n_none = 0
    for vid in wanted:
        s = seeds.get(vid) or {}
        title = s.get("title") or titles.get(vid)
        if s.get("title"):
            n_seed += 1
        elif title:
            n_post += 1
        else:
            n_none += 1
        speakers = ", ".join(s.get("speakers") or [])
        meta[vid] = {
            "video_id": vid, "meta_source": "fallback",
            "title": title or "Untitled video (metadata pending)",
            "channel": s.get("seed", "").split(" · ")[-1] if s else "",
            "channel_id": None, "published_at": s.get("published_at"),
            "description": " ".join(x for x in [speakers and f"Speakers: {speakers}.", s.get("abstract", "")] if x)[:3000],
            "tags": s.get("tags", []), "duration_s": s.get("duration_s") or 0, "captions": False,
            "embeddable": True, "privacy": "public", "made_for_kids": False, "views": 0, "yt_likes": 0,
        }
    write_jsonl(DATA / "videos_meta.jsonl", meta.values())
    print(f"fallback metadata for {len(wanted)} videos: {n_seed} from archives, {n_post} from forum "
          f"link text, {n_none} without a title")


if __name__ == "__main__":
    main()
