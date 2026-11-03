"""Re-tag catalog videos' topics with a stricter prompt than classify uses.

    python -m pipeline.retopic         (after `make score`; then `make score` again to apply)
Reads  web/catalog.json   Writes data/topics.jsonl (resumable: tagged videos are skipped)

classify picks topics while it is busy labelling mentions, and drifts (invented topics, "Ethereum
protocol" for any protocol). This pass sees only the video and the official list. score.py still runs
clean_topics() on the result. Spend is logged to data/usage.jsonl and capped by W3T_BUDGET_USD.
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel, Field

from .common import DATA, ROOT, append_jsonl, read_jsonl
from .config import TOPICS
from . import classify as K

OUT = DATA / "topics.jsonl"

SYSTEM = f"""You tag videos for Web3Tube, a catalog of crypto videos. Given one video's title, channel, \
description and summary, pick 1 to 3 topics, most specific first, from exactly this list:
{", ".join(TOPICS)}.
Rules:
- Use a chain's topic (Bitcoin, Solana, Cardano, Zcash, Polkadot & Substrate, Cosmos & IBC, Move chains) \
only when the video is about that chain.
- "Ethereum protocol" only for Ethereum's own protocol: EIPs, upgrades, clients, core dev calls, research.
- "AI x Crypto" only when both AI and crypto are central to the video.
- Community calls, AMAs and DAO meetings are Governance; podcasts about the industry are History & culture.
Never invent a topic outside the list."""


class Topics(BaseModel):
    topics: list[str] = Field(description="1-3 topics from the list, most specific first")


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
                                    output_config={"effort": "low"}, output_format=Topics,
                                    messages=[{"role": "user", "content": user}])
    pin, pout = K.PRICE.get(K.MODEL, K.PRICE["claude-opus-5-5"])
    usd = (resp.usage.input_tokens * pin + resp.usage.output_tokens * pout) / 1e6
    with K._lock:
        K._spent += usd
        append_jsonl(K.USAGE_LOG, {"model": K.MODEL, "step": "retopic", "input": resp.usage.input_tokens,
                                   "output": resp.usage.output_tokens, "usd": round(usd, 6)})
    out = resp.parsed_output
    if resp.stop_reason == "refusal" or out is None:
        raise RuntimeError("no answer")  # score keeps classify's topics for this video
    return {"video_id": v["id"], "topics": [t for t in out.topics if t in TOPICS][:3], "labeller": K.MODEL}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    catalog = json.loads((ROOT / "web" / "catalog.json").read_text())["videos"]
    meta = {r["video_id"]: r for r in read_jsonl(DATA / "videos_meta.jsonl")}
    done = {r["video_id"] for r in read_jsonl(OUT)} if OUT.exists() else set()
    todo = [{**v, "desc": meta.get(v["id"], {}).get("description")} for v in catalog if v["id"] not in done]
    print(f"{len(catalog)} catalog videos, {len(done)} re-tagged, {len(todo)} to go ({K.MODEL})")
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
    print(f"topics in {OUT}; total spend ${K.spent_usd():.2f}")
    if stopped:
        print(f"budget stop: {stopped}")


if __name__ == "__main__":
    main()
