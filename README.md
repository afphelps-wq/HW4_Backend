# Seq2Find

Describe a study — assay, organism, tissue, treatment conditions, data availability — and get a
short, AI-ranked list of GEO series with direct download links.

The point is the free-text criteria. "Sample metadata indicates TLS annotations" is not a field
GEO exposes, so plain keyword search misses those studies; Seq2Find fetches a live candidate set
from NCBI and has a language model judge each candidate against the full request.

- **Backend**: FastAPI on Render, Postgres for accounts, bookmarks and a result cache.
- **Frontend**: a static page in [`docs/`](docs/), served by GitHub Pages.
- **Spec and design decisions**: [`spec.md`](spec.md).

## How a search works

1. A language model proposes a few alternate phrasings of the assay/organism/tissue, because GEO
   submitters describe the same assay differently ("spatial transcriptomics" vs "spatial
   single-cell RNA-seq").
2. Each phrasing is run against NCBI E-utilities and the results are merged (~70–100 series).
3. **Stage 1** filters them in parallel batches of 20; anything the model skips is retried.
4. **Stage 2** re-ranks the survivors in one call, so confidence is comparable across the list.
5. `meets_data_availability` is decided in code: the model must say so *and* a search term it
   proposed must literally appear in the study's own title or summary. The quoted evidence is cut
   from that text, so it cannot be invented.

Results are cached in Postgres for 24 hours, keyed on the query and the pipeline version.

## Running the backend locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the values
alembic upgrade head
uvicorn backend:app --reload
```

Interactive API docs are at `/docs`. Required environment variables are listed in
[`spec.md`](spec.md#environment-variables).

Accounts are invite-only — there is no public signup route. Create one with:

```bash
python -m scripts.create_user you@example.com --admin     # --reset to change a password
```

## Deploying

**Backend (Render)** — build `pip install -r requirements.txt`, start
`alembic upgrade head && uvicorn backend:app --host 0.0.0.0 --port $PORT`, health check path
`/health`. Set `DATABASE_URL` to the database's *internal* URL; run `scripts/create_user` from
your own machine using the *external* one.

**Frontend (GitHub Pages)** — Settings → Pages → deploy from `main` / `docs`. Then:

- point [`docs/config.js`](docs/config.js) at your API URL, and
- set `ALLOWED_ORIGINS` on the Render service to the Pages origin (e.g.
  `https://<user>.github.io`) — origin only, no path or trailing slash, or the browser blocks
  every request.

## Tests

```bash
pytest                                  # backend: SQLite, no network
node tests/frontend/test.mjs            # frontend: jsdom against a stubbed API (see that file)
```

## Caveats

Ranking sees only each study's title and summary, never sample-level metadata, so
"requirement met" means the study's own text says so. An uncached search takes 20–30 seconds and
makes several OpenAI and NCBI calls. On Render's free tier the service sleeps when idle, so the
first request after a pause can take about a minute.
