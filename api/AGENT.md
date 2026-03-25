# api/ — AGENT.md
## FastAPI Service Layer

---

## PURPOSE

The `api/` layer exposes DYNAFIT's pipeline as an HTTP service. It handles run lifecycle management (create, status, results), human review interactions, and webhook notifications.

**The API is thin.** It validates requests, dispatches to the pipeline, and returns results. No business logic lives here.

---

## ENDPOINTS

### `POST /runs` — Start a new fitment run
```
Request:
  - files: List[UploadFile] (multipart)
  - wave_id: str (form field)
  - skip_human_review: bool = False (for testing only; rejected in prod)

Response:
  {
    "run_id": "uuid",
    "status": "QUEUED",
    "created_at": "ISO datetime",
    "estimated_atoms": int | null
  }
```

**Implementation**: Saves uploaded files to temp storage, enqueues Celery task, returns immediately. Never run pipeline synchronously in the API thread.

### `GET /runs/{run_id}` — Poll run status
```
Response:
  {
    "run_id": "uuid",
    "status": "QUEUED|RUNNING|AWAITING_REVIEW|COMPLETED|FAILED",
    "phase_completed": "ingestion|retrieval|matching|classification|validation",
    "atoms_processed": int,
    "atoms_total": int,
    "llm_cost_usd": float,
    "error_count": int,
    "output_url": str | null  # populated when COMPLETED
  }
```

### `GET /runs/{run_id}/review` — Get items needing human review
```
Response:
  {
    "run_id": "uuid",
    "items_for_review": [
      {
        "atom_id": "uuid",
        "requirement_text": str,
        "module": str,
        "ai_verdict": "FIT|PARTIAL_FIT|GAP",
        "ai_confidence": float,
        "ai_rationale": str,
        "sanity_flags": List[str],
        "top_capabilities": List[{name, score}]
      }
    ]
  }
```

### `PATCH /runs/{run_id}/review` — Submit review decisions
```
Request:
  {
    "decisions": [
      {
        "atom_id": "uuid",
        "verdict": "FIT|PARTIAL_FIT|GAP",  # Can match AI or override
        "reason": str  # Required if overriding AI verdict; min 10 chars
      }
    ]
  }

Response:
  { "accepted": int, "rejected": int, "errors": List[dict] }
```

After all review items decided, resumes LangGraph from interrupt.

### `GET /runs/{run_id}/output` — Download fitment matrix
```
Response: Streaming Excel file download
Content-Disposition: attachment; filename="fitment_matrix_{run_id}.xlsx"
```

### `GET /health` — Health check
```
Response:
  {
    "status": "healthy|degraded|unhealthy",
    "infrastructure": {
      "qdrant": bool,
      "postgres": bool, 
      "redis": bool,
      "embedder": bool
    }
  }
```

---

## MIDDLEWARE

### Auth (`middleware.py`)
- Bearer token authentication on all `/runs` endpoints
- Token validated against `api_keys` table in Postgres
- Include `user_id` in all structlog contexts after auth
- `/health` endpoint is unauthenticated

### Rate Limiting
- 10 runs per hour per API key (configurable per key in DB)
- Rate limit state in Redis
- 429 response with `Retry-After` header

### Request ID
- Every request gets a `X-Request-ID` header (UUID)
- Injected into structlog context for trace correlation
- Returned in response headers

---

## SECURITY RULES

1. **Never log file contents** — only filenames and sizes
2. **Uploaded files stored in** `settings.UPLOAD_DIR` (not in-memory for large files)
3. **File type validation**: Only accept `.xlsx`, `.xls`, `.docx`, `.pdf`, `.txt`
4. **Max file size**: `settings.MAX_UPLOAD_SIZE_MB` (default: 50MB)
5. **`skip_human_review`** must be explicitly blocked in production env:
   ```python
   if settings.ENVIRONMENT == "production" and request.skip_human_review:
       raise HTTPException(400, "skip_human_review not allowed in production")
   ```
6. **Rate limit by API key**, not IP (API keys are assignable, IPs are not)