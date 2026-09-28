import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator


def _text(max_length: int):
    # strip_whitespace runs before min_length, so "   " is rejected.
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


class SearchRequest(BaseModel):
    methodology: _text(200)
    organism: _text(100)
    tissue: _text(200)
    conditions: list[_text(300)] = Field(default_factory=list, max_length=10)
    data_availability: str | None = Field(default=None, max_length=500)
    max_results: int = Field(default=10, ge=1, le=20)

    @field_validator("data_availability")
    @classmethod
    def blank_to_none(cls, v: str | None) -> str | None:
        v = v.strip() if v else v
        return v or None


class SearchResult(BaseModel):
    accession: str
    title: str
    organism: str
    n_samples: int | None = None
    confidence: Literal["high", "medium", "low"]
    match_summary: str
    matched_conditions: list[str] = Field(default_factory=list)
    meets_data_availability: bool
    geo_url: str
    download_links: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    cached: bool
    cached_at: datetime | None = None
    results: list[SearchResult]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool
    created_at: datetime


class SavedSearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: SearchRequest
    results: list[SearchResult]


class SavedSearchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    query: SearchRequest
    results: list[SearchResult]
    created_at: datetime
