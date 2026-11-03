"""Fetch YouTube metadata for every extracted video id.

    YOUTUBE_API_KEY=... python -m pipeline.enrich
Writes data/videos_meta.jsonl. Already-fetched ids are skipped (and the HTTP cache makes reruns cheap).
"""
from __future__ import annotations

from .common import DATA, read_jsonl, write_jsonl
from .youtube import videos


def main() -> None:
    ids = [x for x in (DATA / "video_ids.txt").read_text().split() if x]
    have = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    # Rows from meta_fallback are placeholders: always replace them with real metadata.
    todo = [i for i in ids if i not in have or have[i].get("meta_source") == "fallback"]
    print(f"{len(ids)} ids, {len(todo)} to fetch (~{len(todo) // 50 + 1} quota units)")
    meta = videos(todo)
    for vid, m in meta.items():
        have[vid] = {"video_id": vid, **m}
    gone = [i for i in todo if i not in meta]
    for i in gone:
        if have.get(i, {}).get("meta_source") == "fallback":
            del have[i]
    print(f"fetched {len(meta)}; {len(gone)} are deleted, private or invalid")
    write_jsonl(DATA / "videos_meta.jsonl", have.values())


if __name__ == "__main__":
    main()
