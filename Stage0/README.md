# Stage 0 – Gender Classification API

A FastAPI-based REST API that classifies a name's likely gender by integrating with the [Genderize.io](https://genderize.io) API and returning a processed, enriched response.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
cd Stage0
pip install -r requirements.txt
```

### Running the Server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.

---

## 📡 Endpoint

### `GET /api/classify`

Classifies a name's gender using the Genderize API.

#### Query Parameters

| Parameter | Type   | Required | Description          |
| --------- | ------ | -------- | -------------------- |
| `name`    | string | Yes      | The name to classify |

#### Success Response (`200 OK`)

```json
{
  "status": "success",
  "data": {
    "name": "John",
    "gender": "male",
    "probability": 0.99,
    "sample_size": 1234,
    "is_confident": true,
    "processed_at": "2026-04-17T12:00:00Z"
  }
}
```

#### Error Responses

| Scenario                       | Status | Message                                               |
| ------------------------------ | ------ | ----------------------------------------------------- |
| Missing / empty `name`         | 400    | `Missing or empty 'name' query parameter`             |
| Non-string `name`              | 422    | `Parameter 'name' must be a string`                   |
| No gender prediction available | 200    | `No prediction available for the provided name`       |
| External API timeout           | 502    | `External API (Genderize) timed out`                  |
| External API HTTP error        | 502    | `External API error: <status_code>`                   |
| Internal server error          | 500    | `Internal server error while contacting external API` |

All errors follow the structure:

```json
{
  "status": "error",
  "message": "<error message>"
}
```

---

## ⚙️ Processing Logic

| Field          | Source / Rule                                                 |
| -------------- | ------------------------------------------------------------- |
| `gender`       | Directly from Genderize response                              |
| `probability`  | Directly from Genderize response                              |
| `sample_size`  | Renamed from `count` in Genderize response                    |
| `is_confident` | `true` when `probability >= 0.7` **AND** `sample_size >= 100` |
| `processed_at` | Generated per request — UTC, ISO 8601 format                  |

---

## 🌐 CORS

The API includes `Access-Control-Allow-Origin: *` to allow cross-origin requests from any client.

---

## 📁 Project Structure

```
Stage0/
├── main.py           # FastAPI application
├── requirements.txt  # Python dependencies
└── README.md         # This file
```

---

## 📝 Example Requests

```bash
# Successful classification
curl "http://localhost:8000/api/classify?name=James"

# Missing name (400)
curl "http://localhost:8000/api/classify"

# Empty name (400)
curl "http://localhost:8000/api/classify?name="
```

---

## 🔗 External API

This project uses [Genderize.io](https://genderize.io) — a simple API to predict the gender of a person based on their first name.
