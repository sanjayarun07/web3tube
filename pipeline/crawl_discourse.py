"""Crawl public Discourse forums (Ethereum Research, Ethereum Magicians) into raw post rows.

Two modes:
  posts  (default) walks /posts.json?before=<id>, 50 posts with cooked HTML per request.
                   Roughly 1 request per 50 posts, so a whole forum takes minutes, not hours.
  topics           walks /latest.json then /t/<id>.json. Slower; use if /posts.json is disabled.

Output: data/raw/discourse_<host>.jsonl, one normalized post per line. Re-running resumes.

    python -m pipeline.crawl_discourse --forum ethresear.ch --forum ethereum-magicians.org
"""
from __future__ import annotations

import argparse

from .common import RAW, append_jsonl, get_json, read_jsonl
from .config import DISCOURSE_FORUMS

DEFAULT_FORUMS = list(DISCOURSE_FORUMS)


def _categories(base: str) -> dict[int, str]:
    site = get_json(f"{base}/site.json") or {}
    cats = {c["id"]: c["name"] for c in site.get("categories", [])}
    return cats


def _likes(p: dict) -> int:
    if "like_count" in p:
        return int(p["like_count"] or 0)
    for a in p.get("actions_summary") or []:
        if a.get("id") == 2:
            return int(a.get("count") or 0)
    return int(p.get("reaction_users_count") or 0)


def normalize(host: str, p: dict, cats: dict[int, str], topic: dict | None = None) -> dict:
    topic = topic or {}
    tid = p.get("topic_id") or topic.get("id")
    slug = p.get("topic_slug") or topic.get("slug") or "-"
    return {
        "source": "discourse",
        "forum": host,
        "post_id": p["id"],
        "topic_id": tid,
        "topic_title": p.get("topic_title") or topic.get("title") or "",
        "category": cats.get(p.get("category_id") or topic.get("category_id"), ""),
        "post_number": p.get("post_number"),
        "reply_to": p.get("reply_to_post_number"),
        "author": p.get("username"),
        "author_trust": p.get("trust_level"),
        "author_is_staff": bool(p.get("staff") or p.get("admin") or p.get("moderator")),
        "created_at": p.get("created_at"),
        "likes": _likes(p),
        "reads": p.get("reads"),
        "cooked": p.get("cooked") or "",
        "url": f"https://{host}/t/{slug}/{tid}/{p.get('post_number') or 1}",
    }


def crawl_posts(host: str, max_requests: int, out) -> int:
    base = f"https://{host}"
    cats = _categories(base)
    seen = {r["post_id"] for r in read_jsonl(out)}
    before = min(seen) if seen else None
    n = 0
    for i in range(max_requests):
        params = {"before": before} if before else None
        # Never cache the newest page, it moves; older pages are stable.
        body = get_json(f"{base}/posts.json", params=params, cache=before is not None)
        posts = (body or {}).get("latest_posts") or []
        posts = [p for p in posts if p["id"] not in seen]
        if not posts:
            break
        for p in posts:
            if p.get("hidden") or p.get("deleted_at") or p.get("post_type", 1) != 1:
                continue
            append_jsonl(out, normalize(host, p, cats))
            seen.add(p["id"])
            n += 1
        before = min(p["id"] for p in posts)
        if i % 20 == 0:
            print(f"  {host}: {len(seen)} posts so far (before={before})")
    return n


def crawl_topics(host: str, max_topics: int, out) -> int:
    base = f"https://{host}"
    cats = _categories(base)
    done_topics = {r["topic_id"] for r in read_jsonl(out)}
    n, page, topics_seen = 0, 0, 0
    while topics_seen < max_topics:
        body = get_json(f"{base}/latest.json", params={"order": "created", "page": page})
        topics = (body or {}).get("topic_list", {}).get("topics", [])
        if not topics:
            break
        for t in topics:
            topics_seen += 1
            if t["id"] in done_topics:
                continue
            full = get_json(f"{base}/t/{t['id']}.json")
            if not full:
                continue
            stream = full.get("post_stream", {})
            posts = list(stream.get("posts", []))
            have = {p["id"] for p in posts}
            missing = [pid for pid in stream.get("stream", []) if pid not in have]
            for k in range(0, len(missing), 20):
                chunk = missing[k:k + 20]
                extra = get_json(f"{base}/t/{t['id']}/posts.json",
                                 params=[("post_ids[]", x) for x in chunk])
                posts += (extra or {}).get("post_stream", {}).get("posts", [])
            for p in posts:
                append_jsonl(out, normalize(host, p, cats, full))
                n += 1
            done_topics.add(t["id"])
        page += 1
        print(f"  {host}: page {page}, {n} new posts")
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forum", action="append", help="Discourse host, repeatable")
    ap.add_argument("--mode", choices=["posts", "topics"], default="posts")
    ap.add_argument("--max-requests", type=int, default=5000, help="posts mode: pages of 50")
    ap.add_argument("--max-topics", type=int, default=50000, help="topics mode")
    args = ap.parse_args()
    for host in args.forum or DEFAULT_FORUMS:
        out = RAW / f"discourse_{host}.jsonl"
        print(f"Crawling {host} ({args.mode}) -> {out}")
        try:
            n = (crawl_posts(host, args.max_requests, out) if args.mode == "posts"
                 else crawl_topics(host, args.max_topics, out))
        except Exception as e:  # one forum being down or blocking us should not stop the rest
            print(f"  {host}: failed ({type(e).__name__}: {e}); try --mode topics or skip it")
            continue
        print(f"  {host}: {n} new posts written")


if __name__ == "__main__":
    main()
