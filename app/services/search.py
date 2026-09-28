"""Search orchestration: cache lookup, live GEO fetch, AI ranking, result join.

Reuses the validated logic in prototype/search_prototype.py. The prototype's
`search()` returns only the ranker's output, so the orchestration is repeated
here to keep the candidate records around for the join (title, links, ...).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import SEARCH_CACHE_TTL_HOURS, SEARCH_CACHE_VERSION
from app.models import SearchCache
from app.schemas import SearchRequest, SearchResult
from prototype.search_prototype import (
    MAX_CANDIDATES_FOR_RANKING,
    fetch_candidates,
    generate_query_variants,
    rank_with_ai,
)

GEO_ACC_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={}"


def cache_key(req: SearchRequest) -> str:
    """Hash of everything that affects ranking. max_results is excluded: the
    full ranked list is cached and truncated per request."""
    normalized = {
        "methodology": req.methodology.lower(),
        "organism": req.organism.lower(),
        "tissue": req.tissue.lower(),
        "conditions": sorted(c.lower() for c in req.conditions),
        "data_availability": (req.data_availability or "").lower(),
        "version": SEARCH_CACHE_VERSION,
    }
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()


def _prototype_input(req: SearchRequest) -> dict:
    return {
        "methodology": req.methodology,
        "organism": req.organism,
        "tissue": req.tissue,
        "conditions": req.conditions,
        "data_availability": req.data_availability or "",
    }


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _join(ranked: list[dict], candidates: dict[str, dict]) -> list[SearchResult]:
    results = []
    for item in ranked:
        candidate = candidates.get(item.get("accession"))
        if candidate is None:
            continue  # the model returned an accession we never fetched
        links = []
        if candidate["ftp_link"]:
            links.append(candidate["ftp_link"])
            if candidate["supplementary_files"]:
                links.append(candidate["ftp_link"].rstrip("/") + "/suppl/")
        try:
            results.append(
                SearchResult(
                    accession=candidate["accession"],
                    title=candidate["title"],
                    organism=candidate["organism"],
                    n_samples=_to_int(candidate["n_samples"]),
                    confidence=item.get("confidence", "low"),
                    match_summary=item.get("match_summary", ""),
                    matched_conditions=item.get("matched_conditions", []),
                    meets_data_availability=bool(item.get("meets_data_availability")),
                    geo_url=GEO_ACC_URL.format(candidate["accession"]),
                    download_links=links,
                )
            )
        except ValueError:
            continue  # malformed ranker item (e.g. unknown confidence label)
    return results


def _run_live_search(req: SearchRequest) -> list[SearchResult]:
    user_input = _prototype_input(req)
    by_accession: dict[str, dict] = {}
    for query in generate_query_variants(user_input):
        for candidate in fetch_candidates(query):
            by_accession.setdefault(candidate["accession"], candidate)
    merged = dict(list(by_accession.items())[:MAX_CANDIDATES_FOR_RANKING])
    ranked = rank_with_ai(user_input, list(merged.values()))
    return _join(ranked, merged)


def search(db: Session, req: SearchRequest) -> tuple[list[SearchResult], datetime | None]:
    """Return (results, cached_at); cached_at is None for a live search."""
    key = cache_key(req)
    now = datetime.now(timezone.utc)

    row = db.get(SearchCache, key)
    if row is not None and _aware(row.expires_at) > now:
        results = [SearchResult.model_validate(r) for r in row.results]
        return results[: req.max_results], _aware(row.created_at)

    results = _run_live_search(req)
    payload = [r.model_dump() for r in results]
    expires = now + timedelta(hours=SEARCH_CACHE_TTL_HOURS)
    if row is None:
        db.add(SearchCache(cache_key=key, query=req.model_dump(exclude={"max_results"}),
                           results=payload, created_at=now, expires_at=expires))
    else:
        row.results, row.created_at, row.expires_at = payload, now, expires
    db.commit()
    return results[: req.max_results], None


def _aware(dt: datetime) -> datetime:
    # SQLite drops tzinfo on read; Postgres keeps it.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
