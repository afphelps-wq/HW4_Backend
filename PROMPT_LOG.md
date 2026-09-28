# Prompt Log

Verbatim log of the prompts given while building Seq2Find, in chronological order.
Selections made in multiple-choice clarifying questions are not repeated here;
the decisions they produced are recorded in [spec.md](spec.md).

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
