# Web3Tube pipeline. Every step is resumable; rerun any target after an interruption.
PY ?= python3

all: crawl seed extract enrich classify score

crawl:            ## Discourse forums (13 by default) + HN; add `make social` for Reddit/GitHub
	$(PY) -m pipeline.crawl_discourse
	$(PY) -m pipeline.crawl_social hn

social:
	$(PY) -m pipeline.crawl_social reddit
	$(PY) -m pipeline.crawl_social github

research:         ## fastest first run: just Ethereum Research + Ethereum Magicians
	$(PY) -m pipeline.crawl_discourse --forum ethresear.ch --forum ethereum-magicians.org

seed:             ## Devcon Archive + StreamETH talks (no key needed)
	$(PY) -m pipeline.seed_archives

seed-channels:    ## Devcon / ETHGlobal YouTube channel uploads (needs YOUTUBE_API_KEY)
	$(PY) -m pipeline.seed_conferences

extract:
	$(PY) -m pipeline.extract

enrich:           ## YouTube metadata (needs YOUTUBE_API_KEY)
	$(PY) -m pipeline.enrich

classify:         ## Claude labels (needs ANTHROPIC_API_KEY); try `make classify-sample` first
	$(PY) -m pipeline.classify

classify-sample:
	$(PY) -m pipeline.classify --limit 20

preview:          ## keyless metadata from archives + forum link text; `make enrich` replaces it
	$(PY) -m pipeline.meta_fallback

stance:           ## tags catalog videos constructive / critique / other (needs ANTHROPIC_API_KEY); then make score
	$(PY) -m pipeline.stance

retopic:          ## stricter topic re-tag of catalog videos (needs ANTHROPIC_API_KEY); then make score
	$(PY) -m pipeline.retopic

score:
	$(PY) -m pipeline.score

deploy:           ## Cloudflare Pages, https://web3tube.pages.dev (run `npx wrangler login` once first)
	@test -s web/catalog.json || (echo "web/catalog.json missing: run make score first" && exit 1)
	@$(PY) -c "import os,sys; n=os.path.getsize('web/catalog.json'); print(f'catalog.json {n/1e6:.1f} MB'); sys.exit(n > 25*1024*1024 and 'over the 25 MiB Pages file limit' or 0)"
	npx wrangler pages deploy web --project-name web3tube --branch main

serve:
	cd web && $(PY) -m http.server 8000

test:
	$(PY) -m pytest -q tests

.PHONY: retopic stance deploy preview all crawl social research seed seed-channels extract enrich classify classify-sample score serve test
