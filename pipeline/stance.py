"""Tag each catalog video's stance toward crypto, so critiques get their own shelf.

    python -m pipeline.stance          (after `make score`; then `make score` again to apply)
Reads  web/catalog.json   Writes data/stance.jsonl (resumable: tagged videos are skipped)

One small Claude call per video, on the video's own metadata and Claude's earlier summary. Spend is
logged to data/usage.jsonl and capped by W3T_BUDGET_USD, like classify.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal

from pydantic import BaseModel, Field

from .common import DATA, ROOT, append_jsonl, read_jsonl
from . import classify as K

OUT = DATA / "stance.jsonl"

SYSTEM = """You sort videos for Web3Tube, a catalog of crypto videos that builders and researchers recommend. \
Given one video's title, channel, description and summary, say what stance it takes toward crypto:
- constructive: teaches, builds on, researches or explains crypto technology (including security postmortems \
and critical analysis of one protocol's design).
- critique: argues that crypto, blockchains, NFTs or the industry as a whole are flawed, harmful or a scam; \
skeptic essays and exposes of the industry.
- other: news, interviews, community updates, or anything else.
Answer from the video's content, not from whether you agree with it."""


class Stance(BaseModel):
    stance: Literal["constructive", "critique", "other"]
    reason: str = Field(description="one short clause")


def tag(v: dict) -> dict:
    import anthropic
    with K._lock:
        if K._client is None:
            K._client = anthropic.Anthropic(max_retries=6)
        if K._spent is None:
            K._spent = K.spent_usd()
        if K.BUDGET and K._spent >= K.BUDGET:
            raise K.BudgetExceeded(f"spent ${K._spent:.2f} of ${K.BUDGET:.2f}")
    user = json.dumps({"title": v.get("t"), "channel": v.get("ch"), "summary": v.get("sum"),
                       "description": (v.get("desc") or "")[:600]}, ensure_ascii=False)
    resp = K._client.messages.parse(model=K.MODEL, max_tokens=2000, system=SYSTEM,
                                    output_config={"effort": "low"}, output_format=Stance,
                                    messages=[{"role": "user", "content": user}])
    pin, pout = K.PRICE.get(K.MODEL, K.PRICE["claude-opus-5-5"])
    usd = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
    with K._lock:
        K._spent += usd
        append_jsonl(K.USAGE_LOG, {"model": K.MODEL, "step": "stance", "input": resp.usage.input_tokens,
                                   "output": resp.usage.output_tokens, "usd": round(usd, 6)})
    out = resp.parsed_output
    if resp.stop_reason == "refusal" or out is None:
        return {"video_id": v["id"], "stance": "other", "reason": "no answer", "labeller": K.MODEL}
    return {"video_id": v["id"], "stance": out.stance, "reason": out.reason, "labeller": K.MODEL}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    catalog = json.loads((ROOT / "web" / "catalog.json").read_text())["videos"]
    meta = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    done = {r["video_id"] for r in read_jsonl(OUT)} if OUT.exists() else set()
    todo = [{**v, "desc": meta.get(v["id"], {}).get("description")} for v in catalog if v["id"] not in done]
    print(f"{len(catalog)} catalog videos, {len(done)} tagged, {len(todo)} to go ({K.MODEL})")
    stopped = None
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(tag, v): v["id"] for v in todo}
        for f in as_completed(futs):
            try:
                append_jsonl(OUT, f.result())
            except K.BudgetExceeded as e:
                stopped = str(e)
            except Exception as e:  # keep going; rerun picks up failures
                print(f"  {futs[f]}: {type(e).__name__}: {e}")
    print(f"stances in {OUT}; total spend ${K.spent_usd():.2f}")
    if stopped:
        print(f"budget stop: {stopped}")


if __name__ == "__main__":
    main()
