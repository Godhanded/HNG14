# Stage 1 – Profile Intelligence Service

A FastAPI-based REST API that enriches a name using three external APIs (Genderize, Agify, Nationalize), persists the result in a SQLite database, and exposes clean RESTful endpoints for profile management.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
cd Stage1
python -m venv venv
.\venv\Scripts\Activate.ps1       # Windows PowerShell
# source venv/bin/activate         # macOS/Linux

pip install -r requirements.txt
```

### Running the Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

---

## 📡 Endpoints

### `POST /api/profiles`

Creates a new profile by enriching the given name via external APIs.

**Request body:**

```json
{ "name": "ella" }
```

**Success (201):**

```json
{
  "status": "success",
  "data": {
    "id": "b3f9c1e2-7d4a-4c91-9c2a-1f0a8e5b6d12",
    "name": "ella",
    "gender": "female",
    "gender_probability": 0.99,
    "sample_size": 1234,
    "age": 46,
    "age_group": "adult",
    "country_id": "DRC",
    "country_probability": 0.85,
    "created_at": "2026-04-01T12:00:00Z"
  }
}
```

**Idempotent — duplicate name (200):**

```json
{
  "status": "success",
  "message": "Profile already exists",
  "data": { "...existing profile..." }
}
```

---

### `GET /api/profiles`

Returns all stored profiles with optional case-insensitive filters.

**Query params:** `gender`, `country_id`, `age_group`

```
GET /api/profiles?gender=male&country_id=NG
```

**Success (200):**

```json
{
  "status": "success",
  "count": 2,
  "data": [
    {
      "id": "...",
      "name": "emmanuel",
      "gender": "male",
      "age": 25,
      "age_group": "adult",
      "country_id": "NG"
    }
  ]
}
```

---

### `GET /api/profiles/{id}`

Returns a single profile by UUID.

**Success (200):** Full profile object.  
**Not Found (404):** `{ "status": "error", "message": "Profile not found" }`

---

### `DELETE /api/profiles/{id}`

Deletes a profile by UUID.  
**Success:** `204 No Content`  
**Not Found (404):** `{ "status": "error", "message": "Profile not found" }`

---

## ⚙️ Processing Logic

| Field                 | Source / Rule                                                  |
| --------------------- | -------------------------------------------------------------- |
| `gender`              | From Genderize                                                 |
| `gender_probability`  | From Genderize                                                 |
| `sample_size`         | Renamed from `count` in Genderize response                     |
| `age`                 | From Agify                                                     |
| `age_group`           | 0–12 → child · 13–19 → teenager · 20–59 → adult · 60+ → senior |
| `country_id`          | Highest-probability country from Nationalize                   |
| `country_probability` | Probability of the top country                                 |
| `id`                  | UUID v7 (time-ordered)                                         |
| `created_at`          | UTC ISO 8601, generated at request time                        |

---

## 🛡️ Error Handling

| Scenario                     | Status | Message                                    |
| ---------------------------- | ------ | ------------------------------------------ |
| Missing / empty `name`       | 400    | `Missing or empty 'name' field`            |
| Non-string `name`            | 422    | `Field 'name' must be a string`            |
| Profile not found            | 404    | `Profile not found`                        |
| Genderize invalid response   | 502    | `Genderize returned an invalid response`   |
| Agify invalid response       | 502    | `Agify returned an invalid response`       |
| Nationalize invalid response | 502    | `Nationalize returned an invalid response` |

All errors follow: `{ "status": "error", "message": "<message>" }`

---

## 🌐 CORS

`Access-Control-Allow-Origin: *` is enabled for all routes.

---

## 📁 Project Structure

```
Stage1/
├── main.py           # FastAPI application & all endpoints
├── models.py         # SQLAlchemy ORM model
├── database.py       # DB engine, session, Base
├── utils.py          # UUID v7 generator, age group classifier
├── requirements.txt  # Python dependencies
├── profiles.db       # SQLite database (auto-created on first run)
└── README.md         # This file
```

---

## 🔗 External APIs Used

| API            | URL                                      | Data Extracted                    |
| -------------- | ---------------------------------------- | --------------------------------- |
| Genderize.io   | `https://api.genderize.io?name={name}`   | gender, probability, count        |
| Agify.io       | `https://api.agify.io?name={name}`       | age                               |
| Nationalize.io | `https://api.nationalize.io?name={name}` | country list (top by probability) |
