# Seq2Find — Spec

## Overview

Seq2Find is a backend service (deployed on Render.com) that lets biologists
describe a study they're looking for — methodology, organism/tissue, treatment
conditions, and data availability — in a mix of structured fields and free
text, and get back a short, AI-ranked list of matching GEO/SRA accessions with
direct links to download the underlying data. It's called from a separate
static frontend hosted on GitHub Pages.

This is an early-stage idea and this spec is expected to change as it's built
out. Decisions below reflect where things stand now; open questions are
tracked explicitly so nothing gets silently assumed later.

## Decisions made

### Core search & matching

- **Output**: GEO accessions. Exact granularity (series-level `GSE` vs.
  sample-level `GSM` vs. run-level SRA `SRR`/`SRX`) is not finalized — start
  with `GSE`-level results and revisit once real searches are being run.
- **Metadata source**: live queries against NCBI's GEO/SRA E-utilities API.
  No bulk local index or mirror of GEO metadata — always current, no separate
  ingestion pipeline to maintain.
- **Matching approach**: AI-assisted semantic search, not just structured
  filters. Flow: fetch a live candidate set from GEO/SRA via keyword/E-utilities
  queries, then use an AI model to rank/filter that candidate set against the
  user's full input (including free-text conditions that aren't in structured
  GEO fields). No pre-built vector index.
- **AI provider**: OpenAI (embeddings and/or completion API) for the
  ranking/matching step.
- **Input fields**: methodology/assay type, organism & tissue/cell type,
  treatment conditions, and data availability/format. These can combine
  structured selections with free text, since some things biologists care
  about (e.g. specific annotations present in metadata) don't map to a fixed
  GEO field.
- **Result presentation**: a small ranked shortlist (~10–20 results) with a
  short AI-generated note on why each one matched, rather than a large
  unranked list.

### Data & downloads

- **Download feature**: return direct links to files already hosted on
  GEO/SRA/ENA. The backend does not proxy, cache, or re-host actual sequencing
  data files — this avoids bandwidth/storage costs on Render and keeps the
  service stateless with respect to large files.

### Backend & auth

- **Stack**: Python + FastAPI.
- **Access control**: full user accounts (signup/login), not a single shared
  API key.
- **Signup policy**: invite-only / manually approved — no open public signup
  for now.
- **Auth/session**: JWT bearer tokens. The frontend (GitHub Pages) and backend
  (Render) live on different domains, so token-based auth avoids cross-domain
  cookie complications.

### Infrastructure

- **Database**: Render-managed PostgreSQL, used for user accounts and
  saved/bookmarked searches, and as a cache for recent GEO/AI results (to
  reduce repeat NCBI/OpenAI calls).
- **Persistence**: beyond the live GEO/OpenAI calls themselves, the service
  persists (a) user accounts, (b) saved/bookmarked searches per user, and
  (c) a short-lived cache of recent search results.
- **Usage scale**: initially just the user / a small lab group — not designed
  for open public traffic yet. This keeps OpenAI cost and abuse risk low
  without needing heavy rate-limiting infrastructure on day one.
- **Frontend**: a separate repository, `seq2find-frontend`, served by GitHub
  Pages (plain HTML, CSS and JS; no build step). Kept apart from the backend
  so the two halves deploy independently across a real HTTP boundary. It
  reuses the frosted-glass design system from the author's RNA-seq Explorer
  project, including its light/dark tokens. Its `config.js` holds the API
  base URL. The page signs in, runs searches,
  and manages saved searches; all API-provided text is inserted as text nodes
  and only http(s) links are rendered, so a hostile field cannot inject
  markup or a `javascript:` URL.

## Environment variables

These are the secrets/config the Render service needs. None are committed to
the repo — set them in the Render dashboard (or via `render.yaml` sync: false
placeholders).

| Variable | Purpose | Where it comes from |
|---|---|---|
| `OPENAI_API_KEY` | Powers the AI ranking/matching step | platform.openai.com → API keys (billing must be enabled) |
| `NCBI_API_KEY` | Raises E-utilities rate limit from 3 to 10 req/sec | ncbi.nlm.nih.gov account → Settings → API Key Management |
| `JWT_SECRET` | Signs/verifies auth tokens | Self-generated, e.g. `openssl rand -hex 32` |
| `DATABASE_URL` | Postgres connection string | Auto-provided by Render when the managed Postgres instance is created |
| `ALLOWED_ORIGINS` | CORS allowlist for the GitHub Pages frontend domain | Set once the Pages site's URL is known |

## Worked example

**Input** (a real scenario the user described):

```json
{
  "methodology": "Spatial single-cell RNA-seq",
  "organism": "Human",
  "tissue": "Pancreatic tissue",
  "conditions": [
    "PDAC primary resection, treatment-naive",
    "Healthy patient pancreas (control)",
    "PDAC primary resection, GEM (gemcitabine) treatment"
  ],
  "data_availability": "Metadata must indicate TLS (tertiary lymphoid structure) annotations present"
}
```

**Expected output** (illustrative shape, not final schema):

```json
{
  "results": [
    {
      "accession": "GSE123456",
      "title": "Spatial transcriptomic atlas of pancreatic ductal adenocarcinoma",
      "matched_conditions": ["PDAC primary resection, treatment-naive", "Healthy patient pancreas (control)"],
      "has_tls_annotations": true,
      "match_summary": "Spatial RNA-seq of treatment-naive PDAC resections and matched healthy pancreas; sample metadata includes TLS region annotations.",
      "download_links": [
        "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE123nnn/GSE123456/suppl/..."
      ]
    }
  ]
}
```

This example matters because "TLS annotations present" is not a field GEO
exposes as structured metadata — it typically only shows up in free-text
sample/series descriptions or supplementary file documentation. This is
exactly the kind of match that plain structured filtering (or NCBI's own
search) would miss, and is the core reason semantic/AI-assisted matching was
chosen over structured filters alone.

### Validated with a real run

`prototype/search_prototype.py` was run against this exact example with a live
OpenAI key. It returned `GSE277116` as the top match — a real GEO series
studying TLS formation in pancreatic tumors under neoadjuvant immunotherapy,
flagged `meets_data_availability: true` with high confidence. Confirms the
core flow (live NCBI fetch → AI query expansion → AI ranking) surfaces matches
that keyword/structured search alone would not.

While building this, a real recall problem showed up: a single literal query
built from the user's exact wording ("Spatial single-cell RNA-seq") missed a
separately-known strong match, because GEO submitters describe the same assay
differently (e.g. "spatial transcriptomics"). Fixed by having the AI generate
a few alternate phrasings of the same criteria and merging results across all
of them before ranking — recovery of the missed match was confirmed. This
does mean each search now costs an extra AI call and several more NCBI calls
(throttled client-side to respect NCBI's rate limit), which is a real
cost/latency tradeoff worth revisiting if search volume grows.

## API contract

All routes except `/health` and `/auth/login` require `Authorization: Bearer <jwt>`.
Auth failures are always `401`. Interactive docs: `/docs`.

| Route | Purpose |
|---|---|
| `POST /auth/login` | `{email, password}` -> `{access_token, token_type: "bearer"}`. Emails are case-insensitive; unknown user and wrong password are indistinguishable. |
| `GET /auth/me` | Current user (`id`, `email`, `is_admin`, `created_at`). |
| `POST /search` | Run a search (below). |
| `GET/POST /saved-searches` | List / create bookmarks for the current user. |
| `GET/DELETE /saved-searches/{id}` | Fetch / delete one. Other users' ids return `404`, not `403`. |

There is deliberately no public register route. Accounts are created by an
admin running `python -m scripts.create_user <email> [--admin]` against the
production `DATABASE_URL`; `--reset` changes an existing user's password.

### `POST /search`

Request:

```json
{
  "methodology": "Spatial single-cell RNA-seq",
  "organism": "Human",
  "tissue": "Pancreatic tissue",
  "conditions": ["PDAC primary resection, treatment-naive"],
  "data_availability": "Metadata must indicate TLS annotations present",
  "max_results": 10
}
```

`methodology`, `organism`, `tissue` are required (they drive the NCBI query);
`conditions` (max 10), `data_availability` and `max_results` (1-20, default 10)
are optional. Text is whitespace-trimmed; blank required fields are `422`.

Response:

```json
{
  "cached": false,
  "cached_at": null,
  "results": [{
    "accession": "GSE277116",
    "title": "...",
    "organism": "Homo sapiens",
    "n_samples": 24,
    "confidence": "high",
    "match_summary": "...",
    "matched_conditions": ["..."],
    "meets_data_availability": true,
    "data_availability_evidence": "...formation of mature tertiary lymphoid structures in a remodeled pancrea...",
    "geo_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE277116",
    "download_links": ["ftp://.../GSE277nnn/GSE277116/", "ftp://.../GSE277116/suppl/"]
  }]
}
```

Query parameter `?refresh=true` (admin users only, otherwise `403`) skips the
cache read and overwrites the cached entry, for re-running a search without
waiting out the TTL. Empty result sets are never cached, and a refresh that
comes back empty leaves the existing cached entry alone.

`confidence` is lower-cased and trimmed before validation. Each search logs
its query variants, per-query and merged candidate counts (with accessions),
and every ranker item dropped and why, so a missing expected accession can be
traced to "never fetched" vs. "excluded by the ranker" vs. "dropped in the join".

`meets_data_availability` replaces the example-specific `has_tls_annotations`
from the illustrative output above. Results are `GSE`-level. Accessions the AI
returns that were not in the fetched candidate set are dropped. `502` means
NCBI or OpenAI failed.

## Database schema

Managed with Alembic (`alembic upgrade head`); initial migration is
`alembic/versions/0001_initial_schema.py`, models are in `app/models.py`.

- `users`: `id` uuid, `email` (unique, stored lowercase, enforced by a CHECK),
  `password_hash` (bcrypt), `is_active`, `is_admin`, `created_at`.
- `saved_searches`: `id`, `user_id` -> users (ON DELETE CASCADE), `name`,
  `query` jsonb, `results` jsonb (full snapshot at save time, so bookmarks
  survive cache expiry), `created_at`. Indexed on `(user_id, created_at)`.
- `search_cache`: `cache_key` (sha256 of lower-cased normalized query +
  `SEARCH_CACHE_VERSION`), `query` jsonb, `results` jsonb (full ranked list;
  `max_results` is applied per request), `created_at`, `expires_at`. Shared
  across users. TTL is `SEARCH_CACHE_TTL_HOURS` (default 24). Bump
  `SEARCH_CACHE_VERSION` in `app/config.py` when the ranking prompt or model
  changes. Expired rows are overwritten on the next identical search but never
  purged yet.

### Recall lessons from production testing

The known-good `GSE277116` initially never appeared in production results.
Three separate causes, each found from the per-search logs:

1. **Query variants carried too much.** Given the full input, the AI put
   "TLS annotations" into its NCBI queries; NCBI ANDs every word, so 3 of 4
   variants returned 0 candidates. Variants now see only methodology,
   organism and tissue.
2. **Candidate cap.** The match sits ~25th within the one variant that finds
   it, so a 40-candidate cap dropped it. The service now sends up to 100
   (`MAX_CANDIDATES_FOR_RANKING`).
3. **Ranker skimming.** One call over ~80-100 candidates made
   `gpt-4o-mini` return only 2-6 results and usually skip the target. Ranking
   is now two stages in `app/services/ranking.py`:
   - *Filter:* `gpt-4o-mini` judges batches of 20 (`RANKING_BATCH_SIZE`) in
     parallel and must return a verdict per candidate; candidates it skips
     (~5 per search) are retried once. Tested on 4 identical pools: target
     found 4/4, vs 1-2/4 for a single call.
   - *Re-rank:* one call (`RERANK_MODEL`, default `gpt-4o`) over the ~10-30
     survivors ranks them against each other. Verdicts from separate batches
     are not comparable (nearly everything came back "high" with
     `meets_data_availability: true`), so this pass is what gives a usable
     order. `gpt-4o` is only viable because this input is small (~7-10k
     tokens); a single call over the whole pool exceeds this OpenAI
     account's per-minute token limit. Set `RERANK_MODEL=gpt-4o-mini` to
     avoid it.

`meets_data_availability` is decided in code, not taken from the model:
the re-ranker proposes literal search terms for the requirement once per
search (e.g. "TLS", "tertiary lymphoid structure"); the flag is true only if
the model judges it met AND a term literally appears in the study's title or
summary. `data_availability_evidence` is a snippet cut from that text by
code, so it cannot be invented. An earlier version asked the model to quote
evidence and only checked the quote existed; it flip-flopped run to run.
Remaining weakness: the model's own judgment still occasionally says "no" for
a study whose title states the requirement (a safe-direction miss), and the
ranker only sees titles and summaries, never sample-level metadata.

This was validated on one known example plus a handful of runs, so treat it as
evidence, not proof; more known-good queries would make a real evaluation set.
Bump `SEARCH_CACHE_VERSION` whenever this pipeline or its prompts change (now
`v4`).

Live, uncached searches take ~20-25s (stage 1 ~13s, retry ~4s, re-rank
~5s) and cost on the order of a few cents; identical searches are then
served from the cache. The frontend needs a loading state for this.

## Open questions

These are known gaps to resolve in future iterations, not oversights:

- Exact output granularity: `GSE` only, or also `GSM`/`SRR` when a user needs
  run-level data?
- Rate limiting / cost caps on OpenAI usage per user or globally.
- Cache: 24h TTL and version-key invalidation are set (see Database schema);
  still open is purging expired rows.
- Signup: settled as a manual admin script for now (no invite emails or admin
  panel); revisit if the group grows.
- Error handling for GEO/SRA/OpenAI outages, rate limits, or malformed/
  ambiguous user input.
- Whether saved/bookmarked searches need any sharing or export feature
  (e.g. CSV export of shortlisted accessions).
- CORS: `ALLOWED_ORIGINS` must be the Pages origin only (scheme + host, no
  path or trailing slash). Still open: whether a custom domain is wanted.

## Next steps

1. Wire up Render: create the Postgres instance, set the env vars, run
   `alembic upgrade head`, create the first user with `scripts/create_user`.
2. Make the prototype's NCBI throttle thread-safe (it uses a module-level
   timestamp; concurrent searches can briefly exceed NCBI's rate limit, which
   the 429 retry currently absorbs).
3. Per-user / global OpenAI rate limiting and cost caps.
4. Frontend deployed from the `seq2find-frontend` repo via GitHub Pages,
   with `ALLOWED_ORIGINS` set to that origin.
