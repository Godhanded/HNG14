"""
Seed the database with profiles from seed_profiles.json.
Run with: python seed.py
Re-running is safe — duplicates are ignored via the UNIQUE constraint on name.
"""
import json
import os
import sys
from datetime import datetime, timezone

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# Allow running as a standalone script from within the Backend directory
sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal, engine
import models
from utils import generate_uuid7

SEED_FILE = os.path.join(os.path.dirname(__file__), "seed_profiles.json")


def run_seed():
    models.Base.metadata.create_all(bind=engine)

    with open(SEED_FILE, encoding="utf-8") as f:
        data = json.load(f)

    profiles = data.get("profiles", data) if isinstance(data, dict) else data

    db = SessionLocal()
    inserted = 0
    skipped = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        for p in profiles:
            stmt = (
                sqlite_insert(models.Profile)
                .values(
                    id=generate_uuid7(),
                    name=p["name"],
                    gender=p.get("gender"),
                    gender_probability=p.get("gender_probability"),
                    age=p.get("age"),
                    age_group=p.get("age_group"),
                    country_id=p.get("country_id"),
                    country_name=p.get("country_name"),
                    country_probability=p.get("country_probability"),
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["name"])
            )
            result = db.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped += 1

        db.commit()
        print(f"Seed complete: {inserted} inserted, {skipped} skipped.")
    except Exception as exc:
        db.rollback()
        print(f"Seed failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
