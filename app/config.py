import os

from dotenv import load_dotenv

load_dotenv()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "60"))
SEARCH_CACHE_TTL_HOURS = int(os.environ.get("SEARCH_CACHE_TTL_HOURS", "24"))
# Bump when the ranking prompt/model changes so stale cached results aren't served.
SEARCH_CACHE_VERSION = "v1"


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
