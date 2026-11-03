# Running Web3Tube on your Mac

The forum crawl and conference seeding already ran in the cloud. `web3tube-crawl.zip` contains the
code plus that data (`data/raw/`, `data/mentions.jsonl`, `data/video_ids.txt`), so your Mac only needs to run the steps that
use your keys. Everything is resumable, so rerunning a step never repeats finished work.

## 1. Unpack and install (once)

```bash
cd ~/Downloads                     # wherever you saved web3tube-crawl.zip
unzip web3tube-crawl.zip -d web3tube && cd web3tube
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make test                          # should print "10 passed"
```

Python 3.10 or newer is needed (`python3 --version`). If it is older: `brew install python`.

## 2. Add your keys (in this terminal only, never in the chat)

```bash
export YOUTUBE_API_KEY=...         # Google Cloud console > enable "YouTube Data API v3" > Credentials > API key
export ANTHROPIC_API_KEY=...       # console.anthropic.com > API keys
export W3T_MODEL=claude-haiku-5-5  # optional: much cheaper than the default Opus 5.5
```

## 3. Run the keyed steps

```bash
make extract          # rebuilds the video list from the crawled posts (free, seconds)
make enrich           # YouTube metadata, a few hundred quota units of your 10,000/day
make classify-sample  # labels the 20 most-mentioned videos; check data/labels.jsonl looks right
make classify         # all mentioned videos (~$0.025 each on Opus 5.5, far less on Haiku)
make score            # writes web/catalog.json
make serve            # open http://localhost:8000
```

## 4. Optional: sources the cloud could not reach

Your Mac has normal internet access, so these work there:

```bash
make crawl            # all 13 Discourse forums + Hacker News (resumes ethresear.ch / Magicians)
make social           # Reddit, and GitHub issues if you `export GITHUB_TOKEN=...`
make extract enrich classify score
```

## Sharing the result

`web/` is plain static files. Drag it onto Netlify Drop or Cloudflare Pages, or push it to GitHub Pages.
