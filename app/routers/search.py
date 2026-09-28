import logging

import openai
import requests
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import SearchRequest, SearchResponse
from app.services import search as search_service

router = APIRouter(tags=["search"])
log = logging.getLogger(__name__)


# Plain `def` so FastAPI runs it in a worker thread -- the search makes several
# blocking NCBI/OpenAI calls.
@router.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest,
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """`refresh=true` (admin only) bypasses the cache and overwrites the entry."""
    if refresh and not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "refresh is admin-only")
    try:
        results, cached_at = search_service.search(db, body, refresh=refresh)
    except (openai.OpenAIError, requests.RequestException) as exc:
        log.exception("Upstream failure during search")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Upstream search provider failed; try again shortly"
        ) from exc
    return SearchResponse(cached=cached_at is not None, cached_at=cached_at, results=results)
