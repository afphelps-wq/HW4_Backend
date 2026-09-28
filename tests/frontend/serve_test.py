"""Back end for the frontend checks: the real FastAPI app on an in-memory SQLite
database, with the NCBI and OpenAI calls stubbed out, on http://127.0.0.1:8765.

Two accounts exist: admin@lab.org / correct-horse-1 (admin) and
bob@lab.org / correct-horse-2. Run it, then `node tests/frontend/test.mjs`.

Set ALLOWED_ORIGINS to serve a browser from another origin against it.
"""
import os
import sys
from pathlib import Path

os.environ["JWT_SECRET"] = "frontend-test-secret-frontend-test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend
from app.db import Base, get_db
from app.models import User
from app.security import hash_password
import app.services.search as svc

engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine, expire_on_commit=False)
with Session() as db:
    db.add(User(email="admin@lab.org", password_hash=hash_password("correct-horse-1"), is_admin=True))
    db.add(User(email="bob@lab.org", password_hash=hash_password("correct-horse-2")))
    db.commit()

def override():
    db = Session()
    try:
        yield db
    finally:
        db.close()
backend.app.dependency_overrides[get_db] = override

# Deliberately hostile fixtures: the titles and summaries below carry markup and
# script payloads, so the checks can prove the page renders them as text.
CAND = lambda acc, title, summary="s": {"accession": acc, "title": title, "summary": summary,
    "organism": "Homo sapiens", "n_samples": "12", "supplementary_files": "TAR",
    "ftp_link": f"ftp://ftp.ncbi.nlm.nih.gHOST/geo/series/{acc[:-3]}nnn/{acc}/".replace("gHOST", "gov")}
CANDS = [CAND("GSE1001", "Normal <b>bold</b> title"),
         CAND("GSE1002", '<img src=x onerror="window.__xss=1">'),
         CAND("GSE1003", "Third study")]
svc.generate_query_variants = lambda u: ["q"]
svc.fetch_candidates = lambda q: [dict(c) for c in CANDS]
svc.rank_candidates = lambda u, c: [
    {"accession": "GSE1001", "match_summary": "Great <script>window.__xss=2</script> match", "matched_conditions": ["cond <i>x</i>"],
     "meets_data_availability": True, "confidence": "high", "evidence": "…TLS <u>region</u>…"},
    {"accession": "GSE1002", "match_summary": "ok", "matched_conditions": [], "meets_data_availability": False, "confidence": "medium"},
    {"accession": "GSE1003", "match_summary": "meh", "matched_conditions": [], "meets_data_availability": False, "confidence": "low"},
]
uvicorn.run(backend.app, host="127.0.0.1", port=8765, log_level="warning")
