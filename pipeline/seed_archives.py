"""Seed conference talks from the Devcon Archive and StreamETH without a YouTube API key.

    python -m pipeline.seed_archives                 # both
    python -m pipeline.seed_archives --only streameth
    python -m pipeline.seed_archives --only devcon --max-pages 200

StreamETH: its public video sitemaps list ~20k talks hosted on YouTube (/watch/yt-<id>) with the
           organiser as <video:uploader>. One request per sitemap file, no page fetches.
Devcon:    archive.devcon.org's sitemap lists every talk page; each page embeds the talk record
           (event, track, type, expertise, tags, speakers, youtubeId). ~2.5k pages at 1 req/s.

Rows are merged into data/raw/seeds.jsonl (keyed by video_id, Devcon records win), so this can run
before or after `seed_conferences`. A seed alone never puts a video in the catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

from .common import CACHE, RAW, _session, read_jsonl, write_jsonl

YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_last: dict[str, float] = {}


def get_text(url: str, min_interval: float = 1.0, cache: bool = True) -> str | None:
    key = hashlib.sha1(url.encode()).hexdigest()
    path = CACHE / "text" / key[:2] / f"{key}.txt"
    if cache and path.exists():
        return path.read_text()
    host = url.split("/")[2]
    for attempt in range(4):
        wait = _last.get(host, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.time()
        try:
            r = _session.get(url, timeout=60)
        except Exception as e:  # network blip
            print(f"  {url}: {type(e).__name__}, retrying")
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(float(r.headers.get("Retry-After", 0) or 0) or 5 * 2 ** attempt)
            continue
        if r.status_code != 200:
            return None
        if cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(r.text)
        return r.text
    return None


def _locs(xml: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", xml)


# --- StreamETH ------------------------------------------------------------------------------
def streameth() -> list[dict]:
    robots = get_text("https://streameth.org/robots.txt") or ""
    maps = [m for m in re.findall(r"Sitemap:\s*(\S+)", robots) if "/watch/sitemap/" in m]
    rows = []
    for m in maps:
        xml = get_text(m) or ""
        for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
            loc = re.search(r"<loc>https://streameth\.org/watch/yt-([A-Za-z0-9_-]{11})</loc>", block)
            if not loc:
                continue
            title = re.search(r"<video:title>(.*?)</video:title>", block, re.S)
            up = re.search(r'<video:uploader info="([^"]*)">(.*?)</video:uploader>', block, re.S)
            rows.append({
                "video_id": loc.group(1),
                "title": _unxml(title.group(1)) if title else None,
                "published_at": None,
                "seed": f"StreamETH · {_unxml(up.group(2))}" if up else "StreamETH",
                "seed_channel": up.group(1) if up else "https://streameth.org",
                "seed_source": "streameth",
                "seed_url": f"https://streameth.org/watch/yt-{loc.group(1)}",
            })
        print(f"  {m}: {len(rows)} YouTube-backed talks so far")
    return rows


def _unxml(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'").strip())


# --- Devcon Archive -------------------------------------------------------------------------
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


def _rsc_text(html: str) -> str:
    out = []
    for s in _PUSH.findall(html):
        try:
            out.append(json.loads(s))
        except json.JSONDecodeError:
            pass
    return "".join(out)


def _ms_to_iso(ms) -> str | None:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ms) / 1000))
    except (TypeError, ValueError):
        return None


def devcon_talk(url: str) -> dict | None:
    html = get_text(url)
    if not html:
        return None
    slug = url.rstrip("/").split("/")[-1]
    text = _rsc_text(html)
    i = text.find('"video":{"id":"' + slug + '"')
    if i < 0:
        return None
    try:
        v, _ = json.JSONDecoder().raw_decode(text, i + len('"video":'))
    except json.JSONDecodeError:
        return None
    yt = v.get("sources_youtubeId") or v.get("youtubeId") or ""
    if not YT_ID.match(yt):
        return None
    return {
        "video_id": yt,
        "title": v.get("title"),
        "published_at": _ms_to_iso(v.get("slot_start")),
        "duration_s": int(v["duration"]) if str(v.get("duration") or "").isdigit() else None,
        "seed": f"Devcon Archive · {v.get('eventId')}",
        "seed_channel": "https://archive.devcon.org",
        "seed_source": "devcon",
        "seed_url": url,
        "event": v.get("eventId"),
        "track": v.get("track"),
        "talk_type": v.get("type"),
        "expertise": v.get("expertise"),
        "tags": v.get("tags") or [],
        "speakers": [s.get("name") for s in v.get("speakers") or [] if isinstance(s, dict)],
        "abstract": (v.get("description") or "")[:1500],
    }


def devcon(max_pages: int) -> list[dict]:
    xml = get_text("https://archive.devcon.org/sitemap.xml") or ""
    urls = [u for u in _locs(xml) if re.match(r"https://archive\.devcon\.org/(devcon|devconnect)[^/]*/[^/]+/?$", u)
            and "/test-" not in u]
    print(f"  devcon sitemap: {len(urls)} talk pages")
    rows = []
    for n, u in enumerate(urls[:max_pages] if max_pages else urls, 1):
        r = devcon_talk(u)
        if r:
            rows.append(r)
        if n % 100 == 0:
            print(f"  devcon: {n} pages, {len(rows)} talks with a YouTube id")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["streameth", "devcon"])
    ap.add_argument("--max-pages", type=int, default=0, help="devcon: stop after N talk pages")
    args = ap.parse_args()
    path = RAW / "seeds.jsonl"
    merged = {r["video_id"]: r for r in read_jsonl(path)}
    new = []
    if args.only in (None, "streameth"):
        new += streameth()
    if args.only in (None, "devcon"):
        new += devcon(args.max_pages)
    for r in new:
        old = merged.get(r["video_id"])
        if old is None or r.get("seed_source") == "devcon":
            merged[r["video_id"]] = {**(old or {}), **r}
    n = write_jsonl(path, merged.values())
    print(f"seeds.jsonl: {n} distinct seed videos ({len(new)} rows this run)")


if __name__ == "__main__":
    main()
