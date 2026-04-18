import asyncio
from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional, Any
import httpx
from datetime import datetime, timezone

from database import engine, get_db
import models
from Stage1.Backend.utils import generate_uuid7, classify_age_group

# Create tables on startup
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Profile Intelligence Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

GENDERIZE_URL = "https://api.genderize.io"
AGIFY_URL = "https://api.agify.io"
NATIONALIZE_URL = "https://api.nationalize.io"


class ProfileCreateRequest(BaseModel):
    name: Any = None  # Accept any type so we can return 422 for non-strings ourselves


def profile_to_dict(profile: models.Profile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "gender_probability": profile.gender_probability,
        "sample_size": profile.sample_size,
        "age": profile.age,
        "age_group": profile.age_group,
        "country_id": profile.country_id,
        "country_probability": profile.country_probability,
        "created_at": profile.created_at,
    }


def profile_to_list_dict(profile: models.Profile) -> dict:
    return {
        "id": profile.id,
        "name": profile.name,
        "gender": profile.gender,
        "age": profile.age,
        "age_group": profile.age_group,
        "country_id": profile.country_id,
    }


# ---------------------------------------------------------------------------
# POST /api/profiles
# ---------------------------------------------------------------------------
@app.post("/api/profiles")
async def create_profile(payload: ProfileCreateRequest, db: Session = Depends(get_db)):
    name = payload.name

    # Validate: missing or empty
    if name is None or (isinstance(name, str) and name.strip() == ""):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Missing or empty 'name' field"},
        )

    # Validate: non-string type
    if not isinstance(name, str):
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Field 'name' must be a string"},
        )

    name = name.strip().lower()

    # Idempotency check
    existing = db.query(models.Profile).filter(models.Profile.name == name).first()
    if existing:
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Profile already exists",
                "data": profile_to_dict(existing),
            },
        )

    # Call all three external APIs concurrently
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            gender_res, age_res, nation_res = await asyncio.gather(
                client.get(GENDERIZE_URL, params={"name": name}),
                client.get(AGIFY_URL, params={"name": name}),
                client.get(NATIONALIZE_URL, params={"name": name}),
            )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "An external API timed out"},
        )
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "Failed to reach external APIs"},
        )

    # --- Genderize ---
    try:
        g_data = gender_res.json()
        gender = g_data.get("gender")
        count = g_data.get("count", 0)
        if gender is None or count == 0:
            return JSONResponse(
                status_code=502,
                content={"status": "502", "message": "Genderize returned an invalid response"},
            )
        gender_probability = g_data.get("probability", 0.0)
        sample_size = count
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"status": "502", "message": "Genderize returned an invalid response"},
        )

    # --- Agify ---
    try:
        a_data = age_res.json()
        age = a_data.get("age")
        if age is None:
            return JSONResponse(
                status_code=502,
                content={"status": "502", "message": "Agify returned an invalid response"},
            )
        age_group = classify_age_group(age)
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"status": "502", "message": "Agify returned an invalid response"},
        )

    # --- Nationalize ---
    try:
        n_data = nation_res.json()
        countries = n_data.get("country", [])
        if not countries:
            return JSONResponse(
                status_code=502,
                content={"status": "502", "message": "Nationalize returned an invalid response"},
            )
        top_country = max(countries, key=lambda c: c.get("probability", 0))
        country_id = top_country.get("country_id")
        country_probability = top_country.get("probability")
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"status": "502", "message": "Nationalize returned an invalid response"},
        )

    # Persist
    profile = models.Profile(
        id=generate_uuid7(),
        name=name,
        gender=gender,
        gender_probability=gender_probability,
        sample_size=sample_size,
        age=age,
        age_group=age_group,
        country_id=country_id,
        country_probability=country_probability,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return JSONResponse(
        status_code=201,
        content={"status": "success", "data": profile_to_dict(profile)},
    )


# ---------------------------------------------------------------------------
# GET /api/profiles
# ---------------------------------------------------------------------------
@app.get("/api/profiles")
def list_profiles(
    gender: Optional[str] = Query(default=None),
    country_id: Optional[str] = Query(default=None),
    age_group: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = db.query(models.Profile)

    if gender:
        query = query.filter(models.Profile.gender.ilike(gender))
    if country_id:
        query = query.filter(models.Profile.country_id.ilike(country_id))
    if age_group:
        query = query.filter(models.Profile.age_group.ilike(age_group))

    profiles = query.all()
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "count": len(profiles),
            "data": [profile_to_list_dict(p) for p in profiles],
        },
    )


# ---------------------------------------------------------------------------
# GET /api/profiles/{id}
# ---------------------------------------------------------------------------
@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if not profile:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Profile not found"},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "success", "data": profile_to_dict(profile)},
    )


# ---------------------------------------------------------------------------
# DELETE /api/profiles/{id}
# ---------------------------------------------------------------------------
@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: str, db: Session = Depends(get_db)):
    profile = db.query(models.Profile).filter(models.Profile.id == profile_id).first()
    if not profile:
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": "Profile not found"},
        )
    db.delete(profile)
    db.commit()
    return Response(status_code=204)
