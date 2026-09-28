import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import SavedSearch, User
from app.schemas import SavedSearchCreate, SavedSearchOut

router = APIRouter(prefix="/saved-searches", tags=["saved-searches"])


@router.get("", response_model=list[SavedSearchOut])
def list_saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = (
        select(SavedSearch)
        .where(SavedSearch.user_id == user.id)
        .order_by(SavedSearch.created_at.desc())
    )
    return db.scalars(stmt).all()


@router.post("", response_model=SavedSearchOut, status_code=status.HTTP_201_CREATED)
def create_saved(
    body: SavedSearchCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    saved = SavedSearch(
        user_id=user.id,
        name=body.name,
        query=body.query.model_dump(),
        results=[r.model_dump() for r in body.results],
    )
    db.add(saved)
    db.commit()
    return saved


def _owned(db: Session, user: User, saved_id: uuid.UUID) -> SavedSearch:
    saved = db.get(SavedSearch, saved_id)
    # 404 (not 403) for other users' rows so ids can't be probed.
    if saved is None or saved.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved search not found")
    return saved


@router.get("/{saved_id}", response_model=SavedSearchOut)
def get_saved(
    saved_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _owned(db, user, saved_id)


@router.delete("/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved(
    saved_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    db.delete(_owned(db, user, saved_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
