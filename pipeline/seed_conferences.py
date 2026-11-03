"""Seed the corpus with conference talks (Devcon, ETHGlobal) from their YouTube channels.

    python -m pipeline.seed_conferences
Output: data/raw/seeds.jsonl
"""
from __future__ import annotations

from .common import RAW, read_jsonl, write_jsonl
from .config import SEED_CHANNELS
from .youtube import channel_uploads


def main() -> None:
    rows = []
    for handle, label in SEED_CHANNELS.items():
        vids = channel_uploads(handle)
        print(f"  {handle}: {len(vids)} uploads")
        rows += [{**v, "seed": label, "seed_channel": handle} for v in vids]
    # Merge with seeds from other sources (seed_archives); archive records keep their richer fields.
    merged = {r["video_id"]: r for r in read_jsonl(RAW / "seeds.jsonl")}
    for r in rows:
        merged.setdefault(r["video_id"], {**r, "seed_source": "youtube_channel"})
    n = write_jsonl(RAW / "seeds.jsonl", merged.values())
    print(f"Wrote {n} seed videos")


if __name__ == "__main__":
    main()
