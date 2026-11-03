"""Extract YouTube mentions (with surrounding discussion) from raw posts.

    python -m pipeline.extract
Reads  data/raw/*.jsonl (forums, HN, Reddit, GitHub) and data/raw/seeds.jsonl
Writes data/mentions.jsonl   one row per (post, video), plus 'reply' rows for direct replies
       data/video_ids.txt    every distinct video id that needs metadata
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .common import DATA, RAW, read_jsonl, write_jsonl

ID = r"([A-Za-z0-9_-]{11})"
URL_PATTERNS = [
    re.compile(r"(?:https?:)?//(?:www\.|m\.|music\.)?youtube(?:-nocookie)?\.com/(?:embed|shorts|live|v|e)/" + ID),
    re.compile(r"(?:https?:)?//(?:www\.)?youtu\.be/" + ID),
]
CONTEXT_CHARS = 1500


def video_id_from_url(url: str) -> str | None:
    """Normalize any YouTube URL form to its 11-char id. Returns None for playlists/channels."""
    if not url:
        return None
    for pat in URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    try:
        u = urlparse(url if "//" in url else "https://" + url)
    except ValueError:
        return None
    host = (u.netloc or "").lower()
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if u.path in ("/watch", "/watch/"):
            v = parse_qs(u.query).get("v", [""])[0]
            if re.fullmatch(ID, v):
                return v
        if u.path.startswith("/attribution_link"):
            inner = parse_qs(u.query).get("u", [""])[0]
            return video_id_from_url("https://www.youtube.com" + inner)
    return None


def timestamp_from_url(url: str) -> int | None:
    q = parse_qs(urlparse(url).query)
    t = (q.get("t") or q.get("start") or [None])[0]
    if not t:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?", t)
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s or None


def parse_post(cooked: str) -> tuple[str, dict[str, int | None]]:
    """Return (plain text with [VIDEO] markers, {video_id: timestamp}) for the author's own words.

    Quoted blocks are removed first: a link inside someone else's quote is their mention, not
    this author's.
    """
    soup = BeautifulSoup(cooked or "", "html.parser")
    for q in soup.select("aside.quote, blockquote"):
        q.decompose()
    found: dict[str, int | None] = {}

    def add(vid, ts=None):
        if vid and (vid not in found or (found[vid] is None and ts)):
            found[vid] = ts

    for el in soup.select("[data-video-id], [data-youtube-id]"):
        vid = el.get("data-video-id") or el.get("data-youtube-id")
        if el.get("data-provider-name", "youtube").lower() == "youtube" and re.fullmatch(ID, vid or ""):
            add(vid, None)
            el.replace_with(" [VIDEO] ")
    for el in soup.select("iframe[src]"):
        vid = video_id_from_url(el["src"])
        if vid:
            add(vid)
            el.replace_with(" [VIDEO] ")
    for a in soup.select("a[href]"):
        vid = video_id_from_url(a["href"])
        if vid:
            add(vid, timestamp_from_url(a["href"]))
            label = a.get_text(" ", strip=True)
            a.replace_with(f" [VIDEO: {label}] " if label and "youtu" not in label else " [VIDEO] ")
    text = soup.get_text(" ", strip=True)
    # bare URLs that Discourse did not linkify
    for m in re.finditer(r"\S*youtu\S+", text):
        add(video_id_from_url(m.group(0)), timestamp_from_url(m.group(0)))
    text = re.sub(r"\S*youtu\S+", "[VIDEO]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text, found


def _clip(s: str, n: int = CONTEXT_CHARS) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> None:
    posts = []
    for path in sorted(p for p in RAW.glob("*.jsonl") if p.name != "seeds.jsonl"):
        posts += list(read_jsonl(path))
    print(f"{len(posts)} posts loaded")

    by_key = {(p["forum"], p["topic_id"], p["post_number"]): p for p in posts}
    replies = defaultdict(list)
    for p in posts:
        if p.get("reply_to"):
            replies[(p["forum"], p["topic_id"], p["reply_to"])].append(p)

    mentions, ids = [], set()
    for p in posts:
        text, vids = parse_post(p["cooked"])
        if not vids:
            continue
        key = (p["forum"], p["topic_id"], p["post_number"])
        parent = by_key.get((p["forum"], p["topic_id"], p["reply_to"])) if p.get("reply_to") else None
        parent_text = _clip(parse_post(parent["cooked"])[0], 500) if parent else ""
        kids = sorted(replies.get(key, []), key=lambda r: r["created_at"] or "")[:5]
        base = {k: p[k] for k in ("source", "forum", "post_id", "topic_id", "topic_title", "category",
                                  "post_number", "author", "author_trust", "author_is_staff",
                                  "created_at", "likes", "url")}
        for vid, ts in vids.items():
            ids.add(vid)
            mentions.append({
                **base, "id": f"{p['forum']}:{p['post_id']}:{vid}", "video_id": vid, "kind": "post",
                "timestamp": ts, "videos_in_post": len(vids), "text": _clip(text),
                "parent_text": parent_text,
                "reply_texts": [_clip(parse_post(r["cooked"])[0], 300) for r in kids],
            })
            # Direct replies are separate, independent signals about the same video.
            for r in kids:
                if r["author"] == p["author"]:
                    continue
                rtext, rvids = parse_post(r["cooked"])
                if rvids:  # a reply with its own video links is handled as its own post
                    continue
                mentions.append({
                    **{k: r[k] for k in base}, "id": f"{r['forum']}:{r['post_id']}:{vid}:reply",
                    "video_id": vid, "kind": "reply", "timestamp": None, "videos_in_post": len(vids),
                    "text": _clip(rtext, 800), "parent_text": _clip(text, 600), "reply_texts": [],
                })

    for s in read_jsonl(RAW / "seeds.jsonl"):
        ids.add(s["video_id"])

    write_jsonl(DATA / "mentions.jsonl", mentions)
    (DATA / "video_ids.txt").write_text("\n".join(sorted(ids)) + "\n")
    n_post = sum(m["kind"] == "post" for m in mentions)
    print(f"{n_post} video mentions + {len(mentions) - n_post} replies; {len(ids)} distinct videos")


if __name__ == "__main__":
    main()
