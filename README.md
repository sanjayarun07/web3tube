# Web3Tube

**The videos builders keep recommending.** A HackerTube-style catalog of crypto videos, ranked by
what protocol developers and researchers have actually recommended in years of public discussion,
not by views, follower counts or engagement.

Every video shows *why* it is in the catalog: the original posts, who wrote them, which community,
when it was last endorsed, any criticism, and a per-signal score breakdown.

**Live:** https://web3tube.pages.dev · **How the ranking works:** https://web3tube.pages.dev/how-it-works.html ([source](web/how-it-works.html))

Sources: 29 Discourse forums across Ethereum, Bitcoin, Zcash, Cardano, Polkadot, Cosmos, NEAR, DFINITY,
Solana, Sui and L2s, plus Hacker News, with conference channels (Devcon, ETHGlobal, Solana, Polkadot,
zkSummit) as seeds. Claude Haiku labels every mention, tags each video's stance (critiques get their own
shelf) and topics; `pipeline/config.py` holds every weight and filter.

Quick start: `cp .env.example .env`, fill in the keys, `source .env`, then
`make extract enrich classify score stance retopic score serve` (all steps resume). `make deploy`
publishes `web/` to Cloudflare Pages; see [DEPLOY.md](DEPLOY.md).

## How it works

```
Discourse forums (13) ─┐
Hacker News (Algolia) ─┤                        YouTube Data API
Reddit, GitHub issues ─┼─► extract YouTube ids ─► metadata (no downloads) ─► Claude labels each ─► score ─► web/catalog.json
Devcon / ETHGlobal  ───┘   + surrounding text                                mention + video        │
(channel uploads as seeds)  + direct replies                                                        ▼
                                                                                 static site, no login, localStorage
```

| Step | Command | Output |
|---|---|---|
| Crawl forums | `make crawl` (or `make research` for just ethresear.ch + Magicians) | `data/raw/*.jsonl` |
| Reddit, GitHub | `make social` (GitHub needs `GITHUB_TOKEN`) | `data/raw/reddit.jsonl`, `github.jsonl` |
| Conference seeds | `make seed` (Devcon Archive + StreamETH, no key); `make seed-channels` (YouTube channels, needs key) | `data/raw/seeds.jsonl` |
| Extract links | `make extract` | `data/mentions.jsonl`, `data/video_ids.txt` |
| Metadata | `make enrich` | `data/videos_meta.jsonl` |
| Classify | `make classify-sample`, then `make classify` | `data/labels.jsonl` |
| Score | `make score` | `web/catalog.json`, `data/scored.jsonl` |
| View | `make serve` → http://localhost:8000 | |

Every step is resumable and HTTP responses are cached in `data/http_cache/`, so reruns are cheap.

### Classification
One Claude call per video sees the video's metadata plus all its mentions and labels each mention
`recommendation`, `neutral_reference`, `criticism`, `promotion` or `unrelated` (with a verbatim
evidence quote and a self-promotion flag), and judges the video: topics, technical depth, audience
(researchers / builders / general / traders), shill risk, and whether it is still current.
`python -m pipeline.classify --heuristic` is a free keyword fallback so you can see the whole
pipeline run before spending anything; its labels are much worse and the site marks them.

### Scoring (`pipeline/score.py`, knobs in `pipeline/config.py`)
| Signal | Weight | Computed from |
|---|---|---|
| Independent credible recommendations | 30% | one vote per author, weighted by forum trust level, community weight and label strength |
| Technical depth | 25% | Claude's judgement of the video |
| Discussion sentiment | 15% | recommendation vs criticism strength |
| Recommended across years | 15% | distinct years with endorsements |
| Captions and still current | 10% | captions available + "still current" judgement (proxy; transcripts are not fetched) |
| Engagement | 5% | likes on the recommending posts, log-scaled; YouTube views are never used |

Anti-shilling: same author counts once; self-promotion is down-weighted to 25%; promotional mentions
subtract; diminishing returns per community and a 60% cap on any one community's share; bursts of
3+ low-trust accounts posting the same link within 3 days collapse to one; sponsor/referral language
in the description and Claude's shill-risk score cut the score; market/trading content is kept in a
separate, labelled "Markets" feed. All weights are starting guesses to tune against real data.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
export YOUTUBE_API_KEY=...        # Google Cloud console → enable "YouTube Data API v3" → Credentials → API key
export ANTHROPIC_API_KEY=...      # or `ant auth login`
make test                         # 10 offline tests
make research seed extract enrich classify-sample score serve
```

**Model and cost.** Classification defaults to `claude-opus-5-5` at low effort. Rough cost is
~3k input + ~0.6k output tokens per video: about $0.025/video on Opus 5.5 (≈$125 for 5,000 videos),
or well under $1 for 5,000 videos on Haiku 5.5 (`W3T_MODEL=claude-haiku-5-5`). Run
`make classify-sample` (20 videos) and look at `data/labels.jsonl` before the full run.
**YouTube quota:** `enrich` uses 1 unit per 50 videos; the daily free quota is 10,000 units.

## Hosting
`web/` is plain static files (`index.html`, `app.js`, `style.css`, `catalog.json`). Any static host
works: a VPS with Caddy (`caddy file-server --root web --domain web3tube.example`), Cloudflare Pages,
Netlify or GitHub Pages.

## Network hosts the pipeline needs
ethresear.ch, ethereum-magicians.org and the other forums in `pipeline/config.py`
(note **governance.aave.com**, where gov.aave.com redirects), **hn.algolia.com**, **www.reddit.com**,
**api.github.com**, **www.googleapis.com** (YouTube Data API) and api.anthropic.com. Browsers load
thumbnails from i.ytimg.com and the player from www.youtube-nocookie.com.

## Rights and limits
Only metadata, YouTube's own thumbnails and the official embed are used. No video, audio or
transcript is downloaded. Forum quotes are short excerpts linked back to the source post.
Respect each site's terms and rate limits (defaults: 1 request/second per host, 2s for Reddit).

## Not in this MVP
Farcaster (needs a Neynar key) and X (paid API); Postgres + pgvector (JSONL is enough at this scale);
transcript-based fact checking; daily incremental updates.
