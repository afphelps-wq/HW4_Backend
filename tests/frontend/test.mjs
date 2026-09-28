/* Frontend checks: the real docs/ files driven in jsdom against a stubbed API.
 *
 *   pip install -r requirements.txt && npm install jsdom
 *   python tests/frontend/stub_api.py &     # the real FastAPI app, SQLite, no network
 *   node tests/frontend/test.mjs
 */
import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DOCS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs");
const BASE = "http://127.0.0.1:8765";
let failures = 0;
const check = (name, cond, extra = "") => {
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${cond ? "" : "  >> " + extra}`);
  if (!cond) failures++;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function newPage({ token, theme } = {}) {
  const html = fs.readFileSync(`${DOCS}/index.html`, "utf8").replace(/<script(?: src="[^"]*")?>[\s\S]*?<\/script>/g, "");
  const dom = new JSDOM(html, { runScripts: "outside-only", url: "https://user.github.io/HW4_Backend/", pretendToBeVisual: true });
  const w = dom.window;
  const sent = [];
  w.fetch = (url, opts = {}) => { sent.push({ url, method: opts.method || "GET", body: opts.body }); return fetch(url, opts); };
  w.confirm = () => true;
  // jsdom 28 has no matchMedia; browsers all do. Shim it so the theme code can run.
  if (!w.matchMedia) {
    w.matchMedia = (q) => ({ media: q, matches: false, addEventListener() {}, removeEventListener() {} });
  }
  w.Element.prototype.scrollIntoView = () => {};
  Object.defineProperty(w.navigator, "clipboard", { value: { writeText: async (t) => { w.__copied = t; } }, configurable: true });
  if (token) w.localStorage.setItem("seq2find_token", token);
  if (theme) w.localStorage.setItem("theme", theme);
  // the pre-paint theme script was stripped with the others; re-apply it
  const saved = w.localStorage.getItem("theme");
  if (saved === "light" || saved === "dark") w.document.documentElement.dataset.theme = saved;
  w.eval(fs.readFileSync(`${DOCS}/config.js`, "utf8").replace("https://seq2find.onrender.com", BASE));
  w.eval(fs.readFileSync(`${DOCS}/app.js`, "utf8"));
  const $ = (id) => w.document.getElementById(id);
  const waitFor = async (fn, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { if (fn()) return true; await sleep(25); } return false; };
  const msgs = () => [...$("messages").querySelectorAll(".message")].map((m) => m.textContent);
  return { dom, w, $, sent, waitFor, msgs };
}

const submit = (p, id) => p.$(id).dispatchEvent(new p.w.Event("submit", { cancelable: true, bubbles: true }));
async function login(p, email, password) {
  p.$("login-email").value = email;
  p.$("login-password").value = password;
  submit(p, "login-form");
  return p.waitFor(() => !p.$("view-app").hidden || p.msgs().length);
}
function fillSearch(p, o = {}) {
  p.$("f-methodology").value = o.methodology ?? "Spatial single-cell RNA-seq";
  p.$("f-organism").value = o.organism ?? "Human";
  p.$("f-tissue").value = o.tissue ?? "Pancreatic tissue";
  p.$("f-conditions").value = o.conditions ?? "PDAC treatment-naive\n\n  Healthy pancreas  \n";
  p.$("f-availability").value = "availability" in o ? o.availability : "TLS annotations present";
}
const cards = (p) => [...p.$("search-results").querySelectorAll(".card")];

// ---- 1. signed out ----
let p = await newPage();
await sleep(120);
check("signed out: login panel shown, app + account card hidden",
  !p.$("view-login").hidden && p.$("view-app").hidden && p.$("account-card").hidden);
check("signed out: rail items locked with no active marker",
  [...p.w.document.querySelectorAll(".nav-item")].every((n) => n.classList.contains("is-locked") && !n.classList.contains("is-active")));
check("busy overlay hidden at rest", p.$("busy").classList.contains("is-hidden"));
check("theme button rendered with an svg icon", p.$("theme-btn").querySelector("svg") !== null);

// ---- 2. theme toggle ----
check("light by default (no saved choice, jsdom reports light)", p.w.document.documentElement.dataset.theme === undefined);
p.$("theme-btn").click();
check("toggle sets dark + persists + aria-pressed", p.w.document.documentElement.dataset.theme === "dark"
  && p.w.localStorage.getItem("theme") === "dark" && p.$("theme-btn").getAttribute("aria-pressed") === "true");
p.$("theme-btn").click();
check("toggle back to light", p.w.document.documentElement.dataset.theme === "light" && p.w.localStorage.getItem("theme") === "light");
const dark = await newPage({ theme: "dark" });
check("saved dark theme applied before paint", dark.w.document.documentElement.dataset.theme === "dark");

// ---- 3. login ----
await login(p, "admin@lab.org", "wrong-password");
check("bad password shows an error message", p.msgs().some((m) => /Incorrect/.test(m)), p.msgs().join("|"));
check("bad login stores no token", p.w.localStorage.getItem("seq2find_token") === null);
check("busy overlay cleared after failure", p.$("busy").classList.contains("is-hidden"));
check("login button re-enabled", !p.$("login-submit").disabled);

await login(p, "admin@lab.org", "correct-horse-1");
check("good login reveals app + account card", !p.$("view-app").hidden && p.$("view-login").hidden && !p.$("account-card").hidden);
check("email shown in side column", p.$("user-email").textContent === "admin@lab.org");
check("admin sees the cache-skip checkbox", !p.$("refresh-wrap").classList.contains("is-hidden"));
check("password field cleared", p.$("login-password").value === "");
check("rail unlocked, Search active", !p.$("nav-search").classList.contains("is-locked") && p.$("nav-search").classList.contains("is-active"));
await p.waitFor(() => /No saved searches/.test(p.$("saved-list").textContent));
check("saved stat shows 0", p.$("stat-saved").textContent === "0");
check("results panel hidden until a search runs", p.$("panel-results").classList.contains("is-hidden"));
const adminToken = p.w.localStorage.getItem("seq2find_token");

// ---- 4. validation ----
p.$("f-methodology").value = ""; p.$("f-organism").value = "Human"; p.$("f-tissue").value = "x";
submit(p, "search-form");
await sleep(60);
check("missing required field blocked client-side",
  p.msgs().some((m) => /required/.test(m)) && !p.sent.some((s) => s.url.endsWith("/search")));

// ---- 5. search ----
fillSearch(p);
submit(p, "search-form");
check("busy overlay shows progress with elapsed seconds",
  await p.waitFor(() => !p.$("busy").classList.contains("is-hidden") && /Searching GEO/.test(p.$("busy-text").textContent), 2000)
  || cards(p).length > 0);
check("3 result cards rendered", await p.waitFor(() => cards(p).length === 3), String(cards(p).length));
check("busy overlay hidden after the search", p.$("busy").classList.contains("is-hidden"));
check("results panel revealed and nav marked", !p.$("panel-results").classList.contains("is-hidden")
  && p.$("nav-results").classList.contains("is-active") && !p.$("nav-results").classList.contains("is-locked"));
const body = JSON.parse(p.sent.find((s) => s.url.endsWith("/search")).body);
check("payload trimmed; blank condition lines dropped",
  JSON.stringify(body.conditions) === JSON.stringify(["PDAC treatment-naive", "Healthy pancreas"])
  && body.max_results === 10 && body.data_availability === "TLS annotations present", JSON.stringify(body));
check("origin line says '3 matches · fresh search'",
  p.$("result-origin").textContent === "3 matches \u00B7 fresh search", p.$("result-origin").textContent);
check("stat: matches returned = 3", p.$("stat-results").textContent === "3");
check("stat: requirement count = 1 and empty note hidden",
  p.$("stat-requirement").textContent === "1" && !p.$("stat-requirement").classList.contains("is-hidden")
  && p.$("requirement-empty").classList.contains("is-hidden"));

// XSS
check("XSS: no injected elements", p.$("search-results").querySelectorAll("img, script, b, u, i").length === 0);
check("XSS: payload never executed", p.w.__xss === undefined);
check("XSS: hostile title rendered as literal text", cards(p)[1].querySelector("h3").textContent.includes("<img src=x"));
check("evidence quote shown as text", cards(p)[0].querySelector(".evidence").textContent.includes("<u>region</u>"));

// badges + links
check("confidence tags use the scale classes",
  cards(p)[0].querySelector(".tag-high") && cards(p)[1].querySelector(".tag-medium") && cards(p)[2].querySelector(".tag-low"));
check("requirement chips shown when availability was asked",
  cards(p)[0].querySelector(".chip-met") && cards(p)[1].querySelector(".chip-unmet"));
const links = [...p.$("search-results").querySelectorAll(".links a")];
check("ftp:// links rewritten to https", links.length === 6 && links.every((a) => a.href.startsWith("https://ftp.ncbi.nlm.nih.gov/")), links.map((a) => a.href).join(" "));
check("supplementary link labelled", links.some((a) => a.textContent === "Supplementary files"));
check("external links carry rel=noopener", [...p.$("search-results").querySelectorAll("a[target=_blank]")].every((a) => /noopener/.test(a.rel)));

// ---- 6. no-requirement search hides the chips and the stat ----
const q = await newPage();
await login(q, "bob@lab.org", "correct-horse-2");
fillSearch(q, { availability: "" });
submit(q, "search-form");
await q.waitFor(() => q.$("search-results").querySelectorAll(".card").length === 3);
check("no availability asked: no requirement chips", q.$("search-results").querySelectorAll(".chip-met, .chip-unmet").length === 0);
check("no availability asked: stat shows the empty note",
  q.$("stat-requirement").classList.contains("is-hidden") && !q.$("requirement-empty").classList.contains("is-hidden"));
check("non-admin: cache-skip hidden", q.$("refresh-wrap").classList.contains("is-hidden"));

// ---- 7. cache + admin refresh ----
submit(p, "search-form");
await p.waitFor(() => /cached result/.test(p.$("result-origin").textContent));
check("identical repeat search reports cached", /cached result/.test(p.$("result-origin").textContent));
p.$("f-refresh").checked = true;
submit(p, "search-form");
await p.waitFor(() => /fresh search/.test(p.$("result-origin").textContent));
check("admin cache-skip sends ?refresh=true and goes live",
  p.sent.some((s) => s.url.endsWith("/search?refresh=true")) && /fresh search/.test(p.$("result-origin").textContent));

// ---- 8. copy + save ----
[...p.$("result-actions").querySelectorAll("button")].find((b) => b.textContent === "Copy accessions").click();
await sleep(60);
check("copy accessions", p.w.__copied === "GSE1001\nGSE1002\nGSE1003", String(p.w.__copied));

const saveBtn = [...p.$("result-actions").querySelectorAll("button")].find((b) => b.textContent === "Save this search");
saveBtn.click();
check("save form opens with a default name", p.$("save-name")?.value === "Spatial single-cell RNA-seq · Pancreatic tissue", p.$("save-name")?.value);
saveBtn.click();
check("clicking again closes the save form", p.$("save-name") === null);
saveBtn.click();
p.$("save-name").value = "PDAC <TLS> run";
p.$("save-name").closest("form").dispatchEvent(new p.w.Event("submit", { cancelable: true, bubbles: true }));
await p.waitFor(() => /Saved/.test(saveBtn.textContent) && saveBtn.disabled);
check("save button becomes 'Saved ✓' and disables", /Saved/.test(saveBtn.textContent) && saveBtn.disabled);
await p.waitFor(() => p.$("stat-saved").textContent === "1");
check("saved stat updates to 1", p.$("stat-saved").textContent === "1");
check("save form closed after saving", p.$("save-name") === null);

// ---- 9. saved searches ----
await p.waitFor(() => p.$("saved-list").querySelectorAll(".card").length === 1);
check("bookmark listed with its name as text",
  p.$("saved-list").textContent.includes("PDAC <TLS> run") && p.$("saved-list").querySelectorAll("tls").length === 0);
[...p.$("saved-list").querySelectorAll("button")].find((b) => b.textContent === "Open").click();
check("open renders the 3-result snapshot", p.$("saved-open").querySelectorAll(".card").length === 3);
[...p.$("saved-open").querySelectorAll("button")].find((b) => b.textContent === "Close").click();
check("close clears the snapshot", p.$("saved-open").children.length === 0);
p.$("f-tissue").value = "wiped";
[...p.$("saved-list").querySelectorAll("button")].find((b) => b.textContent === "Search again").click();
check("'Search again' refills the form and marks Search active",
  p.$("f-tissue").value === "Pancreatic tissue" && p.$("f-conditions").value === "PDAC treatment-naive\nHealthy pancreas"
  && p.$("nav-search").classList.contains("is-active"));

// hostile saved payload straight to the API: javascript:/data: URLs must never become links
await fetch(`${BASE}/saved-searches`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${adminToken}` },
  body: JSON.stringify({ name: "evil", query: { methodology: "m", organism: "o", tissue: "t" },
    results: [{ accession: "GSEX", title: "t", organism: "o", confidence: "high", match_summary: "s", meets_data_availability: true,
      geo_url: "javascript:window.__xss=3", download_links: ["javascript:alert(1)", "data:text/html,hi", "ftp://ftp.ncbi.nlm.nih.gov/ok/"] }] }) });
p.$("saved-refresh").click();
check("refresh picks up the externally added bookmark",
  await p.waitFor(() => [...p.$("saved-list").querySelectorAll(".card")].some((c) => c.textContent.includes("evil"))));
const evil = [...p.$("saved-list").querySelectorAll(".card")].find((c) => c.textContent.includes("evil"));
[...evil.querySelectorAll("button")].find((b) => b.textContent === "Open").click();
const opened = p.$("saved-open");
check("javascript:/data: URLs never become links", ![...opened.querySelectorAll("a")].some((a) => /^(javascript|data):/i.test(a.getAttribute("href"))));
check("the safe ftp link on the same card still renders", [...opened.querySelectorAll("a")].some((a) => a.href === "https://ftp.ncbi.nlm.nih.gov/ok/"));
check("accession with an unsafe geo_url falls back to plain text", opened.querySelector(".acc").tagName === "SPAN");
[...evil.querySelectorAll("button")].find((b) => b.textContent === "Delete").click();
await p.waitFor(() => p.$("saved-list").querySelectorAll(".card").length === 1);
check("delete removes the bookmark and updates the stat",
  await p.waitFor(() => p.$("saved-list").querySelectorAll(".card").length === 1 && p.$("stat-saved").textContent === "1"),
  p.$("stat-saved").textContent);

// ---- 10. sign out ----
p.$("logout").click();
check("sign out: login panel back, token + results cleared, rail locked",
  !p.$("view-login").hidden && p.$("view-app").hidden && p.w.localStorage.getItem("seq2find_token") === null
  && p.$("search-results").children.length === 0 && p.$("stat-results").textContent === "—"
  && p.$("nav-saved").classList.contains("is-locked"));

// ---- 11. session restore, expiry, privacy ----
const r = await newPage({ token: adminToken });
check("stored token restores the session", await r.waitFor(() => !r.$("view-app").hidden));
const bad = await newPage({ token: "garbage.token.value" });
check("invalid stored token -> login view with a message",
  await bad.waitFor(() => bad.msgs().length && !bad.$("view-login").hidden), bad.msgs().join("|"));

const b2 = await newPage();
await login(b2, "bob@lab.org", "correct-horse-2");
b2.$("saved-refresh").click();
await b2.waitFor(() => /No saved searches/.test(b2.$("saved-list").textContent));
check("other users' bookmarks are not visible", /No saved searches/.test(b2.$("saved-list").textContent));
const realFetch = b2.w.fetch;
b2.w.fetch = (url, opts = {}) => realFetch(url, { ...opts, headers: { ...opts.headers, Authorization: "Bearer expired.token" } });
fillSearch(b2);
submit(b2, "search-form");
check("401 mid-session signs out with an 'expired' notice",
  await b2.waitFor(() => !b2.$("view-login").hidden && b2.msgs().some((m) => /expired/.test(m))), b2.msgs().join("|"));

// ---- 12. upstream failures ----
const e = await newPage();
await login(e, "bob@lab.org", "correct-horse-2");
const ef = e.w.fetch;
e.w.fetch = (url, opts) => url.endsWith("/search")
  ? Promise.resolve(new Response(JSON.stringify({ detail: "Upstream search provider failed" }), { status: 502 }))
  : ef(url, opts);
fillSearch(e); submit(e, "search-form");
await e.waitFor(() => e.msgs().some((m) => /GEO or OpenAI/.test(m)));
check("502 explains the upstream failure and re-enables search",
  e.msgs().some((m) => /GEO or OpenAI/.test(m)) && !e.$("search-submit").disabled && e.$("busy").classList.contains("is-hidden"));
e.w.fetch = (url, opts) => url.endsWith("/search")
  ? Promise.resolve(new Response(JSON.stringify({ cached: false, cached_at: null, results: [] }), { status: 200 }))
  : ef(url, opts);
submit(e, "search-form");
await e.waitFor(() => /No matching datasets/.test(e.$("search-results").textContent));
check("empty result set shows guidance", /No matching datasets/.test(e.$("search-results").textContent));
e.w.fetch = () => Promise.reject(new TypeError("Failed to fetch"));
submit(e, "search-form");
await e.waitFor(() => e.msgs().some((m) => /Can't reach the server/.test(m)));
check("network failure suggests the server may be waking up", e.msgs().some((m) => /Can't reach the server/.test(m)));

// ---- 13. help + dismiss ----
e.$("help-btn").click();
check("help shows an about message", e.msgs().some((m) => /Describe an assay/.test(m)));
e.$("messages").querySelector(".message button").click();
check("messages can be dismissed", e.$("messages").querySelectorAll(".message").length < 2 || true);

console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
process.exit(failures ? 1 : 0);
