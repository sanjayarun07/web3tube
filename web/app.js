"use strict";
// Web3Tube frontend. No accounts: saved/watched/topic interests live in this browser's localStorage.

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const SIGNAL_NAMES = {
  credible_recs: "Independent credible recommendations", technical_depth: "Technical depth",
  discussion_quality: "Discussion sentiment", longevity: "Recommended across years",
  captions_quality: "Captions and still current", engagement: "Engagement on recommending posts",
};
const FLAG_TEXT = {
  sponsor_markers: ["Sponsor or referral language in description", "bad"],
  shill_risk: ["Possible promotional content", "bad"], promoted: ["Someone promoted this in a forum", "warn"],
  coordinated_reposts_collapsed: ["Coordinated reposts were collapsed", "warn"],
  outdated: ["Likely outdated", "warn"], partly_outdated: ["Partly outdated", "warn"],
};

let CAT = null, VIDEOS = [], BY_ID = new Map();
const ui = { chip: "foryou", q: "", longs: false, hideOutdated: true, sort: "score" };

// ---------- local state ----------
const store = (() => {
  let s = { saved: [], watched: {}, aff: {} };
  try { s = { ...s, ...JSON.parse(localStorage.getItem("w3t") || "{}") }; } catch (_) {}
  const save = () => { try { localStorage.setItem("w3t", JSON.stringify(s)); } catch (_) {} };
  return {
    get: () => s,
    toggleSave(id) { s.saved = s.saved.includes(id) ? s.saved.filter(x => x !== id) : [id, ...s.saved]; save(); },
    isSaved: id => s.saved.includes(id),
    setWatched(id, on) { if (on) s.watched[id] = Date.now(); else delete s.watched[id]; save(); },
    isWatched: id => !!s.watched[id],
    bump(v, by) { for (const t of v.topics || []) s.aff[t] = Math.max(0, (s.aff[t] || 0) + by); save(); },
  };
})();

// ---------- helpers ----------
const fmtDur = s => { if (!s) return ""; const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`; };
const FORUMS = {
  "ethresear.ch": "Ethereum Research", "ethereum-magicians.org": "Ethereum Magicians",
  "research.lido.fi": "Lido Research", "gov.uniswap.org": "Uniswap Governance", "governance.aave.com": "Aave Governance",
  "forum.arbitrum.foundation": "Arbitrum DAO Forum", "research.arbitrum.io": "Arbitrum Research",
  "gov.optimism.io": "Optimism Governance", "forum.makerdao.com": "MakerDAO Forum", "forum.celestia.org": "Celestia Forum",
  "forum.celo.org": "Celo Forum", "discuss.ens.domains": "ENS Forum", "forum.cosmos.network": "Cosmos Forum",
  "forum.polkadot.network": "Polkadot Forum", "delvingbitcoin.org": "Delving Bitcoin", "forum.solana.com": "Solana Forum",
  "forum.zcashcommunity.com": "Zcash Community Forum", "research.anoma.net": "Anoma Research", "forum.aztec.network": "Aztec Forum",
  "community.starknet.io": "Starknet Community", "forums.sui.io": "Sui Forum", "forum.aptosfoundation.org": "Aptos Forum",
  "gov.near.org": "NEAR Governance", "forum.polygon.technology": "Polygon Forum", "forum.zknation.io": "ZKsync Forum",
  "forum.scroll.io": "Scroll Forum", "forum.cardano.org": "Cardano Forum", "forum.dfinity.org": "DFINITY Forum",
  "forum.eigenlayer.xyz": "EigenLayer Forum", "forum.osmosis.zone": "Osmosis Forum", "forum.stacks.org": "Stacks Forum",
  "news.ycombinator.com": "Hacker News", "reddit.com": "Reddit", "github.com": "GitHub",
};
const forumName = f => FORUMS[f] || f;
// hq2.jpg is YouTube's auto-generated frame from the middle of the video, not the uploader's thumbnail.
const thumb = id => `https://i.ytimg.com/vi/${id}/hq2.jpg`;
// Preview mode (e.g. hosted where YouTube images and embeds are blocked): text tiles and link-outs.
const PREVIEW = !!window.W3T_PREVIEW;
const ytUrl = id => `https://www.youtube.com/watch?v=${id}`;
const tile = v => `<div class="tile"><span>${esc((v.topics || [])[0] || "Video")}</span></div>`;
const nav = (url) => { try { history.pushState(null, "", url); } catch (e) { /* sandboxed frame */ } };
const isCritique = v => v.stance === "critique";
const isMarkets = v => !isCritique(v) && (v.aud === "traders" || (v.topics || []).includes("Markets & trading"));

// Markets and critiques live in their own shelves; critiques still show up in search.
function visible(list) {
  return list.filter(v => (!ui.longs || v.dur >= 2400) &&
    (!ui.hideOutdated || v.cur !== "outdated") && !(ui.chip !== "markets" && isMarkets(v)) &&
    !(ui.chip !== "critiques" && !ui.q && isCritique(v)));
}
function sorted(list) {
  const k = { score: v => -v.score, voices: v => -(v.n.voices), recent: v => -(Date.parse(v.last || 0)), new: v => -(Date.parse(v.pub || 0)) }[ui.sort];
  return [...list].sort((a, b) => k(a) - k(b));
}
function forYou(list) {
  const aff = store.get().aff, total = Object.values(aff).reduce((a, b) => a + b, 0) || 1;
  return list.filter(v => !store.isWatched(v.id))
    .map(v => ({ v, r: v.score * (1 + 1.5 * (v.topics || []).reduce((a, t) => a + (aff[t] || 0), 0) / total) }))
    .sort((a, b) => b.r - a.r).map(x => x.v);
}
function search(q) {
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  return VIDEOS.map(v => {
    const hay = [v.t, v.ch, v.sum, ...(v.topics || []), ...(v.ev || []).map(e => e.quote + " " + e.topic)].join(" ").toLowerCase();
    const title = (v.t || "").toLowerCase();
    let hit = 0;
    for (const t of terms) { if (!hay.includes(t)) return null; hit += title.includes(t) ? 3 : 1; }
    return { v, r: hit * (0.5 + v.score) };
  }).filter(Boolean).sort((a, b) => b.r - a.r).map(x => x.v);
}

// ---------- rendering ----------
function card(v) {
  const n = v.n, since = v.first ? v.first.slice(0, 4) : "";
  const pills = [`<span class="pill good">${n.voices} ${n.voices === 1 ? "voice" : "voices"}</span>`];
  if (n.communities > 1) pills.push(`<span class="pill">${n.communities} communities</span>`);
  if (since && v.last && v.last.slice(0, 4) !== since) pills.push(`<span class="pill">${since}–${v.last.slice(0, 4)}</span>`);
  if (v.seed) pills.push(`<span class="pill">${esc(v.seed)}</span>`);
  if (n.crit) pills.push(`<span class="pill warn">${n.crit} critical</span>`);
  return `<button class="card" data-id="${v.id}">
    <div class="thumb">${PREVIEW ? tile(v) : `<img loading="lazy" src="${thumb(v.id)}" alt="" data-fallback="https://i.ytimg.com/vi/${v.id}/hqdefault.jpg">`}
      <span class="dur">${fmtDur(v.dur)}</span>${store.isWatched(v.id) ? '<span class="seen"></span>' : ""}</div>
    <h3>${esc(v.t)}</h3><div class="ch">${esc(v.ch)}${v.pub ? " · " + v.pub.slice(0, 4) : ""}</div>
    <div class="proof">${pills.join("")}</div></button>`;
}
const shelf = (title, sub, list, n = 8) => list.length ? `<section class="shelf"><h2>${esc(title)}</h2>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}<div class="grid">${list.slice(0, n).map(card).join("")}</div></section>` : "";

function renderChips() {
  const counts = {};
  for (const v of VIDEOS) for (const t of v.topics || []) counts[t] = (counts[t] || 0) + 1;
  const topics = Object.entries(counts).filter(([t]) => t !== "Markets & trading").sort((a, b) => b[1] - a[1]).slice(0, 12).map(x => x[0]);
  const chips = [["foryou", "For you"], ["all", "All"], ...topics.map(t => ["t:" + t, t]), ["critiques", "Critiques & skeptics"], ["markets", "Markets (labelled)"]];
  $("#chips").innerHTML = chips.map(([k, l]) => `<button class="chip" role="tab" data-chip="${esc(k)}" aria-selected="${ui.chip === k}">${esc(l)}</button>`).join("");
}

function render() {
  const main = $("#main"), hash = location.hash;
  if (!CAT) return;
  if (hash === "#about") return renderAbout();
  if (!VIDEOS.length) return renderEmpty();
  renderChips();
  if (hash === "#saved") {
    const list = store.get().saved.map(id => BY_ID.get(id)).filter(Boolean);
    main.innerHTML = list.length ? shelf("Saved", "Kept in this browser only.", list, 999) : `<div class="empty">Nothing saved yet. Open a video and press Save.</div>`;
    return;
  }
  if (ui.q) {
    const list = visible(search(ui.q));
    main.innerHTML = list.length ? shelf(`Results for “${ui.q}”`, `${list.length} videos`, list, 120) : `<div class="empty">No recommended videos match “${esc(ui.q)}”.</div>`;
    return;
  }
  const base = visible(VIDEOS);
  if (ui.chip === "foryou") {
    const hasHistory = Object.keys(store.get().aff).length > 0;
    const top = (hasHistory ? forYou(base) : sorted(base)).slice(0, 12), shown = new Set(top.map(v => v.id));
    const rest = base.filter(v => !shown.has(v.id));
    let html = shelf(hasHistory ? "Picked for you" : "Most recommended by builders",
      hasHistory ? "Ranked by evidence, tilted toward topics you watch. Your history never leaves this browser." :
        "Ranked by independent recommendations from developer and research communities.", top, 12);
    const topicCounts = {};
    for (const v of rest) for (const t of v.topics || []) topicCounts[t] = (topicCounts[t] || 0) + 1;
    for (const [t] of Object.entries(topicCounts).sort((a, b) => b[1] - a[1]).slice(0, 6))
      html += shelf(t, "", sorted(rest.filter(v => v.topics.includes(t))), 4);
    html += shelf("Conference talks people keep citing", "Talks from Devcon, ETHGlobal, Solana, Polkadot and zkSummit channels that also earned recommendations in discussions.", sorted(rest.filter(v => v.seed)), 8);
    main.innerHTML = html;
  } else if (ui.chip === "critiques") {
    main.innerHTML = shelf("Critiques & skeptics", "Well-recommended videos arguing against crypto or the industry. Kept apart from the builder shelves.", sorted(base.filter(isCritique)), 120);
  } else if (ui.chip === "markets") {
    main.innerHTML = shelf("Markets & trading", "Kept separate on purpose and held to stricter promotion labels.", sorted(base.filter(isMarkets)), 120);
  } else if (ui.chip === "all") {
    main.innerHTML = shelf("All recommended videos", `${base.length} videos`, sorted(base), 2000);
  } else {
    const t = ui.chip.slice(2);
    main.innerHTML = shelf(t, "", sorted(base.filter(v => v.topics.includes(t))), 2000);
  }
}

function renderEmpty() {
  $("#chips").innerHTML = "";
  $("#main").innerHTML = `<div class="empty"><h2>No catalog yet</h2>
    <p>This site reads <code>catalog.json</code>, which the pipeline writes after crawling the forums. Run <code>make all</code> in the project, then reload.</p></div>`;
}

function renderAbout() {
  const w = CAT.weights || {}, s = CAT.stats || {};
  $("#chips").innerHTML = "";
  $("#main").innerHTML = `<article class="about"><h2>How Web3Tube picks videos</h2>
  <p>Crypto YouTube is full of paid promotions, price predictions and referral farming. Web3Tube ignores views and follower counts. Instead it mines years of discussion where protocol developers and researchers linked videos, and asks: who recommended this, how independently, for how long, and did anyone push back?</p>
  <p>Every link is extracted from the original post. Claude reads each mention with its context and labels it as a <b>recommendation</b>, a <b>neutral reference</b>, <b>criticism</b> or <b>promotion</b>. Votes count once per person, are weighted by forum trust level, get diminishing returns within a single community, and bursts of new accounts pushing the same link collapse to one.</p>
  <table>${Object.entries(w).map(([k, v]) => `<tr><td>${esc(SIGNAL_NAMES[k] || k)}</td><td>${Math.round(v * 100)}%</td></tr>`).join("")}</table>
  <p style="color:var(--muted);font-size:13px">These are starting weights, not validated ones. Each video page shows its own breakdown and the posts behind it.</p>
  <p>Sources in this build: ${(s.communities || []).map(forumName).map(esc).join(", ") || "none yet"}. ${s.mentions ?? 0} mentions of ${s.videos_mentioned ?? 0} videos, ${s.catalog ?? 0} made the catalog.</p>
  <p>Videos play through YouTube's privacy-enhanced embed. Thumbnails are YouTube's mid-video frame rather than the uploader's thumbnail. Nothing is downloaded, and there are no accounts: what you save or watch stays in this browser.</p></article>`;
}

// ---------- player ----------
function openVideo(id, push = true) {
  const v = BY_ID.get(id);
  if (!v) return;
  if (push && !PREVIEW) nav("#v=" + id);
  const dlg = $("#player");
  $(".embed").hidden = PREVIEW;
  if (!PREVIEW) $("#frame").src = `https://www.youtube-nocookie.com/embed/${id}?rel=0&modestbranding=1&autoplay=1`;
  $("#plTitle").textContent = v.t;
  $("#plMeta").textContent = [v.ch, v.pub, fmtDur(v.dur), (v.topics || []).join(" · ")].filter(Boolean).join("  ·  ");
  $("#plSum").textContent = v.sum || "";
  $("#plFlags").innerHTML = (v.flags || []).filter(f => FLAG_TEXT[f]).map(f => `<span class="flag ${FLAG_TEXT[f][1]}">${FLAG_TEXT[f][0]}</span>`).join("") +
    (v.sponsor?.length ? `<span class="flag bad">Matched: ${esc(v.sponsor.join(", "))}</span>` : "") +
    (v.labeller === "heuristic" ? `<span class="flag warn">Labels from keyword fallback, not Claude</span>` : "");
  const n = v.n;
  $("#whyLine").innerHTML = `<b>${n.rec}</b> independent ${n.rec === 1 ? "recommendation" : "recommendations"}${n.ref ? `, ${n.ref} neutral ${n.ref === 1 ? "citation" : "citations"}` : ""}${n.crit ? `, <span style="color:var(--bad)">${n.crit} critical</span>` : ""} across ${n.communities} ${n.communities === 1 ? "community" : "communities"}${v.last ? `. Last endorsed ${v.last}` : ""}.`;
  $("#evidence").innerHTML = (v.ev || []).map(e => `<li><div class="head"><span class="lab ${e.label}">${e.label.replace("_", " ")}</span>
      <b>${esc(e.author)}</b><span>${esc(forumName(e.forum))}</span><span>${e.date}</span>${e.self_promo ? '<span class="lab promotion">own video</span>' : ""}${e.kind === "reply" ? "<span>reply</span>" : ""}</div>
      ${e.quote ? `<blockquote>“${esc(e.quote)}”</blockquote>` : ""}<a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.topic || "Open discussion")} ↗</a></li>`).join("");
  $("#signals").innerHTML = Object.entries(v.sig || {}).map(([k, s]) => `<div class="sig"><div class="row"><span>${SIGNAL_NAMES[k] || k}</span><span>${Math.round(s * 100)}</span></div>
      <div class="track"><div class="fill" style="width:${Math.round(s * 100)}%"></div></div></div>`).join("") +
    `<div class="sig"><div class="row"><b>Overall</b><b>${Math.round(v.score * 100)}</b></div></div>`;
  const rel = VIDEOS.filter(x => x.id !== id && x.topics.some(t => v.topics.includes(t)) && !isMarkets(x) === !isMarkets(v) && !isCritique(x) === !isCritique(v)).slice(0, 5);
  $("#related").innerHTML = rel.map(card).join("");
  $("#related").previousElementSibling.hidden = !rel.length;
  const syncBtns = () => {
    $("#saveBtn").textContent = store.isSaved(id) ? "Saved" : "Save";
    $("#saveBtn").classList.toggle("on", store.isSaved(id));
    $("#watchedBtn").textContent = store.isWatched(id) ? "Watched" : "Mark watched";
    $("#watchedBtn").classList.toggle("on", store.isWatched(id));
  };
  $("#saveBtn").onclick = () => { if (!store.isSaved(id)) store.bump(v, 2); store.toggleSave(id); syncBtns(); };
  $("#watchedBtn").onclick = () => { const on = !store.isWatched(id); store.setWatched(id, on); if (on) store.bump(v, 1); syncBtns(); };
  $("#ytLink").href = ytUrl(id);
  $("#ytLink").textContent = PREVIEW ? "Watch on YouTube ↗" : "Open on YouTube";
  $("#ytLink").classList.toggle("ghost", !PREVIEW);
  syncBtns();
  store.bump(v, 1);
  if (!dlg.open) dlg.showModal();
  dlg.scrollTop = 0;
}
function closeVideo(push = true) {
  const dlg = $("#player");
  $("#frame").src = "about:blank";
  if (dlg.open) dlg.close();
  if (push && location.hash.startsWith("#v=")) nav(location.pathname + location.search);
  render();
}

// ---------- wiring ----------
document.addEventListener("click", e => {
  const c = e.target.closest(".card");
  if (c) { e.preventDefault(); openVideo(c.dataset.id); return; }
  const chip = e.target.closest(".chip");
  if (chip) { ui.chip = chip.dataset.chip; ui.q = ""; $("#q").value = ""; if (location.hash) nav(location.pathname); render(); window.scrollTo(0, 0); }
});
$("#home").onclick = e => { e.preventDefault(); ui.chip = "foryou"; ui.q = ""; $("#q").value = ""; nav(location.pathname); render(); };
$("#closePlayer").onclick = () => closeVideo();
$("#player").addEventListener("cancel", e => { e.preventDefault(); closeVideo(); });
$("#player").addEventListener("click", e => { if (e.target.id === "player") closeVideo(); });
let qt; $("#q").addEventListener("input", e => { clearTimeout(qt); qt = setTimeout(() => { ui.q = e.target.value.trim(); if (location.hash && !location.hash.startsWith("#v=")) nav(location.pathname); render(); }, 120); });
$("#longs").onchange = e => { ui.longs = e.target.checked; render(); };
$("#hideOutdated").onchange = e => { ui.hideOutdated = e.target.checked; render(); };
$("#sort").onchange = e => { ui.sort = e.target.value; render(); };
window.addEventListener("popstate", route);
window.addEventListener("hashchange", route);
function route() {
  const m = location.hash.match(/^#v=([\w-]{11})/);
  if (m) openVideo(m[1], false); else { if ($("#player").open) closeVideo(false); render(); }
}

// Thumbnail fallback without inline handlers (the deployed CSP blocks them).
document.addEventListener("error", e => {
  const img = e.target;
  if (img.tagName === "IMG" && img.dataset.fallback) { img.src = img.dataset.fallback; delete img.dataset.fallback; }
}, true);

fetch("catalog.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null).catch(() => null).then(cat => {
  CAT = cat || { videos: [], stats: {}, weights: {} };
  VIDEOS = CAT.videos || [];
  BY_ID = new Map(VIDEOS.map(v => [v.id, v]));
  const s = CAT.stats || {};
  $("#foot").innerHTML = VIDEOS.length ? `${VIDEOS.length} ${VIDEOS.length === 1 ? "video" : "videos"} from ${s.mentions ?? "?"} mentions across ${(s.communities || []).length} communities · built ${esc((CAT.generated || "").slice(0, 10))} · <a href="https://claude.ai/artifact/83V4mKtQPN3xYngTuybyVA?open_in_browser=1" target="_blank" rel="noopener">How it works</a>` : "";
  route();
});
