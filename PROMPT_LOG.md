# Prompt Log

Verbatim log of the prompts given while building Seq2Find, in chronological order.
Selections made in multiple-choice clarifying questions are not repeated here;
the decisions they produced are recorded in [spec.md](spec.md). Long console,
API and deploy-log pastes are shortened, marked `[... truncated ...]`; the prompt
text itself is never edited.

## Tools and models used

**To build it:** [Claude Code](https://claude.com/claude-code), Anthropic's CLI/IDE coding agent,
run inside VS Code. It wrote code, ran the test suites, made the live NCBI/OpenAI calls used to
validate the ranking pipeline, and drove `git` and `gh`. Sessions 1 and 2 ran on **Claude Sonnet
5**; the frontend work onwards ran on **Claude Opus 5**. Each commit records which one in its
`Co-Authored-By` trailer.

**Inside the app:** OpenAI's **`gpt-4o-mini`** generates the alternate NCBI query phrasings and
runs the stage-1 candidate filter; **`gpt-4o`** does the stage-2 re-rank. Both are called from the
backend only (see [README](README.md#how-secrets-and-auth-are-handled)).

## Prompts that shaped the implementation

The whole log is below, but these are the turns that changed the design rather than the wiring:

| # | Prompt | What it changed |
|---|---|---|
| [1](#1-project-kickoff) | "help me figure out what details I want to implement by creating a spec.md and then prompting me with as many questions as you can" | Produced `spec.md` and the question-first workflow used throughout |
| [2](#2-example-query-reply-to-a-clarifying-question) | The PDAC / TLS example query | The worked example the whole pipeline is validated against; "TLS annotations" is what forced AI ranking over plain filtering |
| [16](#16-fix-query-recall) | "try to fix it" (a known-good study was missing) | Added AI-generated query variants after a single literal query proved to miss matches |
| [20](#20-session-2-api-schema-auth-routes-database-schema) | "/search endpoint schema, auth routes … Postgres schema" | The API contract, JWT auth and the three tables |
| [21](#21-ask-the-clarifying-questions) | "ask me these questiosn" | Chose the admin-script signup, SQLAlchemy + Alembic, and result snapshots in bookmarks |
| [40](#40-accept-the-four-proposed-fixes) | "Don't cache empty results / Normalize confidence casing / Log the query variants … / admin-only ?refresh=true" | The diagnostics that made the recall bug findable at all |
| [44](#44-logs-reveal-the-cause-variants-return-nothing) | The log paste showing 3 of 4 variants returning 0 candidates | Root cause: the variant prompt was seeing the data-availability text and ANDing "TLS" into NCBI queries |
| [47](#47-build-stage-2-and-when-does-the-frontend-start) | "yes build stage 2" | Two-stage ranking, after batch verdicts proved not comparable across batches |
| [50](#50-match-the-other-projects-style) | "model this frontend to be the same style as my project" | The frontend reuses the design system from `15113-api-project` |

## 1. Project kickoff

```
I want to create a simple backend service on Render.com to integrate into a GitHub Pages Site. The service I want to create is called Seq2Find which allows biologists to input details like methodology, treatment conditions, data availability etc and it outputs geo accessions and allows easy download of data for projects. This is still a rough idea so I need to iterate a lot on the features. First, help me figure out what details I want to implement by creating a spec.md and then prompting me with as many questions as you can to clarify all the details of the service
```

## 2. Example query (reply to a clarifying question)

```
"Spatial SC RNA:Pancreatic Tissue: PDAC primary resction treatment naive, healthy patient pancreas, PDAC primary resection GEM treatment, TLS annotations present: metadata available
```

## 3. API keys

```
ok so now I need to find the api keys necessary for this
```

## 4. Env vars in spec and Render setup

```
yes also I am setting up the render service right now
```

## 5. Remaining env vars

```
under the environment variables i have added the open ai key and ncbi key in render, do I need to add anything else?
```

## 6. JWT secret

```
do i just generate values for JWT_SECRET?
```

## 7. Render advanced settings

```
do i need to include any of these advanced filters?

Secret Files
Store plaintext files containing secret data (such as a .env file or a private key).
Access during builds and at runtime from your app’s root, or from /etc/secrets/<filename>.

Add Secret File
Health Check Path
Provide an HTTP endpoint path that Render messages periodically to monitor your service. Learn More.
/healthz
Pre-Deploy Command
Render runs this command before the start command. Useful for database migrations and static asset uploads.
Auto-Deploy
By default, Render automatically deploys your service whenever you update its code or configuration. Disable to handle deploys manually. Learn more.
autoDeployTrigger

On Commit
Build Filters
Include or ignore specific paths in your repo when determining whether to trigger an auto-deploy. Paths are relative to your repo's root directory. Learn more.
```

## 8. When to deploy

```
ok i shouldn't hit deploy yet though until I build the backend code right
```

## 9. Rename skeleton

```
make the skeleton called backend.py
```

## 10. Commit

```
commit all this so i can deploy
```

## 11. Push

```
yes git push
```

## 12. Redeploy on Render

```
i accidently deployed before I pushed to github, is there a way I can redo the deploy on render?
```

## 13. Deploy error log

```
==> Uploading build...
==> Uploaded in 1.8s. Compression took 1.1s
==> Build successful 🎉
==> Deploying...
==> Setting WEB_CONCURRENCY=1 by default, based on available CPUs in the instance
==> Running 'gunicorn app:backend'
bash: line 1: gunicorn: command not found
==> Exited with status 127
==> Common ways to troubleshoot your deploy: https://render.com/docs/troubleshooting-deploys
==> Running 'gunicorn app:backend'
bash: line 1: gunicorn: command not found
```

## 14. Deploy success

```
ok it worked!
```

## 15. Next task

```
start next task
```

## 16. Fix query recall

```
try to fix it
```

## 17. Running the prototype

```
how should I run it?
```

## 18. Prototype output

```
(venv) anabellaphelps@Anabellas-MacBook-Air HW4_Backend % python prototype/search_prototype.py

[
  {
    "accession": "GSE277116",
    "match_summary": "The study investigates the impact of neoadjuvant immunotherapy on the formation of tertiary lymphoid structures (TLS) in pancreatic tumors, employing spatial single-cell RNA-seq methodology.",
    "matched_conditions": [
      "PDAC primary resection, treatment-naive",
      "Healthy patient pancreas (control)",
      "PDAC primary resection, GEM (gemcitabine) treatment"
    ],
    "meets_data_availability": true,
    "confidence": "high"
  },
  {
    "accession": "GSE335452",
    "match_summary": "This work characterizes CD8+ exhausted T cells within pancreatic ductal adenocarcinoma using spatial single-cell RNA-seq, relevant to PDAC conditions.",
    "matched_conditions": [
      "PDAC primary resection, treatment-naive",
      "PDAC primary resection, GEM (gemcitabine) treatment"
    ],
    "meets_data_availability": false,
    "confidence": "medium"
  },
  {
    "accession": "GSE111672",
    "match_summary": "Combines spatial transcriptomics and single-cell RNA-seq to reveal tissue architecture in pancreatic ductal adenocarcinomas, relevant to human pancreatic tissue.",
    "matched_conditions": [
      "PDAC primary resection, treatment-naive",
      "PDAC primary resection, GEM (gemcitabine) treatment"
    ],
    "meets_data_availability": false,
    "confidence": "medium"
  }
]
```

## 19. Prompt log

```
before the create a prompt log file and add all prompts to that file
```

## 20. Session 2: API schema, auth routes, database schema

```
First read the spec.md and prototype file. I just finished the prototype and I  then I am now working on this (/search endpoint schema, auth routes) and the Postgres schema (users, saved searches, cache).
```

## 21. Ask the clarifying questions

```
ask me these questiosn
```

## 22. Render setup

```
ok so how do i do the render set up
```

## 23. Commit and push

```
commit and push the new work
```

## 24. Which password

```
what is the password?
```

## 25. create_user fails on DATABASE_URL

```
Traceback (most recent call last):
  File "<frozen runpy>", line 203, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/Users/anabellaphelps/Documents/GitHub/HW4_Backend/scripts/create_user.py", line 59, in <module>
    sys.exit(main())
             ~~~~^^
  File "/Users/anabellaphelps/Documents/GitHub/HW4_Backend/scripts/create_user.py", line 41, in main
    with Session(get_engine()) as db:
                 ~~~~~~~~~~^^
  File "/Users/anabellaphelps/Documents/GitHub/HW4_Backend/app/db.py", line 18, in get_engine
    _engine = create_engine(database_url(), pool_pre_ping=True)
[... truncated ...]
sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL from given URL string
```

## 26. Internal or external database URL

```
should i use the internal or external?
```

## 27. Database URL set on Render

```
ok i added database url to the render web service and added an internal url
```

## 28. First successful deploy

```
[... truncated: pip install output ...]
==> Build successful 🎉
==> Deploying...
==> Setting WEB_CONCURRENCY=1 by default, based on available CPUs in the instance
==> Running 'uvicorn backend:app --host 0.0.0.0 --port $PORT'
==> Your service is live 🎉
==> Available at your primary URL https://seq2find.onrender.com
INFO:     Started server process [58]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:10000 (Press CTRL+C to quit)
INFO:     127.0.0.1:52608 - "HEAD / HTTP/1.1" 404 Not Found
INFO:     10.236.25.120:40944 - "GET /health HTTP/1.1" 200 OK
```

## 29. Python version pin

```
where do i add the python version pin?
```

## 30. Creating the first user

```
ok now that i have redeployed what is the next step to crreat user
```

## 31. Start command now runs migrations

```
==> Running 'alembic upgrade head && uvicorn backend:app --host 0.0.0.0 --port $PORT'
```

## 32. Server started

```
Uvicorn running on http://0.0.0.0:10000
```

## 33. Login works

```
ok it responded with access_token
```

## 34. Authorized in /docs

```
ok I authorized wht is step 3?
```

## 35. First /search returns 502

```
Request URL
https://seq2find.onrender.com/search
Server response
Code	Details
502
Undocumented
Error: response status is 502

Response body
{
  "detail": "Upstream search provider failed; try again shortly"
}
```

## 36. Cause: OpenAI key missing on Render

```
Upstream failure during search
Traceback (most recent call last):
  File "/opt/render/project/src/app/routers/search.py", line 27, in search
    results, cached_at = search_service.search(db, body)
  File "/opt/render/project/src/app/services/search.py", line 92, in _run_live_search
    for query in generate_query_variants(user_input):
  File "/opt/render/project/src/prototype/search_prototype.py", line 99, in generate_query_variants
    client = OpenAI()
openai.OpenAIError: Missing credentials. Please pass an `api_key`, `workload_identity`, `admin_api_key`, or set the `OPENAI_API_KEY` or `OPENAI_ADMIN_KEY` environment variable.
```

## 37. Env vars fixed

```
ok i fixed the environment variables and now its deploying
```

## 38. 401 (docs page lost its authorization)

```
curl -X 'POST' \
  'https://seq2find.onrender.com/search' \
  -H 'accept: */*' \
  -H 'Content-Type: application/json' \
[... truncated: request body ...]
Server response
Code	Details
401
Response body
{
  "detail": "Invalid or missing credentials"
}
```

## 39. First working search (GSE277116 missing)

```
{
  "cached": true,
  "cached_at": "2026-09-28T02:19:26.739178Z",
  "results": [
    {
      "accession": "GSE335452",
      "title": "Single-cell RNA-seq and spatial transcriptomics characterize CD8+ exhausted T cells in pancreatic ductal adenocarcinoma",
      "organism": "Homo sapiens",
      "n_samples": 15,
      "confidence": "high",
      "matched_conditions": [
        "PDAC primary resection, treatment-naive",
        "PDAC primary resection, GEM (gemcitabine) treatment"
      ],
      "meets_data_availability": true,
      "geo_url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE335452"
    },
[... truncated: GSE335070, GSE253430, GSE111672 ...]
  ]
}
```

## 40. Accept the four proposed fixes

```
Don't cache empty results.
Normalize confidence casing.
Log the query variants, the candidate count, and any dropped ranker items, so we can see why GSE277116 didn't appear.
Add an admin-only ?refresh=true so you can re-run a search without waiting out the cache.
```

## 41. Push first or investigate first

```
wait so should i push or should i find out about gse277116
```

## 42. Commit and push

```
ok commit and push
```

## 43. Refresh still misses GSE277116

```
{
  "cached": false,
  "cached_at": null,
  "results": [
[... truncated: GSE335452, GSE335070, GSE253430, GSE111672 - same four, no GSE277116 ...]
  ]
}
```

## 44. Logs reveal the cause: variants return nothing

```
INFO app.services.search: Query variants: ['Spatial single-cell RNA-seq AND Human AND Pancreatic tissue', 'Spatial scRNA-seq Human Pancreas with TLS annotations', 'Spatial transcriptomics single-cell RNA-seq Human pancreatic tissue TLS', 'ssRNA-seq Human pancreatic samples with tertiary lymphoid structures']
INFO app.services.search: Query 'Spatial single-cell RNA-seq AND Human AND Pancreatic tissue' returned 13 GSE candidates
INFO app.services.search: Query 'Spatial scRNA-seq Human Pancreas with TLS annotations' returned 0 GSE candidates
INFO app.services.search: Query 'Spatial transcriptomics single-cell RNA-seq Human pancreatic tissue TLS' returned 0 GSE candidates
INFO app.services.search: Query 'ssRNA-seq Human pancreatic samples with tertiary lymphoid structures' returned 0 GSE candidates
INFO app.services.search: Merged 14 unique candidates, sending 14 to ranker: GSE335070, GSE335452, GSE253430, GSE253429, GSE247808, GSE247807, GSE247806, GSE247805, GSE237848, GSE217847, GSE197064, GSE203612, GSE111672, GSE226840
INFO app.services.search: Ranker returned 4 items, kept 4: GSE226840, GSE335452, GSE335070, GSE111672
```

## 45. Push the recall fix

```
push
```

## 46. Recall fixed, but every result is 'high'

```
[... truncated: 10 results, GSE277116 now present at position 5 ...]

INFO app.services.search: Query variants: ['Spatial single-cell RNA-seq AND Human AND Pancreatic tissue', 'spatial scRNA-seq Human pancreatic', 'spatial transcriptomics human pancreas', 'single-cell spatial RNA sequencing human pancreatic tissue']
INFO app.services.search: Query 'Spatial single-cell RNA-seq AND Human AND Pancreatic tissue' returned 13 GSE candidates
INFO app.services.search: Query 'spatial scRNA-seq Human pancreatic' returned 34 GSE candidates
INFO app.services.search: Query 'spatial transcriptomics human pancreas' returned 40 GSE candidates
INFO app.services.search: Query 'single-cell spatial RNA sequencing human pancreatic tissue' returned 40 GSE candidates
INFO app.services.search: Merged 86 unique candidates, sending 86 to ranker: [... truncated ...]
WARNING app.services.ranking: Ranker covered 81 of 86 candidates
INFO app.services.search: Ranker returned 17 items, kept 17: GSE217845, GSE226840, GSE327056, GSE299970, GSE277116, GSE300435, GSE294669, GSE278687, GSE235315, GSE202740, GSE226829, GSE335452, GSE267680, GSE202742, GSE337859, GSE201601, GSE111672
```

## 47. Build stage 2, and when does the frontend start

```
yes build stage 2, at what point will we get to building the frontend?
```

## 48. Commit and push

```
commit and push
```

## 49. Two-stage ranking confirmed in production

```
INFO app.services.search: Query variants: ['Spatial single-cell RNA-seq AND Human AND Pancreatic tissue', 'spatial scRNA-seq human pancreatic tissue', 'spatial transcriptomics human pancreas', 'spatial single-cell sequencing human pancreatic cells']
INFO app.services.search: Query 'Spatial single-cell RNA-seq AND Human AND Pancreatic tissue' returned 13 GSE candidates
INFO app.services.search: Query 'spatial scRNA-seq human pancreatic tissue' returned 33 GSE candidates
INFO app.services.search: Query 'spatial transcriptomics human pancreas' returned 40 GSE candidates
INFO app.services.search: Query 'spatial single-cell sequencing human pancreatic cells' returned 40 GSE candidates
INFO app.services.search: Merged 89 unique candidates, sending 89 to ranker: [... truncated ...]
INFO app.services.ranking: Retrying 4 candidates the ranker skipped
INFO app.services.ranking: Stage 1 kept 18 of 89 candidates
INFO app.services.ranking: Re-rank terms ['TLS', 'tertiary lymphoid structure', 'annotations']; kept 10 of 18 survivors; dropped/omitted: GSE253429, GSE327056, GSE300435, GSE278687, GSE285264, GSE267680, GSE254829, GSE202742
INFO app.services.search: Ranker returned 10 items, kept 10: GSE226840, GSE277116, GSE294669, GSE335452, GSE299970, GSE249539, GSE253430, GSE311788, GSE310353, GSE306617
```

## 50. Match the other project's style

```
model this frontend to be the same style as my project https://github.com/afphelps-wq/15113-api-project
```

## 51. Commit

```
commit
```

## 52. Push

```
push
```

## 53. Update this log

```
add prompts from this session to prompt log md
```
