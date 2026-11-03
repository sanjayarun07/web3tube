"""Classify every mention (recommendation / neutral / criticism / promotion) and judge each video.

One Claude call per video: the call sees the video's metadata plus all of its mentions, so it
can tell a recommendation from a passing reference or a complaint, and spot self-promotion.

    python -m pipeline.classify                 # Claude (needs ANTHROPIC_API_KEY or `ant auth login`)
    python -m pipeline.classify --heuristic     # keyword fallback, free, much worse
    W3T_MODEL=claude-haiku-5-5 python -m pipeline.classify   # cheaper bulk run

Writes data/labels.jsonl (resumable: videos already labelled are skipped).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from pydantic import BaseModel, Field

from .common import DATA, RAW, append_jsonl, read_jsonl
from .config import COMMUNITY_WEIGHT, SPONSOR_MARKERS, TOPICS

MODEL = os.environ.get("W3T_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("W3T_EFFORT", "low")
CHUNK = 25

Label = Literal["recommendation", "neutral_reference", "criticism", "promotion", "unrelated"]


class MentionLabel(BaseModel):
    mention_index: int
    label: Label
    strength: float = Field(description="0-1, how strongly the author endorses (or criticises) the video")
    self_promotion: bool = Field(description="author appears to be the speaker/uploader promoting their own video")
    evidence: str = Field(description="verbatim excerpt, max ~200 chars, from the mention text that justifies the label; empty if none")


class VideoJudgement(BaseModel):
    topics: list[str] = Field(description="1-3 topics from the allowed list")
    technical_depth: float = Field(description="0-1, 1 = deep technical/research content for builders")
    audience: Literal["researchers", "builders", "general", "traders"]
    shill_risk: float = Field(description="0-1, likelihood the video is token shilling, price talk or paid promotion")
    still_current: Literal["current", "partly_outdated", "outdated", "unknown"]
    summary: str = Field(description="one plain sentence on what the video teaches, max 160 chars")


class Result(BaseModel):
    video: VideoJudgement
    mentions: list[MentionLabel]


SYSTEM = f"""You label evidence for Web3Tube, a catalog of the YouTube videos that crypto builders \
and researchers keep recommending. You get one video's YouTube metadata and numbered mentions of it \
from developer and community forums across the whole crypto space (Ethereum, Bitcoin, Solana, \
Cosmos, Polkadot and others; also Hacker News, Reddit and GitHub). Each mention shows the author's own \
words with [VIDEO] where the link was, plus surrounding context.

For each mention choose exactly one label:
- recommendation: the author endorses the video as worth watching or uses it as a trusted source \
("great talk on X", "this explains it well", "see Vitalik's talk for the design rationale").
- neutral_reference: the video is cited or linked without a judgement (meeting recordings, "here is the call recording", lists).
- criticism: the author disputes the video, says it is wrong, misleading or outdated.
- promotion: marketing, shilling, the author advertising their own product/channel/event, or referral spam.
- unrelated: the link is incidental or the mention text says nothing about it.
Set self_promotion=true when the author appears to be the speaker or uploader. A reply mention \
(kind=reply) is someone responding to a post that contains the video: label what the reply says \
about the video, and use unrelated when it is about something else.

Judge the video from its metadata and the discussion. Topics must come from: {", ".join(TOPICS)}. \
Recordings of protocol calls (ACD, breakout rooms) are neutral references by default and have \
technical_depth around 0.5. Be calibrated and terse; quote evidence verbatim, never paraphrase."""


def _video_block(vid: str, meta: dict, seed: dict | None) -> str:
    m = meta or {}
    lines = [f"video_id: {vid}", f"title: {m.get('title', '(unknown, metadata missing)')}",
             f"channel: {m.get('channel', '')}", f"published: {m.get('published_at', '')}",
             f"duration_min: {round((m.get('duration_s') or 0) / 60)}",
             f"description: {(m.get('description') or '')[:1200]}"]
    if seed:
        lines.append(f"conference_seed: {seed['seed']}")
    return "\n".join(lines)


def _mention_block(i: int, m: dict) -> str:
    ctx = {"index": i, "kind": m["kind"], "forum": m["forum"], "topic": m["topic_title"],
           "category": m["category"], "author": m["author"], "date": (m["created_at"] or "")[:10],
           "text": m["text"]}
    if m.get("parent_text"):
        ctx["replying_to"] = m["parent_text"]
    if m.get("reply_texts"):
        ctx["replies_received"] = m["reply_texts"]
    return json.dumps(ctx, ensure_ascii=False)


_client = None
_lock = threading.Lock()
USAGE = {"input": 0, "output": 0}
# $ per million input/output tokens, for the budget guard. Unknown models count at Opus rates.
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
BUDGET = float(os.environ.get("W3T_BUDGET_USD", "0") or 0)  # 0 = no limit
USAGE_LOG = DATA / "usage.jsonl"


class BudgetExceeded(Exception):
    pass


def spent_usd() -> float:
    """Total spend recorded in data/usage.jsonl (every Claude call appends a row)."""
    return sum(r.get("usd", 0) for r in read_jsonl(USAGE_LOG)) if USAGE_LOG.exists() else 0.0


_spent = None


def classify_llm(vid: str, meta: dict, seed: dict | None, mentions: list[dict]) -> dict:
    import anthropic
    global _client
    with _lock:
        if _client is None:
            _client = anthropic.Anthropic(max_retries=6)
    global _spent
    video_judgement, labels = None, []
    for start in range(0, max(len(mentions), 1), CHUNK):
        with _lock:
            if _spent is None:
                _spent = spent_usd()
            if BUDGET and _spent >= BUDGET:
                raise BudgetExceeded(f"spent ${_spent:.2f} of ${BUDGET:.2f}")
        chunk = mentions[start:start + CHUNK]
        user = (_video_block(vid, meta, seed) + "\n\nMENTIONS (one JSON object per line):\n" +
                "\n".join(_mention_block(start + i, m) for i, m in enumerate(chunk)))
        resp = _client.messages.parse(
            model=MODEL, max_tokens=8000, system=SYSTEM,
            output_config={"effort": EFFORT}, output_format=Result,
            messages=[{"role": "user", "content": user}],
        )
        pin, pout = PRICE.get(MODEL, PRICE["claude-opus-5-5"])
        usd = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
        with _lock:
            USAGE["input"] += resp.usage.input_tokens
            USAGE["output"] += resp.usage.output_tokens
            _spent += usd
            append_jsonl(USAGE_LOG, {"model": MODEL, "input": resp.usage.input_tokens,
                                     "output": resp.usage.output_tokens, "usd": round(usd, 6)})
        if resp.stop_reason == "refusal" or resp.parsed_output is None:
            h = classify_heuristic(vid, meta, seed, chunk)
            for x in h["mentions"]:
                x["mention_index"] += start
            video_judgement = video_judgement or h["video"]
            labels += h["mentions"]
            continue
        out = resp.parsed_output
        video_judgement = video_judgement or out.video.model_dump()
        labels += [x.model_dump() for x in out.mentions]
    return {"video": video_judgement, "mentions": labels, "labeller": MODEL}


POS = re.compile(r"\b(great|excellent|awesome|fantastic|highly recommend|recommend|must[- ]watch|worth (?:a )?watch|"
                 r"best (?:talk|explanation|intro)|explains? (?:it|this) (?:well|nicely|clearly)|good (?:talk|video|intro|overview)|"
                 r"check out|watch this|helpful|insightful|brilliant|love(?:d)? this|nice talk|thanks for sharing)\b", re.I)
NEG = re.compile(r"\b(wrong|incorrect|misleading|outdated|disagree|flawed|not accurate|inaccurate|debunk|"
                 r"doesn't work|broken|confused|nonsense|bad take)\b", re.I)
NEUTRAL = re.compile(r"\b(recording|livestream|call #?\d+|meeting|agenda|notes|stream)\b", re.I)


def classify_heuristic(vid: str, meta: dict, seed: dict | None, mentions: list[dict]) -> dict:
    """Keyword fallback so the pipeline runs end to end without an LLM. Low accuracy by design."""
    labels = []
    for i, m in enumerate(mentions):
        t = m["text"]
        pos, neg = len(POS.findall(t)), len(NEG.findall(t))
        if any(s in t.lower() for s in SPONSOR_MARKERS):
            label, strength = "promotion", 0.6
        elif neg > pos:
            label, strength = "criticism", min(1, 0.4 + 0.2 * neg)
        elif pos:
            label, strength = "recommendation", min(1, 0.4 + 0.2 * pos)
        elif NEUTRAL.search(t) or m["kind"] == "post":
            label, strength = "neutral_reference", 0.2
        else:
            label, strength = "unrelated", 0.0
        ev = (POS.search(t) or NEG.search(t))
        evidence = t[max(0, ev.start() - 80): ev.end() + 80] if ev else ""
        labels.append({"mention_index": i, "label": label, "strength": strength,
                       "self_promotion": False, "evidence": evidence})
    title = (meta or {}).get("title", "") + " " + (meta or {}).get("description", "")[:500]
    lower = title.lower()
    topics = [t for t, kws in {
        "Zero-knowledge": ["zk", "zero knowledge", "snark", "stark", "plonk"],
        "Scaling & L2s": ["rollup", "layer 2", "l2", "scaling", "plasma"],
        "Consensus": ["consensus", "casper", "proof of stake", "beacon", "fork choice", "lmd"],
        "MEV": ["mev", "pbs", "builder", "searcher"],
        "Security & exploits": ["security", "exploit", "hack", "audit", "vulnerab"],
        "Cryptography": ["cryptograph", "bls", "kzg", "signature", "vdf", "fhe"],
        "Account abstraction": ["account abstraction", "4337", "smart account"],
        "EVM": ["evm", "opcode", "eof"],
        "DeFi mechanisms": ["defi", "amm", "uniswap", "lending", "stablecoin"],
        "Data availability": ["data availability", "danksharding", "4844", "blob"],
        "Governance": ["governance", "dao", "eip process"],
    }.items() if any(k in lower for k in kws)][:3] or ["Ethereum protocol"]
    shill = 0.8 if any(s in lower for s in SPONSOR_MARKERS) else 0.1
    depth = 0.7 if seed or any(k in lower for k in ["research", "deep dive", "protocol", "devcon", "workshop"]) else 0.45
    return {"video": {"topics": topics, "technical_depth": depth, "audience": "builders", "shill_risk": shill,
                      "still_current": "unknown", "summary": ""},
            "mentions": labels, "labeller": "heuristic"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--heuristic", action="store_true", help="keyword classifier, no API calls")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="only label N videos (for a cost check)")
    args = ap.parse_args()

    meta = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    seeds = {r["video_id"]: r for r in read_jsonl(RAW / "seeds.jsonl")}
    by_video = defaultdict(list)
    for m in read_jsonl(DATA / "mentions.jsonl"):
        by_video[m["video_id"]].append(m)
    out = DATA / "labels.jsonl"
    done = {r["video_id"] for r in read_jsonl(out)}
    # Only videos that are mentioned AND still exist on YouTube are worth paying to label.
    todo = [v for v in by_video if v not in done and (v in meta or not meta)]
    # Most-mentioned first; among equals, mentions that read like a recommendation and come from
    # higher-weight communities first, so a budget stop leaves the least promising videos unlabelled.
    def priority(v):
        ms = by_video[v]
        rec_like = any(POS.search((m.get("text") or "").lower()) for m in ms)
        comm = max(COMMUNITY_WEIGHT.get(m.get("forum"), 0.6) for m in ms)
        return (-len(ms), -rec_like, -comm)
    todo.sort(key=priority)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(by_video)} mentioned videos, {len(done)} labelled, {len(todo)} to go "
          f"({'heuristic' if args.heuristic else MODEL + ' effort=' + EFFORT})")

    def work(vid):
        ms = by_video[vid]
        fn = classify_heuristic if args.heuristic else classify_llm
        res = fn(vid, meta.get(vid), seeds.get(vid), ms)
        by_idx = {x["mention_index"]: x for x in res["mentions"]}
        return {"video_id": vid, "video": res["video"], "labeller": res["labeller"],
                "mentions": [{"id": m["id"], **{k: v for k, v in by_idx.get(i, {"label": "unrelated", "strength": 0,
                              "self_promotion": False, "evidence": ""}).items() if k != "mention_index"}}
                             for i, m in enumerate(ms)]}

    stopped = None
    with ThreadPoolExecutor(max_workers=1 if args.heuristic else args.workers) as pool:
        futs = {pool.submit(work, v): v for v in todo}
        for n, f in enumerate(as_completed(futs), 1):
            try:
                append_jsonl(out, f.result())
            except BudgetExceeded as e:
                stopped = str(e)
            except Exception as e:  # keep going; rerun picks up failures
                print(f"  {futs[f]}: {type(e).__name__}: {e}")
            if n % 50 == 0:
                print(f"  {n}/{len(todo)}  tokens in={USAGE['input']} out={USAGE['output']}")
    print(f"tokens: input={USAGE['input']} output={USAGE['output']}; total spend ${spent_usd():.2f}")
    if stopped:
        print(f"budget stop: {stopped}")
    print(f"labels in {out}")


if __name__ == "__main__":
    main()
