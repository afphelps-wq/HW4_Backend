import os

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-32")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import User
from app.security import hash_password
from backend import app

CANDIDATE = {
    "accession": "GSE1",
    "title": "Spatial atlas of PDAC",
    "summary": "...",
    "organism": "Homo sapiens",
    "n_samples": "12",
    "supplementary_files": "TAR",
    "ftp_link": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE1nnn/GSE1/",
}
RANKED = [
    {"accession": "GSE1", "match_summary": "Good match", "matched_conditions": ["a"],
     "meets_data_availability": True, "confidence": "high"},
    {"accession": "GSE_HALLUCINATED", "match_summary": "x", "matched_conditions": [],
     "meets_data_availability": False, "confidence": "low"},
    {"accession": "GSE1", "match_summary": "bad label", "matched_conditions": [],
     "meets_data_availability": False, "confidence": "very-high"},
]


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(session_factory):
    def _make(email="alice@lab.org", password="correct-horse-1", **kw):
        with session_factory() as db:
            db.add(User(email=email, password_hash=hash_password(password), **kw))
            db.commit()
    return _make


@pytest.fixture
def auth_headers(client, make_user):
    def _headers(email="alice@lab.org", password="correct-horse-1", **user_kw):
        make_user(email, password, **user_kw)
        token = client.post("/auth/login", json={"email": email, "password": password}).json()
        return {"Authorization": f"Bearer {token['access_token']}"}
    return _headers


@pytest.fixture
def stub_upstreams(monkeypatch):
    calls = {"live": 0}

    def fake_variants(user_input):
        calls["live"] += 1
        return ["q1", "q2"]

    monkeypatch.setattr("app.services.search.generate_query_variants", fake_variants)
    monkeypatch.setattr("app.services.search.fetch_candidates", lambda q: [dict(CANDIDATE)])
    monkeypatch.setattr("app.services.search.rank_with_ai", lambda u, c: RANKED)
    return calls


@pytest.fixture(autouse=True)
def block_live_upstreams(monkeypatch):
    """Tests must never reach NCBI/OpenAI (load_dotenv pulls in real keys)."""
    def blocked(*args, **kwargs):
        raise AssertionError("test attempted a live NCBI/OpenAI call")

    for name in ("generate_query_variants", "fetch_candidates", "rank_with_ai"):
        monkeypatch.setattr(f"app.services.search.{name}", blocked)
