# Insighta Labs Profile API — Stage 2

Advanced filtering, sorting, pagination, and natural language search over 2026 demographic profiles.

---

## Running the API

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

The database is created and seeded automatically on first startup. Re-running is idempotent.

To seed manually:

```bash
python seed.py
```

---

## Endpoints

### `GET /api/profiles`

Supports filtering, sorting, and pagination.

| Parameter | Type | Description |
|---|---|---|
| `gender` | string | `male` or `female` |
| `age_group` | string | `child`, `teenager`, `adult`, `senior` |
| `country_id` | string | ISO 3166-1 alpha-2 (e.g. `NG`) |
| `min_age` | int | Minimum age (inclusive) |
| `max_age` | int | Maximum age (inclusive) |
| `min_gender_probability` | float | Min confidence for gender |
| `min_country_probability` | float | Min confidence for country |
| `sort_by` | string | `age`, `created_at`, `gender_probability` |
| `order` | string | `asc` (default) or `desc` |
| `page` | int | Page number (default: 1) |
| `limit` | int | Results per page (default: 10, max: 50) |

### `GET /api/profiles/search?q=<query>`

Natural language search. Returns the same paginated format. Supports `page` and `limit`.

---

## Natural Language Parsing

### Approach

The parser (`parser.py`) uses regex-based rule matching — no AI or LLMs involved. The query string is lowercased and each pattern is independently tested.

### Supported keywords and mappings

**Gender**

| Input | Filter |
|---|---|
| `male`, `males`, `man`, `men` | `gender=male` |
| `female`, `females`, `woman`, `women`, `girl`, `girls` | `gender=female` |
| `male and female`, `female and male` | *(no gender filter)* |

**Age groups**

| Input | Filter |
|---|---|
| `child`, `children`, `kid`, `kids` | `age_group=child` |
| `teenager`, `teenagers`, `teen`, `teens`, `adolescent` | `age_group=teenager` |
| `adult`, `adults` | `age_group=adult` |
| `senior`, `seniors`, `elderly`, `elder`, `elders` | `age_group=senior` |

**"young" / "youth"**

Maps to `min_age=16` and `max_age=24`. Only applied when no explicit age group is present.

**Age constraints**

| Input pattern | Filter |
|---|---|
| `above N`, `over N`, `older than N` | `min_age=N` |
| `below N`, `under N`, `younger than N` | `max_age=N` |
| `between N and M` | `min_age=N`, `max_age=M` |

**Countries**

Country names are matched by substring (longest match first to handle multi-word names like "south africa" before "africa"). Both "from" and bare name references work:

- `"people from nigeria"` → `country_id=NG`
- `"adults in kenya"` → `country_id=KE`

Supported countries include all African nations plus major world countries (see `COUNTRY_NAME_TO_CODE` in `parser.py`).

### Parsing logic

1. Detect "male and female" → skip gender filter
2. Match gender keywords → set `gender`
3. Match age group keywords → set `age_group`
4. Match "young"/"youth" (only if no age_group matched) → set `min_age=16`, `max_age=24`
5. Match numeric age patterns → set `min_age` / `max_age`
6. Match country names (longest first) → set `country_id`
7. If no filters were extracted → return `{"status": "error", "message": "Unable to interpret query"}`

### Example mappings

| Query | Extracted filters |
|---|---|
| `young males` | `gender=male, min_age=16, max_age=24` |
| `females above 30` | `gender=female, min_age=30` |
| `people from angola` | `country_id=AO` |
| `adult males from kenya` | `gender=male, age_group=adult, country_id=KE` |
| `male and female teenagers above 17` | `age_group=teenager, min_age=17` |
| `seniors from nigeria` | `age_group=senior, country_id=NG` |
| `women between 25 and 40` | `gender=female, min_age=25, max_age=40` |

---

## Limitations

- **No synonyms beyond the listed keywords.** Phrases like "grown ups", "young adults", "middle-aged" are not recognized.
- **"young" conflicts with explicit age groups.** "Young adults" keeps `age_group=adult` and ignores the young age range.
- **Country detection is name-based.** Demonyms ("Nigerians", "Kenyans") are not supported. Only country names are matched.
- **No negation.** "Not from Nigeria", "excluding males" are not handled.
- **No compound age ranges with "and".** "above 20 and below 40" is not supported — use `between 20 and 40` instead.
- **"young" upper bound is fixed at 24.** Combining `young` with `above 20` produces `min_age=20` (explicit value overrides the young range's min).
- **Case and spelling.** Queries are lowercased before parsing but typos or abbreviations are not corrected.
- **Ambiguous country names.** "Guinea" resolves to Guinea (GN), not Guinea-Bissau or Equatorial Guinea (longest match takes priority).

---

## Error responses

All errors follow:

```json
{ "status": "error", "message": "<error message>" }
```

| Status | Meaning |
|---|---|
| 400 | Missing or empty `q` parameter |
| 422 | Invalid parameter type or uninterpretable query |
| 404 | Profile not found |
