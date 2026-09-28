# Seq2Find

Describe a study — assay, organism, tissue, treatment conditions, data availability — and get a
short, AI-ranked list of GEO (Gene Expression Omnibus) series with direct download links.

The point is the free-text criteria. "Sample metadata indicates TLS annotations" is not a field
GEO exposes, so plain keyword search misses those studies. Seq2Find fetches a live candidate set
from NCBI and has a language model judge each candidate against the whole request.

| | |
|---|---|
| **Live frontend** | https://afphelps-wq.github.io/seq2find-frontend/ |
| **Live backend** | https://seq2find.onrender.com (interactive API docs at [`/docs`](https://seq2find.onrender.com/docs)) |
| **Stack** | FastAPI + PostgreSQL on Render; static HTML/CSS/JS on GitHub Pages |
| **Frontend repo** | https://github.com/afphelps-wq/seq2find-frontend |
| **Design decisions** | [`spec.md`](spec.md) |

Accounts are invite-only, so there is no public signup. Ask for one, or create your own locally
with the script below.

## What the backend does

Everything that needs a secret or a database happens on the server: the OpenAI and NCBI keys, the
ranking pipeline, password hashing, and the result cache. The browser only ever sees the base URL.

A search runs in five steps:

1. A language model proposes alternate phrasings of the assay/organism/tissue, because GEO
   submitters describe the same assay differently ("spatial transcriptomics" vs "spatial
   single-cell RNA-seq"). A single literal query misses real matches.
2. Each phrasing goes to NCBI E-utilities and the results are merged (~70–100 series).
3. **Stage 1** filters them in parallel batches of 20, requiring a verdict on every candidate;
   anything the model skips is retried once.
4. **Stage 2** re-ranks the survivors in one call, so confidence is comparable across the list.
5. `meets_data_availability` is decided **in code**: the model must say so *and* a search term it
   proposed must literally appear in the study's own title or summary. The quoted evidence is cut
   from that text by code, so it cannot be invented.

Results are cached in Postgres for 24 hours, keyed on the query plus the pipeline version.

## API

Base URL `https://seq2find.onrender.com`. Everything except `/health` and `/auth/login` needs an
`Authorization: Bearer <token>` header. All requests and responses are JSON.

### `POST /auth/login`

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `email` | string | yes | case-insensitive |
| `password` | string | yes | |

Returns `{"access_token": "<jwt>", "token_type": "bearer"}`. The token is valid for 60 minutes.
A wrong password and an unknown account return an identical `401`, so the response cannot be used
to discover which emails exist.

### `GET /auth/me`

Returns the signed-in user: `{"id", "email", "is_admin", "created_at"}`.

### `POST /search`

The main endpoint. Optional query parameter `?refresh=true` (admin only, else `403`) bypasses the
cache and overwrites the entry.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `methodology` | string | yes | assay type, e.g. `Spatial single-cell RNA-seq` |
| `organism` | string | yes | e.g. `Human` |
| `tissue` | string | yes | tissue or cell type |
| `conditions` | string[] | no | up to 10; judged by the AI, so free text is fine |
| `data_availability` | string | no | free-text requirement, e.g. `Metadata must indicate TLS annotations present` |
| `max_results` | int | no | 1–20, default 10 |

The first three build the NCBI query; the rest are judged by the ranking model.

```jsonc
// request
{
  "methodology": "Spatial single-cell RNA-seq",
  "organism": "Human",
  "tissue": "Pancreatic tissue",
  "conditions": ["PDAC primary resection, treatment-naive"],
  "data_availability": "Metadata must indicate TLS annotations present",
  "max_results": 10
}

// 200 response
{
  "cached": false,                 // true if served from the 24h cache
  "cached_at": null,               // when the cached copy was built
  "results": [{
    "accession": "GSE277116",
    "title": "Neoadjuvant immunotherapy promotes the formation of mature tertiary lymphoid structures…",
    "organism": "Homo sapiens",
    "n_samples": 28,
    "confidence": "high",          // high | medium | low
    "match_summary": "…one sentence on why it matched…",
    "matched_conditions": ["PDAC primary resection, treatment-naive"],
    "meets_data_availability": true,
    "data_availability_evidence": "…quote from the study's own text…",
    "geo_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE277116",
    "download_links": ["https://ftp.ncbi.nlm.nih.gov/geo/series/GSE277nnn/GSE277116/", "…/suppl/"]
  }]
}
```

### `GET|POST /saved-searches`, `GET|DELETE /saved-searches/{id}`

Bookmarks, scoped to the signed-in user. `POST` takes `{"name", "query", "results"}` and returns
`201`; it stores a snapshot of the results, so a bookmark still works after the cache expires.
`DELETE` returns `204`. Another user's id returns `404` rather than `403`, so ids can't be probed.

### `GET /health`

`{"status": "ok"}`. No auth. Used by Render's health check.

### Status codes

| Code | Meaning |
|---|---|
| `401` | missing, invalid or expired token; wrong credentials |
| `403` | `?refresh=true` without an admin account |
| `404` | saved search not found, or not yours |
| `422` | invalid input (blank required field, `max_results` out of range) |
| `502` | NCBI or OpenAI failed — the detail is deliberately generic, with the real traceback in the server log |

## How the frontend talks to the backend

The frontend is a **separate repository**, [`seq2find-frontend`](https://github.com/afphelps-wq/seq2find-frontend), served by GitHub Pages
at [https://afphelps-wq.github.io/seq2find-frontend/](https://afphelps-wq.github.io/seq2find-frontend/). Keeping it apart means the two halves deploy independently across a real
HTTP boundary. It holds no secrets — only this API's base URL, in its `config.js` — and calls the
API with `fetch()`:

| When | Call | What it does with the response |
|---|---|---|
| Sign-in form submitted | `POST /auth/login` | Stores the JWT in `localStorage`, then calls `/auth/me` |
| After login, and on page load if a token is stored | `GET /auth/me` | Shows the email, reveals the app, and shows the admin-only cache-skip checkbox if `is_admin` |
| Search form submitted | `POST /search` (plus `?refresh=true` if an admin ticks the box) | Renders a result card per match and updates the summary cards; `cached` decides whether it says "fresh search" or "cached result from …" |
| Signing in, and after any bookmark change | `GET /saved-searches` | Renders the bookmark list and the saved-count card |
| "Save this search" | `POST /saved-searches` | Confirms on the button and reloads the list |
| "Delete" on a bookmark | `DELETE /saved-searches/{id}` | Reloads the list after a confirmation prompt |

Every request attaches `Authorization: Bearer <token>` from `localStorage`.

**Error handling.** Required fields are checked before anything is sent. A `401` from any call
signs the user out and explains that the session expired. A `502` says the upstream providers
failed; a network error says the server may be waking up (Render's free tier sleeps when idle);
an empty result list suggests broader wording. Searches show a progress overlay with an elapsed
counter, because a fresh search takes 20–30 seconds, and give up after 3 minutes.

**Rendering is defensive.** Every API-supplied string is inserted as a text node, never as HTML,
and only `http(s)` URLs are turned into links, so a hostile title or a `javascript:` download link
cannot inject anything. NCBI's `ftp://` links are rewritten to `https://`, which browsers can open.

## Running it locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # then fill in the values below
alembic upgrade head                  # creates the tables
python -m scripts.create_user you@example.com --admin    # prompts for a password
uvicorn backend:app --reload          # http://127.0.0.1:8000, docs at /docs
```

Check it before involving the frontend:

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"…"}'
```

To drive it from the real page, clone [`seq2find-frontend`](https://github.com/afphelps-wq/seq2find-frontend) beside this repo, set its
`config.js` to `window.SEQ2FIND_API = "http://127.0.0.1:8000";`, add `http://localhost:8080` to
`ALLOWED_ORIGINS`, and serve it with `python -m http.server 8080` (opening the file directly gives
it an `origin` of `null`, which CORS rejects). **Change `config.js` back before pushing.**

### Environment variables

Set these in `.env` locally and in Render's dashboard in production. `.env` is gitignored and has
never been committed; [`.env.example`](.env.example) lists the names with empty values.

| Variable | Purpose | Where it comes from |
|---|---|---|
| `OPENAI_API_KEY` | the ranking model | platform.openai.com → API keys (billing must be on) |
| `NCBI_API_KEY` | raises the E-utilities limit from 3 to 10 req/sec | ncbi.nlm.nih.gov account → API Key Management |
| `JWT_SECRET` | signs auth tokens | generate one: `openssl rand -hex 32` |
| `DATABASE_URL` | Postgres connection string | Render creates it with the database |
| `ALLOWED_ORIGINS` | CORS allowlist, comma-separated | the frontend's origin, e.g. `https://afphelps-wq.github.io` — origin only, no path or trailing slash |
| `NCBI_EMAIL` | identifies the caller to NCBI | your email (optional but polite) |
| `RERANK_MODEL` | stage-2 model, default `gpt-4o` | set to `gpt-4o-mini` if the account's rate limit is low |

## How secrets and auth are handled

- **No key ever reaches the browser.** `OPENAI_API_KEY` and `NCBI_API_KEY` live only in Render's
  environment variables. The frontend knows the backend's URL and nothing else, which is the
  reason for having a backend at all: the browser calls Seq2Find, and Seq2Find calls OpenAI
  and NCBI.
- **Nothing secret is in the repo.** `.env` is gitignored and was never committed; only
  `.env.example`, with empty values, is tracked. `git log` confirms no key, token or connection
  string has ever been in a commit.
- **Passwords** are stored only as bcrypt hashes. The login endpoint verifies against a dummy hash
  when the email is unknown, so a missing account and a wrong password take the same time.
- **Sessions** are stateless JWTs signed with `JWT_SECRET`, expiring after 60 minutes. Every
  protected route re-reads the user, so deactivating an account invalidates tokens already issued.
- **Signup is closed.** There is no register route; accounts are created only by an admin running
  `scripts/create_user.py` against the database.
- **CORS** is an explicit allowlist from `ALLOWED_ORIGINS`, not a wildcard.

## Tests

```bash
pytest                                       # 39 backend checks: SQLite, no network calls

npm install jsdom                            # once
python tests/frontend/stub_api.py &        # the real app on SQLite, upstreams stubbed
node tests/frontend/test.mjs                 # 61 checks driving the real frontend
```

The frontend suite loads the real page from a [`seq2find-frontend`](https://github.com/afphelps-wq/seq2find-frontend) checkout — beside
this repo, or wherever `FRONTEND_DIR` points — into a headless DOM, and exercises sign-in, session
expiry, search, caching, bookmarks, the theme toggle, and every error path, including deliberately
hostile titles and `javascript:` links.

## Deploying

**Backend (Render).** Build `pip install -r requirements.txt`; start
`alembic upgrade head && uvicorn backend:app --host 0.0.0.0 --port $PORT`, so each deploy applies
migrations before serving. Health check path `/health`. Set the environment variables above, using
the database's **internal** URL for `DATABASE_URL`; run `scripts/create_user` from your own machine
with the **external** one.

**Frontend (GitHub Pages).** See [`seq2find-frontend`](https://github.com/afphelps-wq/seq2find-frontend) — Pages from `main` at the repo
root. Its `config.js` points at this API, and `ALLOWED_ORIGINS` here must contain that site's
**origin** (`https://afphelps-wq.github.io`), with no path and no trailing slash.

## Caveats

The ranking model sees only each study's title and summary, never sample-level metadata, so
"requirement met" means the study's own text says so — confirm on the GEO page before relying on
it. An uncached search takes 20–30 seconds and makes several OpenAI and NCBI calls. On Render's
free tier the service sleeps when idle, so the first request after a pause takes about a minute.
