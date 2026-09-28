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
- **Frontend**: doesn't exist yet. It will be a static site on GitHub Pages
  that calls this API; the API's request/response shape should be simple
  enough to drive a lightweight future UI.

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

## Open questions

These are known gaps to resolve in future iterations, not oversights:

- Exact output granularity: `GSE` only, or also `GSM`/`SRR` when a user needs
  run-level data?
- Exact request/response JSON schema for the search endpoint (the example
  above is illustrative only).
- Rate limiting / cost caps on OpenAI usage per user or globally.
- Cache TTL and invalidation strategy for cached GEO/AI results.
- Signup/invite mechanics: who approves new accounts, and how are invites
  sent (manual DB insert, email invite flow, admin panel)?
- Error handling for GEO/SRA/OpenAI outages, rate limits, or malformed/
  ambiguous user input.
- Whether saved/bookmarked searches need any sharing or export feature
  (e.g. CSV export of shortlisted accessions).
- CORS configuration specifics between the GitHub Pages domain and the
  Render backend domain.

## Next steps

1. Design the concrete API contract (endpoints, request/response schemas,
   auth flow) based on the decisions above.
2. Design the PostgreSQL schema for users, saved searches, and cached results.
3. Prototype the "fetch live candidates, then AI-rank" search flow against a
   couple of real example queries (like the one above) to validate the
   approach before building the full API.
