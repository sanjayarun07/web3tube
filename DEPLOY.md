# Deploying Web3Tube

`web/` is a static site: `index.html`, `app.js`, `style.css`, `catalog.json`, plus `_headers`
(security headers and caching for Cloudflare Pages), `favicon.svg` and `robots.txt`. No build step.

## Cloudflare Pages (configured)

Live URL: https://web3tube.pages.dev (project `web3tube`, production branch `main`).

```bash
npx wrangler login     # once, opens a browser to sign in to Cloudflare
make score             # writes web/catalog.json
make deploy            # checks catalog size, then: npx wrangler pages deploy web --project-name web3tube --branch main
```

Recent wrangler versions try to send new Pages projects to Cloudflare Workers instead. The project was
created once with `npx wrangler pages project create web3tube --production-branch main --force`; deploys to
an existing project go straight to Pages and need no `--force`.

An earlier deploy also created a Worker at https://web3tube.web3tube.workers.dev. It still serves an
older copy; delete it from the dashboard (Workers & Pages > web3tube Worker) once it is no longer needed.

Add a custom domain under Workers & Pages > web3tube > Custom domains.

To update the live site after a new crawl: `make extract enrich classify score stance score deploy`.

## Notes
- Cloudflare Pages limits each file to 25 MiB; `make deploy` refuses a larger `catalog.json`.
- `_headers` sets a Content-Security-Policy that allows only YouTube thumbnails (`i.ytimg.com`) and
  privacy-mode embeds (`youtube-nocookie.com`). Add hosts there if the frontend starts loading others.
- Routing uses the URL hash (`#v=<id>`, `#about`), so no rewrite rules are needed.
- Other static hosts work too: Netlify Drop (drag `web/`), GitHub Pages, or `caddy file-server --root web`.
