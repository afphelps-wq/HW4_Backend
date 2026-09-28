import os

from dotenv import load_dotenv

load_dotenv()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "60"))
SEARCH_CACHE_TTL_HOURS = int(os.environ.get("SEARCH_CACHE_TTL_HOURS", "24"))
# Bump when the ranking prompt/model/candidate pipeline changes so stale cached
# results aren't served.
SEARCH_CACHE_VERSION = "v3"
# Candidates sent to the AI ranker per search (~420 tokens each). The prototype
# used 40, but a known-good match (GSE277116) only ranks ~25th within the one
# query variant that finds it, so a cap of 40 across merged variants drops it.
MAX_CANDIDATES_FOR_RANKING = int(os.environ.get("MAX_CANDIDATES_FOR_RANKING", "100"))
RANKING_MODEL = os.environ.get("RANKING_MODEL", "gpt-4o-mini")
# The ranker judges candidates in batches this size. A single call over ~80-100
# candidates made gpt-4o-mini skip most of them (it returned 2-6 results and
# usually missed GSE277116); batches of 20 gave 100% coverage in testing.
RANKING_BATCH_SIZE = int(os.environ.get("RANKING_BATCH_SIZE", "20"))


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url.startswith(("postgres://", "postgresql://", "postgresql+")):
        raise RuntimeError(
            "DATABASE_URL is missing or not a Postgres URL "
            "(expected postgresql://user:password@host/dbname)"
        )
    # Render hands out postgres:// or postgresql:// URLs; SQLAlchemy needs the
    # driver spelled out to use psycopg 3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET is not set")
    return secret
