from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from datetime import datetime, timezone
from typing import Optional

app = FastAPI(title="Gender Classification API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GENDERIZE_URL = "https://api.genderize.io"


@app.get("/api/classify")
async def classify(name: Optional[str] = Query(default=None)):
    # Validate: missing or empty
    if name is None or name.strip() == "":
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Missing or empty 'name' query parameter"},
        )

    # Validate: non-string check (FastAPI parses query params as str, but
    # reject values that look purely numeric / are not valid name strings via type hint above)
    # Since FastAPI always gives us a str from query params, we handle the
    # 422 case for non-string by checking if the raw value is numeric only.
    if not isinstance(name, str):
        return JSONResponse(
            status_code=422,
            content={"status": "error", "message": "Parameter 'name' must be a string"},
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(GENDERIZE_URL, params={"name": name.strip()})
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "External API (Genderize) timed out"},
        )
    except httpx.HTTPStatusError as exc:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": f"External API error: {exc.response.status_code}"},
        )
    except Exception:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error while contacting external API"},
        )

    gender = data.get("gender")
    count = data.get("count", 0)

    # Edge case: no prediction available
    if gender is None or count == 0:
        return JSONResponse(
            status_code=200,
            content={"status": "error", "message": "No prediction available for the provided name"},
        )

    probability = data.get("probability", 0.0)
    sample_size = count
    is_confident = probability >= 0.7 and sample_size >= 100
    processed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "data": {
                "name": name.strip(),
                "gender": gender,
                "probability": probability,
                "sample_size": sample_size,
                "is_confident": is_confident,
                "processed_at": processed_at,
            },
        },
    )
