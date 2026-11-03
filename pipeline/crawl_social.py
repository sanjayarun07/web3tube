"""Crawl Hacker News, Reddit and GitHub for YouTube links into the same post schema as Discourse.

    python -m pipeline.crawl_social hn        # hn.algolia.com, no key
    python -m pipeline.crawl_social reddit    # www.reddit.com public JSON, no key, slow (rate limited)
    GITHUB_TOKEN=... python -m pipeline.crawl_social github   # api.github.com issue search

Output: data/raw/hn.jsonl, data/raw/reddit.jsonl, data/raw/github.jsonl
"""
from __future__ import annotations

import argparse
import html
import os
from datetime import datetime, timezone

from .common import RAW, get_json, write_jsonl
from .config import GITHUB_ORGS, HN_TERMS, REDDIT_SUBS


def _row(**kw) -> dict:
    base = {"source": kw.pop("source"), "author_trust": None, "author_is_staff": False,
            "reads": None, "category": "", "reply_to": None}
    return {**base, **kw}


# ---------------------------------------------------------------- Hacker News
def crawl_hn(max_pages: int) -> list[dict]:
    rows: dict[str, dict] = {}
    api = "https://hn.algolia.com/api/v1/search_by_date"
    for term in HN_TERMS:
        for tags, field in (("comment", "comment_text"), ("story", "url")):
            for page in range(max_pages):
                body = get_json(api, params={"query": f"youtube {term}", "tags": tags,
                                             "hitsPerPage": 1000, "page": page}, min_interval=0.5) or {}
                hits = body.get("hits", [])
                for h in hits:
                    text = h.get(field) or ""
                    if tags == "story":
                        text = f'<a href="{html.escape(text)}">{html.escape(h.get("title") or "")}</a> {h.get("story_text") or ""}'
                    if "youtu" not in text:
                        continue
                    story = h.get("story_id") or h["objectID"]
                    rows[h["objectID"]] = _row(
                        source="hn", forum="news.ycombinator.com", post_id=int(h["objectID"]),
                        topic_id=int(story), topic_title=h.get("story_title") or h.get("title") or "",
                        post_number=int(h["objectID"]),
                        reply_to=int(h["parent_id"]) if h.get("parent_id") and h.get("parent_id") != story else None,
                        author=h.get("author"), created_at=h.get("created_at"),
                        likes=int(h.get("points") or 0), cooked=text,
                        url=f"https://news.ycombinator.com/item?id={h['objectID']}")
                if page + 1 >= body.get("nbPages", 0):
                    break
        print(f"  hn '{term}': {len(rows)} items so far")
    return list(rows.values())


# ---------------------------------------------------------------- Reddit
def crawl_reddit(max_pages: int) -> list[dict]:
    rows: dict[str, dict] = {}
    for sub in REDDIT_SUBS:
        after = None
        for _ in range(max_pages):
            params = {"q": "site:youtube.com OR site:youtu.be", "restrict_sr": 1, "sort": "top",
                      "t": "all", "limit": 100, "raw_json": 1}
            if after:
                params["after"] = after
            body = get_json(f"https://www.reddit.com/r/{sub}/search.json", params=params, min_interval=2.0) or {}
            data = body.get("data", {})
            for c in data.get("children", []):
                d = c["data"]
                if "youtu" not in (d.get("url") or "") + (d.get("selftext") or ""):
                    continue
                rows[d["id"]] = _row(
                    source="reddit", forum="reddit.com", category=f"r/{sub}", post_id=d["id"],
                    topic_id=d["id"], topic_title=d.get("title") or "", post_number=1,
                    author=d.get("author"),
                    created_at=datetime.fromtimestamp(d["created_utc"], timezone.utc).isoformat(),
                    likes=int(d.get("score") or 0),
                    cooked=f'<a href="{html.escape(d.get("url") or "")}">{html.escape(d.get("title") or "")}</a> '
                           f'{html.escape(d.get("selftext") or "")}',
                    url=f"https://www.reddit.com{d.get('permalink', '')}")
            after = data.get("after")
            if not after:
                break
        print(f"  r/{sub}: {len(rows)} posts so far")
    return list(rows.values())


# ---------------------------------------------------------------- GitHub
def crawl_github(max_pages: int) -> list[dict]:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Set GITHUB_TOKEN (any classic or fine-grained token with public read).")
    import requests
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.html+json"})
    rows: list[dict] = []
    for org in GITHUB_ORGS:
        for page in range(1, max_pages + 1):
            r = s.get("https://api.github.com/search/issues",
                      params={"q": f"org:{org} youtube in:body,comments", "per_page": 100, "page": page}, timeout=30)
            if r.status_code == 403:
                import time
                time.sleep(60)
                continue
            if r.status_code == 422:  # past the 1000-result window
                break
            r.raise_for_status()
            items = r.json().get("items", [])
            for it in items:
                repo = it["repository_url"].split("/repos/")[1]
                title = f"{repo}: {it['title']}"
                rows.append(_row(source="github", forum="github.com", category=repo, post_id=it["id"],
                                 topic_id=it["id"], topic_title=title, post_number=0,
                                 author=it["user"]["login"], created_at=it["created_at"],
                                 likes=int(it.get("reactions", {}).get("+1", 0)),
                                 cooked=it.get("body_html") or "", url=it["html_url"]))
                if it.get("comments"):
                    cr = s.get(it["comments_url"], params={"per_page": 100}, timeout=30)
                    for n, c in enumerate(cr.json() if cr.ok else [], 1):
                        rows.append(_row(source="github", forum="github.com", category=repo, post_id=c["id"],
                                         topic_id=it["id"], topic_title=title, post_number=n,
                                         author=c["user"]["login"], created_at=c["created_at"],
                                         likes=int(c.get("reactions", {}).get("+1", 0)),
                                         cooked=c.get("body_html") or "", url=c["html_url"]))
            if len(items) < 100:
                break
        print(f"  github {org}: {len(rows)} rows so far")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", choices=["hn", "reddit", "github"])
    ap.add_argument("--max-pages", type=int, default=10)
    args = ap.parse_args()
    fn = {"hn": crawl_hn, "reddit": crawl_reddit, "github": crawl_github}[args.source]
    rows = fn(args.max_pages)
    n = write_jsonl(RAW / f"{args.source}.jsonl", rows)
    print(f"wrote {n} rows to data/raw/{args.source}.jsonl")


if __name__ == "__main__":
    main()
