from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc, desc

from database import engine, get_db
import models
from parser import parse_natural_language
from seed import run_seed

VALID_SORT_BY = {"age", "created_at", "gender_probability"}
VALID_ORDER = {"asc", "desc"}
VALID_GENDERS = {"male", "female"}
VALID_AGE_GROUPS = {"child", "teenager", "adult", "senior"}

SORT_COLUMNS = {
    "age": models.Profile.age,
    "created_at": models.Profile.created_at,
    "gender_probability": models.Profile.gender_probability,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    run_seed()
    yield


app = FastAPI(title="Insighta Labs Profile API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "Invalid query parameters"},
    )


def profile_to_dict(profile: models.Profile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "gender_probability": profile.gender_probability,
        "age": profile.age,
        "age_group": profile.age_group,
        "country_id": profile.country_id,
        "country_name": profile.country_name,
        "country_probability": profile.country_probability,
        "created_at": profile.created_at,
    }


def apply_filters(query, filters: dict):
    if filters.get("gender"):
        query = query.filter(models.Profile.gender == filters["gender"])
    if filters.get("age_group"):
        query = query.filter(models.Profile.age_group == filters["age_group"])
    if filters.get("country_id"):
        query = query.filter(models.Profile.country_id == filters["country_id"].upper())
    if filters.get("min_age") is not None:
        query = query.filter(models.Profile.age >= filters["min_age"])
    if filters.get("max_age") is not None:
        query = query.filter(models.Profile.age <= filters["max_age"])
    if filters.get("min_gender_probability") is not None:
        query = query.filter(models.Profile.gender_probability >= filters["min_gender_probability"])
    if filters.get("min_country_probability") is not None:
        query = query.filter(models.Profile.country_probability >= filters["min_country_probability"])
    return query


def apply_sort(query, sort_by: Optional[str], order: str):
    col = SORT_COLUMNS.get(sort_by, models.Profile.created_at)
    direction = asc if order == "asc" else desc
    return query.order_by(direction(col))


def paginated_response(query, page: int, limit: int) -> dict:
    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "status": "success",
        "page": page,
        "limit": limit,
        "total": total,
        "data": [profile_to_dict(p) for p in items],
    }


# ---------------------------------------------------------------------------
# GET /api/profiles/search  — must be declared BEFORE /api/profiles/{id}
# ---------------------------------------------------------------------------
@app.get("/api/profiles/search")
def search_profiles(
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    if not q or not q.strip():
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Missing or empty parameter: q"},
        )

    filters = parse_natural_language(q.strip())
    if filters is None:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Unable to interpret query"},
        )

    query = db.query(models.Profile)
    query = apply_filters(query, filters)
    query = apply_sort(query, "created_at", "asc")

    return JSONResponse(status_code=200, content=paginated_response(query, page, limit))


# ---------------------------------------------------------------------------
# GET /api/profiles
# ---------------------------------------------------------------------------
@app.get("/api/profiles")
def list_profiles(
    gender: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    min_age: Optional[int] = Query(default=None),
    max_age: Optional[int] = Query(default=None),
    min_gender_probability: Optional[float] = Query(default=None),
    min_country_probability: Optional[float] = Query(default=None),
    sort_by: Optional[str] = Query(default=None),
    order: str = Query(default="asc"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    # Semantic validation
    if gender is not None and gender not in VALID_GENDERS:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Invalid query parameters"},
        )
    if age_group is not None and age_group not in VALID_AGE_GROUPS:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Invalid query parameters"},
        )
    if sort_by is not None and sort_by not in VALID_SORT_BY:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Invalid query parameters"},
        )
    if order not in VALID_ORDER:
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Invalid query parameters"},
        )

    filters = {
        "gender": gender,
        "age_group": age_group,
        "country_id": country_id,
        "min_age": min_age,
        "max_age": max_age,
        "min_gender_probability": min_gender_probability,
        "min_country_probability": min_country_probability,
    }

    query = db.query(models.Profile)
    query = apply_filters(query, filters)
    query = apply_sort(query, sort_by, order)

    return JSONResponse(status_code=200, content=paginated_response(query, page, limit))


# ---------------------------------------------------------------------------
# GET /api/profiles/{profile_id}
# ---------------------------------------------------------------------------
@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if not profile:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Profile not found"},
        )
    return JSONResponse(status_code=200, content={"status": "success", "data": profile_to_dict(profile)})
