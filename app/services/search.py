"""Search orchestration: cache lookup, live GEO fetch, AI ranking, result join.

Reuses the validated logic in prototype/search_prototype.py. The prototype's
`search()` returns only the ranker's output, so the orchestration is repeated
here to keep the candidate records around for the join (title, links, ...).
"""

import hashlib
import json
import logging
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

log = logging.getLogger(__name__)

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
        accession = item.get("accession")
        candidate = candidates.get(accession)
        if candidate is None:
            log.warning("Dropped ranker item %r: accession not in fetched candidates", accession)
            continue
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
                    confidence=str(item.get("confidence", "low")).strip().lower(),
                    match_summary=item.get("match_summary", ""),
                    matched_conditions=item.get("matched_conditions", []),
                    meets_data_availability=bool(item.get("meets_data_availability")),
                    geo_url=GEO_ACC_URL.format(candidate["accession"]),
                    download_links=links,
                )
            )
        except ValueError as exc:
            # pydantic's ValidationError is a ValueError
            log.warning("Dropped ranker item %s: malformed (%s)",
                        accession, str(exc).replace("\n", " | "))
    return results


def _run_live_search(req: SearchRequest) -> list[SearchResult]:
    user_input = _prototype_input(req)
    variants = generate_query_variants(user_input)
    log.info("Query variants: %s", variants)
    by_accession: dict[str, dict] = {}
    for query in variants:
        found = fetch_candidates(query)
        log.info("Query %r returned %d GSE candidates", query, len(found))
        for candidate in found:
            by_accession.setdefault(candidate["accession"], candidate)
    merged = dict(list(by_accession.items())[:MAX_CANDIDATES_FOR_RANKING])
    log.info("Merged %d unique candidates, sending %d to ranker: %s",
             len(by_accession), len(merged), ", ".join(merged))
    ranked = rank_with_ai(user_input, list(merged.values()))
    results = _join(ranked, merged)
    log.info("Ranker returned %d items, kept %d: %s", len(ranked), len(results),
             ", ".join(r.accession for r in results))
    return results


def search(
    db: Session, req: SearchRequest, refresh: bool = False
) -> tuple[list[SearchResult], datetime | None]:
    """Return (results, cached_at); cached_at is None for a live search.

    refresh=True skips the cache read and overwrites the cached entry."""
    key = cache_key(req)
    now = datetime.now(timezone.utc)

    row = db.get(SearchCache, key)
    if not refresh and row is not None and _aware(row.expires_at) > now:
        results = [SearchResult.model_validate(r) for r in row.results]
        return results[: req.max_results], _aware(row.created_at)

    results = _run_live_search(req)
    if not results:
        # An empty ranking is likelier a transient/noisy miss than a true
        # "nothing exists"; don't pin it for the whole TTL. (An existing
        # cached entry is likewise kept rather than overwritten with nothing.)
        log.warning("Search produced no results; not caching")
        return results, None

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
