"""Score labelled videos and write the static catalog the frontend reads.

    python -m pipeline.score
Reads  data/mentions.jsonl, data/labels.jsonl, data/videos_meta.jsonl, data/raw/seeds.jsonl
Writes web/catalog.json  (and data/scored.jsonl with every signal, for debugging the ranking)
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .common import DATA, RAW, ROOT, read_jsonl, write_jsonl
from . import config as C

LABEL_WEIGHT = {"recommendation": 1.0, "neutral_reference": 0.35, "criticism": 0.0,
                "promotion": 0.0, "unrelated": 0.0}
TRUST_CRED = {0: 0.3, 1: 0.5, 2: 0.75, 3: 0.9, 4: 1.0}
CURRENT = {"current": 1.0, "partly_outdated": 0.6, "outdated": 0.2, "unknown": 0.5}


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def author_credibility(m: dict, activity: Counter) -> float:
    """Credibility from forum trust level and how established the author is across the corpus.

    Deliberately ignores follower counts and video views."""
    t = m.get("author_trust")
    base = TRUST_CRED.get(t, 0.6) if t is not None else 0.6
    if m.get("author_is_staff"):
        base = min(1.0, base + 0.1)
    established = min(1.0, math.log1p(activity[(m["forum"], m["author"])]) / math.log1p(50))
    return round(0.7 * base + 0.3 * established, 3)


def collapse_bursts(recs: list[dict]) -> tuple[list[dict], int]:
    """Coordinated pushes: >= N low-trust accounts recommending the same video within a few days
    collapse to a single mention."""
    low = sorted([r for r in recs if (r.get("author_trust") or 0) <= 1 and r["source"] == "discourse"
                  or r["source"] == "reddit"], key=lambda r: r["_dt"] or datetime.min.replace(tzinfo=timezone.utc))
    drop: set[str] = set()
    for i, r in enumerate(low):
        if r["id"] in drop or not r["_dt"]:
            continue
        window = [x for x in low[i:] if x["_dt"] and (x["_dt"] - r["_dt"]).days <= C.BURST_WINDOW_DAYS]
        if len({x["author"] for x in window}) >= C.BURST_MIN_ACCOUNTS:
            drop |= {x["id"] for x in window[1:]}
    return [r for r in recs if r["id"] not in drop], len(drop)


_RELEVANT = re.compile(r"\b(?:(?:" + "|".join(re.escape(t) for t in C.RELEVANCE_TERMS) + r")(?:e?s)?\b|(?:"
                       + "|".join(re.escape(t) for t in C.RELEVANCE_NAMES) + r")\b|(?:"
                       + "|".join(re.escape(t) for t in C.RELEVANCE_PREFIXES) + r"))", re.I)


def is_relevant(meta: dict, lab: dict) -> bool:
    """Crypto-relevance check on the video's title, channel, description and Claude's summary."""
    text = " ".join([meta.get("title") or "", meta.get("channel") or "", meta.get("description") or "",
                     lab["video"].get("summary") or ""])
    return bool(_RELEVANT.search(text))


_CHAIN = {t: re.compile(rx, re.I) for t, rx in C.CHAIN_TOPICS.items()}
_ETH = re.compile(C.ETHEREUM_SIGNAL, re.I)
_REQUIRES = {t: re.compile(rx, re.I) for t, rx in C.TOPIC_REQUIRES.items()}
_CANON = {t.lower(): t for t in C.TOPICS} | {k: v for k, v in C.TOPIC_ALIASES.items()}


def clean_topics(topics: list[str], text: str, forums: set[str]) -> list[str]:
    """Map Claude's topics onto the official list and fix chain tags from what the video names."""
    out = []
    for t in topics:
        t = _CANON.get(t.strip().lower())
        if t and t not in out:
            out.append(t)
    for t, rx in _CHAIN.items():
        named = bool(rx.search(text))
        if named and t not in out:
            out.append(t)
        elif not named and t in out:
            out.remove(t)
    for t, rx in _REQUIRES.items():
        if t in out and not rx.search(text):
            out.remove(t)
    if "Ethereum protocol" in out and not _ETH.search(text + " " + " ".join(forums)):
        out.remove("Ethereum protocol")
    return out or [t for t in (_CANON.get(x.strip().lower()) for x in topics) if t][:1] or ["History & culture"]


def sat(x: float, k: float) -> float:
    """Diminishing returns: 0 -> 0, k -> 0.63, 3k -> 0.95."""
    return 1 - math.exp(-x / k)


def score_video(vid: str, ms: list[dict], lab: dict, meta: dict, seed: dict | None, activity: Counter,
                topics: list[str] | None = None) -> dict:
    v = lab["video"]
    by_id = {x["id"]: x for x in lab["mentions"]}
    rows = []
    for m in ms:
        L = by_id.get(m["id"], {"label": "unrelated", "strength": 0, "self_promotion": False, "evidence": ""})
        rows.append({**m, **L, "_dt": _dt(m["created_at"]), "cred": author_credibility(m, activity)})

    endorsing = [r for r in rows if LABEL_WEIGHT[r["label"]] > 0]
    endorsing, collapsed = collapse_bursts(endorsing)

    # Independence: one vote per author per video (their strongest), weighted by credibility.
    best: dict[tuple, dict] = {}
    for r in endorsing:
        k = (r["forum"], r["author"])
        w = LABEL_WEIGHT[r["label"]] * max(0.3, min(1.0, r["strength"])) * r["cred"]
        w *= C.COMMUNITY_WEIGHT.get(r["forum"], 0.6)
        if r["self_promotion"]:
            w *= C.SELF_PROMO_WEIGHT
        if k not in best or w > best[k]["_w"]:
            best[k] = {**r, "_w": w}
    per_comm = defaultdict(float)
    for r in best.values():
        per_comm[r["forum"]] += r["_w"]
    # Per-community diminishing returns, so one forum cannot carry a video on its own.
    total = sum(per_comm.values())
    if len(per_comm) > 1:
        per_comm = {c: min(w, max(C.MAX_COMMUNITY_SHARE * total, 0.5)) for c, w in per_comm.items()}
    raw_rec = sum(sat(w, 1.5) * 1.5 for w in per_comm.values())

    promos = {(r["forum"], r["author"]) for r in rows if r["label"] == "promotion"}
    raw_rec = max(0.0, raw_rec - C.PROMOTION_PENALTY * len(promos))

    recs = [r for r in best.values() if r["label"] == "recommendation"]
    crits = {(r["forum"], r["author"]): r for r in rows if r["label"] == "criticism"}
    R = sum(r["strength"] * r["cred"] for r in recs)
    Cr = sum(r["strength"] * r["cred"] for r in crits.values())
    years = {r["_dt"].year for r in best.values() if r["_dt"]}
    likes = sum(r.get("likes") or 0 for r in best.values())

    signals = {
        "credible_recs": round(sat(raw_rec, 1.2), 3),
        "technical_depth": round(min(1, max(0, v["technical_depth"])), 3),
        "discussion_quality": round(0.5 + 0.5 * (R - Cr) / (R + Cr + 0.5), 3),
        "longevity": round(min(1.0, len(years) / 4), 3),
        "captions_quality": round(0.5 * bool(meta.get("captions")) + 0.5 * CURRENT[v["still_current"]], 3),
        "engagement": round(min(1.0, math.log1p(likes) / math.log1p(100)), 3),
    }
    score = sum(C.WEIGHTS[k] * s for k, s in signals.items())

    text = f"{meta.get('title', '')} {meta.get('description', '')}".lower()
    sponsor_hits = sorted({s for s in C.SPONSOR_MARKERS if s in text})
    flags = []
    if sponsor_hits:
        flags.append("sponsor_markers")
        score *= 0.8
    if v["shill_risk"] >= 0.5:
        flags.append("shill_risk")
    score *= 1 - 0.7 * v["shill_risk"]
    if promos:
        flags.append("promoted")
    if collapsed:
        flags.append("coordinated_reposts_collapsed")
    if v["still_current"] in ("outdated", "partly_outdated"):
        flags.append(v["still_current"])
    if seed:
        score += 0.03

    dated = [r for r in recs if r["_dt"]]
    last = max((r["_dt"] for r in dated), default=None)
    first = min((r["_dt"] for r in dated), default=None)

    # Evidence shown under "why recommended": strongest independent voices first, then criticism.
    ev_rows = sorted(best.values(), key=lambda r: (r["label"] != "recommendation", -r["_w"]))[:8]
    ev_rows += sorted(crits.values(), key=lambda r: -r["strength"])[:3]
    evidence = [{
        "label": r["label"], "forum": r["forum"], "author": r["author"],
        "date": (r["created_at"] or "")[:10], "topic": r["topic_title"][:140], "url": r["url"],
        "quote": (r.get("evidence") or r["text"])[:240], "self_promo": r["self_promotion"],
        "kind": r["kind"],
    } for r in ev_rows]

    return {
        "id": vid, "t": meta.get("title"), "ch": meta.get("channel"), "pub": (meta.get("published_at") or "")[:10],
        "dur": meta.get("duration_s") or 0, "aud": v["audience"],
        "topics": clean_topics(topics or v["topics"], " ".join([meta.get("title") or "", meta.get("channel") or "",
                                                              v.get("summary") or ""]), {r["forum"] for r in rows}),
        "sum": v["summary"], "cur": v["still_current"], "cap": bool(meta.get("captions")),
        "seed": seed["seed"] if seed else None,
        "score": round(score, 4), "sig": signals, "flags": flags, "sponsor": sponsor_hits,
        "n": {"rec": len(recs), "ref": sum(r["label"] == "neutral_reference" for r in best.values()),
              "crit": len(crits), "promo": len(promos), "voices": len(best), "communities": len(per_comm)},
        "first": first.date().isoformat() if first else None,
        "last": last.date().isoformat() if last else None,
        "years": sorted(years), "ev": evidence, "labeller": lab.get("labeller"),
    }


def main() -> None:
    meta = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    seeds = {r["video_id"]: r for r in read_jsonl(RAW / "seeds.jsonl")}
    labels = {r["video_id"]: r for r in read_jsonl(DATA / "labels.jsonl")}
    stance_file = DATA / "stance.jsonl"  # from `python -m pipeline.stance`; optional
    stances = {r["video_id"]: r["stance"] for r in read_jsonl(stance_file)} if stance_file.exists() else {}
    topics_file = DATA / "topics.jsonl"  # stricter re-tag from `python -m pipeline.retopic`; optional
    retopic = {r["video_id"]: r["topics"] for r in read_jsonl(topics_file)} if topics_file.exists() else {}
    mentions = list(read_jsonl(DATA / "mentions.jsonl"))
    activity = Counter((m["forum"], m["author"]) for m in mentions)
    by_video = defaultdict(list)
    for m in mentions:
        by_video[m["video_id"]].append(m)

    scored, skipped = [], Counter()
    for vid, ms in by_video.items():
        m = meta.get(vid)
        if not m:
            skipped["no_metadata (deleted/private)"] += 1
            continue
        if not m.get("embeddable", True) or m.get("privacy") not in (None, "public"):
            skipped["not_embeddable_or_private"] += 1
            continue
        if vid not in labels:
            skipped["unlabelled"] += 1
            continue
        if not is_relevant(m, labels[vid]):
            skipped["off_topic"] += 1
            continue
        scored.append({**score_video(vid, ms, labels[vid], m, seeds.get(vid), activity, retopic.get(vid)),
                       "stance": stances.get(vid)})
    write_jsonl(DATA / "scored.jsonl", scored)

    catalog = []
    for s in scored:
        if s["n"]["rec"] + s["n"]["ref"] < C.MIN_RECOMMENDERS or s["n"]["rec"] == 0 and s["n"]["ref"] < 3:
            skipped["too_few_independent_voices"] += 1
        elif s["score"] < C.MIN_SCORE:
            skipped["below_min_score"] += 1
        else:
            catalog.append(s)
    catalog.sort(key=lambda s: -s["score"])

    import json
    import os
    out = Path(os.environ.get("W3T_CATALOG", ROOT / "web" / "catalog.json"))
    out.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weights": C.WEIGHTS, "topics": C.TOPICS,
        "stats": {"mentions": len(mentions), "videos_mentioned": len(by_video), "catalog": len(catalog),
                  "communities": sorted({m["forum"] for m in mentions}), "skipped": dict(skipped)},
        "videos": catalog,
    }, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(catalog)} videos in catalog -> {out}; skipped {dict(skipped)}")


if __name__ == "__main__":
    main()
