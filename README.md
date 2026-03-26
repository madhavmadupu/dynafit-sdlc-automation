# DYNAFIT — D365 F&O Requirement Fitment Engine

AI-powered multi-agent system that automates fitment analysis of business requirements against Microsoft Dynamics 365 Finance & Operations standard capabilities.

DYNAFIT reduces manual fitment analysis from **weeks to hours** — producing auditable, consistent decisions with LLM-generated rationale and confidence scores.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Frontend](#frontend)
- [Testing](#testing)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [License](#license)

---

## How It Works

Upload a Business Requirements Document (BRD) in Excel, Word, or PDF format. DYNAFIT runs a 5-phase AI pipeline and produces a `fitment_matrix.xlsx` classifying every requirement as:

| Verdict | Meaning |
|---|---|
| **FIT** | Covered out-of-the-box by D365 F&O |
| **PARTIAL FIT** | Achievable with configuration or minor customization |
| **GAP** | Requires custom development |

Each verdict includes a confidence score (0–1), matched D365 capability, rationale, and full audit trail.

### Pipeline Phases

```
Raw Documents (Excel / Word / PDF)
        │
        ▼
┌─────────────────────────────────┐
│  Phase 1 · Ingestion Agent      │  Parse documents, extract & deduplicate
│                                 │  requirement atoms, normalize terminology
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│  Phase 2 · Retrieval Agent      │  RAG across 3 knowledge sources:
│                                 │  D365 KB · MS Learn · Historical Fitments
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│  Phase 3 · Matching Agent       │  Semantic scoring, confidence bands,
│                                 │  fast-track / soft-gap routing
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│  Phase 4 · Classification Agent │  LLM chain-of-thought reasoning
│                                 │  (Claude) for FIT / PARTIAL / GAP
└────────────┬────────────────────┘
             ▼
┌─────────────────────────────────┐
│  Phase 5 · Validation Agent     │  Human-in-the-loop review,
│                                 │  conflict detection, Excel export
└─────────────────────────────────┘
```

---

## Architecture

### Multi-Agent Orchestration

Built on **LangGraph StateGraph** — each phase is a graph node with typed state flowing through the pipeline. A `RequirementState` dict is the single source of truth across all agents.

- **Checkpointing** — Every run gets a unique thread ID for reproducibility and resume
- **Human-in-the-loop** — Phase 5 uses `interrupt()` to pause for consultant review before finalizing
- **Smart routing** — Phase 3 routes high-confidence matches to fast-track (no LLM cost) and obvious gaps to soft-gap, reserving LLM calls for ambiguous cases

### Retrieval Strategy

Phase 2 fans out to three knowledge sources in parallel:

| Source | Backend | Method |
|---|---|---|
| D365 Capability KB | Qdrant | Vector (bge-large cosine) + BM25, module-filtered |
| MS Learn Corpus | Qdrant | Semantic search |
| Historical Fitments | PostgreSQL + pgvector | Exact hash match OR similarity > 0.75 |

Results are fused via **Reciprocal Rank Fusion** (k=60), then reranked by a **CrossEncoder** (`ms-marco-MiniLM-L-6-v2`) to produce top-5 candidates per requirement.

### Cost Controls

- **Fast-track routing** skips LLM for high-confidence matches (composite >= 0.85)
- **Soft-gap routing** skips LLM for obvious gaps (composite < 0.40, no candidates)
- **Pre-flight cost guard** estimates token usage via tiktoken and aborts if projected cost exceeds `MAX_LLM_COST_USD_PER_RUN` (default: $5.00)

---

## Tech Stack

### Backend

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| API Framework | FastAPI |
| Agent Orchestration | LangGraph + LangChain |
| LLM | Anthropic Claude (via langchain-anthropic) |
| Embeddings | sentence-transformers (bge-large-en-v1.5) |
| Reranking | CrossEncoder (ms-marco-MiniLM-L-6-v2) |
| Vector DB | Qdrant |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis 7 |
| Task Queue | Celery |
| Observability | structlog + Prometheus |

### Frontend

| Component | Technology |
|---|---|
| Framework | Next.js 16 |
| Language | TypeScript 5 |
| UI Components | shadcn/ui (Radix UI) |
| State Management | Zustand |
| Styling | Tailwind CSS 4 |
| Charts | Recharts |
| Animations | Framer Motion |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 22+
- Docker & Docker Compose

### 1. Clone and configure

```bash
git clone https://github.com/your-org/dynafit-sdlc-automation.git
cd dynafit-sdlc-automation
cp .env.example .env
```

Edit `.env` and set your API keys:

```env
ANTHROPIC_API_KEY=your_key_here
LANGCHAIN_API_KEY=your_key_here      # optional, for LangSmith tracing
```

### 2. Start infrastructure

```bash
docker compose up -d
```

This provisions PostgreSQL (with pgvector), Redis, and Qdrant.

### 3. Install backend

```bash
pip install -e ".[dev]"
python scripts/setup_postgres.py
python scripts/setup_qdrant.py
```

### 4. Install frontend

```bash
cd ui
npm install
cd ..
```

### 5. Run

```bash
# Backend (port 8000)
python main.py run

# Frontend (port 3000) — in a separate terminal
cd ui && npm run dev
```

Open **http://localhost:3000** for the UI, or **http://localhost:8000/docs** for the Swagger API.

---

## API Reference

Base URL: `/api/v1`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/runs` | Upload BRD files, start pipeline |
| `GET` | `/runs/{run_id}/stream` | SSE stream for real-time phase progress |
| `GET` | `/runs/{run_id}/status` | Current pipeline status and phase stats |
| `GET` | `/runs/{run_id}/results` | Full results (atoms, classifications, cost) |
| `GET` | `/runs/{run_id}/review` | Items flagged for human review |
| `PATCH` | `/runs/{run_id}/review` | Submit consultant overrides, resume pipeline |
| `GET` | `/runs/{run_id}/export` | Download fitment_matrix.xlsx |
| `GET` | `/health` | Health check |

### Example: Start a run

```bash
curl -X POST http://localhost:8000/api/v1/runs \
  -H "API-Key: your_api_key" \
  -F "files=@requirements.xlsx"
```

### Example: Stream progress

```bash
curl -N http://localhost:8000/api/v1/runs/{run_id}/stream \
  -H "API-Key: your_api_key"
```

---

## Frontend

The Next.js UI provides a phase-by-phase dashboard with:

- **File upload** — Drag-and-drop BRD documents
- **Live progress** — Real-time SSE streaming of pipeline phases
- **Review interface** — Inspect flagged requirements, submit consultant overrides
- **Results dashboard** — Verdict distribution charts, confidence breakdowns, module summaries
- **Export** — Download the final fitment matrix

---

## Testing

```bash
# Run all tests
pytest

# Unit tests only
pytest -m unit

# With coverage
pytest --cov --cov-report=html

# Parallel execution
pytest -n auto
```

**Test markers:** `unit`, `integration`, `e2e`, `eval`, `slow`

**Coverage minimum:** 85% (enforced in `pyproject.toml`)

### Linting

```bash
ruff check .            # Lint
ruff format --check .   # Format check
mypy agents core infrastructure api   # Type check
```

---

## Configuration

All configuration is driven by environment variables (loaded via Pydantic Settings).

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required) |
| `CLASSIFICATION_MODEL` | `claude-sonnet-4-6` | LLM model for classification |
| `MAX_LLM_COST_USD_PER_RUN` | `5.00` | Cost guard per pipeline run |
| `QDRANT_HOST` | `localhost` | Qdrant vector DB host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `POSTGRES_URL` | — | Async PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `API_KEY` | — | API authentication key |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LANGCHAIN_API_KEY` | — | LangSmith tracing (optional) |

Per-module thresholds and terminology mappings are configured in `core/config/module_config/*.yaml`.

---

## Project Structure

```
dynafit-sdlc-automation/
├── main.py                             # Application entry point
├── pyproject.toml                      # Dependencies & tooling config
├── docker-compose.yml                  # PostgreSQL + Redis + Qdrant
├── .env.example                        # Environment variable template
│
├── agents/                             # Multi-agent pipeline
│   ├── ingestion/                      # Phase 1: Document parsing & atomization
│   ├── retrieval/                      # Phase 2: RAG across 3 knowledge sources
│   ├── matching/                       # Phase 3: Semantic scoring & routing
│   ├── classification/                 # Phase 4: LLM-based classification
│   └── validation/                     # Phase 5: Review, conflicts & export
│
├── core/                               # Shared modules
│   ├── state/                          # LangGraph orchestration & state
│   ├── schemas/                        # Pydantic v2 data models
│   ├── config/                         # Settings, thresholds, module configs
│   └── prompts/                        # Jinja2 LLM prompt templates
│
├── infrastructure/                     # External service clients
│   ├── llm/                            # Anthropic Claude wrapper
│   ├── vector_db/                      # Qdrant, pgvector, embeddings
│   └── storage/                        # PostgreSQL, Redis
│
├── api/                                # FastAPI REST layer
│   ├── server.py                       # App factory & lifecycle
│   ├── routes.py                       # API endpoints
│   └── dependencies.py                 # Dependency injection
│
├── knowledge_base/                     # D365 capabilities catalog
├── ui/                                 # Next.js frontend
├── scripts/                            # Setup & utility scripts
├── tests/                              # Test suite
├── docs/                               # Documentation
└── .github/workflows/ci.yml           # CI pipeline
```

---

## License

Proprietary. All rights reserved.
