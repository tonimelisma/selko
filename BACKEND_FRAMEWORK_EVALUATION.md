# Python Backend Framework Evaluation for Selko

**Date:** 2026-01-22
**Context:** POC phase, solo developer, need APIs + background workers
**Current State:** Basic Python services with Supabase integration

## Requirements Summary

### Must Have
- ✅ REST APIs for web/mobile/CLI clients
- ✅ Background job queue processing
- ✅ Integration with Supabase (PostgreSQL + Storage)
- ✅ Quick setup for solo developer
- ✅ Good observability (logging, monitoring)
- ✅ Testing support

### Nice to Have
- Async support for better performance
- OpenAPI/Swagger documentation
- Type safety (works with existing type hints)
- Low operational overhead
- Easy deployment
- Polling mechanism support

### Constraints
- Solo developer (prioritize simplicity)
- POC phase (can change later, but prefer production-ready)
- Already using: Python 3.12+, Supabase, `uv` package manager

---

## Evaluation Criteria

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **Developer Velocity** | 10 | Time from zero to working API |
| **Learning Curve** | 9 | Ease of learning for solo dev |
| **API Development** | 10 | REST API ergonomics, auto-docs |
| **Job Queue Integration** | 9 | Built-in or easy integration with task queues |
| **Observability** | 8 | Logging, metrics, tracing, debugging |
| **Production Ready** | 8 | Stability, performance, battle-tested |
| **Community/Ecosystem** | 7 | Libraries, tutorials, Stack Overflow help |
| **Type Safety** | 7 | Support for type hints, validation |
| **Testing Support** | 8 | Built-in test client, fixtures |
| **Deployment Simplicity** | 7 | Easy to containerize and deploy |
| **Documentation** | 7 | Quality and completeness of docs |
| **Supabase Compatibility** | 6 | Works well with Supabase client |
| **Scalability** | 6 | Can grow beyond POC (async, horizontal scaling) |
| **Maintenance Overhead** | 8 | Amount of config/boilerplate needed |

**Scoring:** 1-10 scale (10 = best)

---

## Framework Options

### 1. FastAPI ⭐ RECOMMENDED

**Description:** Modern, async web framework built on Starlette and Pydantic

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 10 | Fastest to prototype APIs |
| Learning Curve | 9 | Python type hints = automatic docs |
| API Development | 10 | Auto OpenAPI, validation, serialization |
| Job Queue Integration | 8 | Works with Celery, ARQ, Dramatiq |
| Observability | 8 | Middleware for logging, Prometheus, OpenTelemetry |
| Production Ready | 9 | Used by Netflix, Uber, Microsoft |
| Community/Ecosystem | 10 | Fastest growing Python framework |
| Type Safety | 10 | Pydantic models, full type hints |
| Testing Support | 9 | `TestClient` built-in, pytest-friendly |
| Deployment Simplicity | 9 | Single ASGI app, easy containerization |
| Documentation | 10 | Excellent docs + interactive playground |
| Supabase Compatibility | 9 | Async Supabase client works perfectly |
| Scalability | 9 | Async by default, high performance |
| Maintenance Overhead | 9 | Minimal boilerplate |

**Total: 129/140 (92%)**

**Pros:**
- ✅ Automatic OpenAPI/Swagger UI (great for mobile/web devs)
- ✅ Async/await native (performance + scalability)
- ✅ Pydantic validation (type-safe request/response)
- ✅ Dependency injection system
- ✅ WebSocket support (future real-time features)
- ✅ Works perfectly with existing Supabase Python client
- ✅ Minimal learning curve if you know Python type hints

**Cons:**
- ⚠️ Async can be overkill for simple CRUD
- ⚠️ Requires ASGI server (Uvicorn/Hypercorn)
- ⚠️ No built-in job queue (use separate library)

**Job Queue Pairing:**
- **ARQ** (async, Redis-based, clean) - Best fit
- **Celery** (most mature, heavy)
- **Dramatiq** (lighter than Celery)

**Code Example:**
```python
from fastapi import FastAPI, Depends
from pydantic import BaseModel

app = FastAPI()

class Email(BaseModel):
    subject: str
    from_email: str

@app.get("/emails")
async def list_emails(limit: int = 10):
    # Auto-validated, auto-documented
    return {"emails": [], "limit": limit}

@app.post("/emails", response_model=Email)
async def create_email(email: Email):
    # Pydantic validation automatic
    return email
```

**Deployment:**
```dockerfile
FROM python:3.12-slim
RUN pip install fastapi uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### 2. Flask + Flask-RESTful

**Description:** Micro-framework, most popular Python web framework

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 8 | Quick start, but more boilerplate than FastAPI |
| Learning Curve | 10 | Easiest to learn, huge community |
| API Development | 6 | Manual serialization, no auto-docs |
| Job Queue Integration | 9 | Celery integration is industry standard |
| Observability | 7 | Many extensions available |
| Production Ready | 10 | Battle-tested for 15+ years |
| Community/Ecosystem | 10 | Largest ecosystem, most tutorials |
| Type Safety | 4 | No native support, manual validation |
| Testing Support | 9 | Excellent test client |
| Deployment Simplicity | 9 | WSGI, well-understood |
| Documentation | 9 | Comprehensive docs |
| Supabase Compatibility | 8 | Sync client works fine |
| Scalability | 5 | WSGI = sync only, blocks on I/O |
| Maintenance Overhead | 7 | More boilerplate than FastAPI |

**Total: 111/140 (79%)**

**Pros:**
- ✅ Most mature, stable, proven
- ✅ Easiest to find help/tutorials
- ✅ Flask-Celery integration is standard
- ✅ Huge extension ecosystem
- ✅ Simple mental model (request → response)

**Cons:**
- ⚠️ Synchronous (blocks on database/API calls)
- ⚠️ No automatic API docs
- ⚠️ Manual input validation (use Marshmallow/Pydantic)
- ⚠️ More code for same features vs FastAPI
- ⚠️ Older patterns (pre-async Python)

**Job Queue Pairing:**
- **Celery** - Industry standard with Flask
- **RQ (Redis Queue)** - Simpler alternative

---

### 3. Django + Django REST Framework (DRF)

**Description:** Full-stack framework with batteries included

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 6 | Slow initial setup, fast after scaffolding |
| Learning Curve | 5 | Steep, lots of "Django way" concepts |
| API Development | 8 | DRF is excellent, auto-browsable API |
| Job Queue Integration | 9 | Celery/Django-Q/Django-RQ built-in |
| Observability | 8 | Admin panel, debug toolbar, APM integrations |
| Production Ready | 10 | Powers Instagram, Pinterest, Mozilla |
| Community/Ecosystem | 10 | Massive ecosystem |
| Type Safety | 5 | ORM not type-safe, can add django-stubs |
| Testing Support | 10 | Best-in-class testing tools |
| Deployment Simplicity | 7 | More complex (static files, migrations) |
| Documentation | 10 | Legendary documentation |
| Supabase Compatibility | 4 | Django ORM conflicts with external DB |
| Scalability | 7 | WSGI sync, but proven at scale |
| Maintenance Overhead | 5 | Heavy framework, lots of config |

**Total: 104/140 (74%)**

**Pros:**
- ✅ Admin panel (free database UI)
- ✅ ORM, migrations, auth built-in
- ✅ DRF provides excellent API tools
- ✅ Best testing framework
- ✅ Security features out-of-box

**Cons:**
- ⚠️ **MAJOR:** Django ORM conflicts with Supabase RLS approach
- ⚠️ Overkill for API-only backend
- ⚠️ Steep learning curve for solo dev
- ⚠️ Slow initial development (setup overhead)
- ⚠️ Forces "Django way" patterns
- ⚠️ You'd lose Supabase benefits (RLS, auth)

**Verdict:** ❌ Not recommended - conflicts with Supabase architecture

---

### 4. Litestar (formerly Starlite)

**Description:** Modern ASGI framework, FastAPI alternative with more structure

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 8 | Slightly more setup than FastAPI |
| Learning Curve | 7 | More concepts than FastAPI |
| API Development | 9 | Similar to FastAPI, more opinionated |
| Job Queue Integration | 7 | ARQ/Celery compatible |
| Observability | 9 | Built-in OpenTelemetry, structured logging |
| Production Ready | 7 | Newer, but stable (v2.0+) |
| Community/Ecosystem | 5 | Growing, smaller than FastAPI |
| Type Safety | 10 | Strong type checking, Pydantic |
| Testing Support | 8 | Good test client |
| Deployment Simplicity | 9 | ASGI, similar to FastAPI |
| Documentation | 8 | Good, but less extensive |
| Supabase Compatibility | 9 | Async Supabase works |
| Scalability | 9 | High performance ASGI |
| Maintenance Overhead | 8 | More structure = more boilerplate |

**Total: 113/140 (81%)**

**Pros:**
- ✅ Better observability than FastAPI (built-in OpenTelemetry)
- ✅ More structured (dependency injection, lifecycle hooks)
- ✅ Plugin system
- ✅ Great for larger apps

**Cons:**
- ⚠️ Smaller community than FastAPI
- ⚠️ More concepts to learn
- ⚠️ Overkill for POC phase

**Verdict:** Good alternative to FastAPI if you need more structure

---

### 5. Sanic

**Description:** Flask-like async framework

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 7 | Flask-like syntax, async |
| Learning Curve | 8 | Familiar if you know Flask |
| API Development | 6 | Manual serialization, no auto-docs |
| Job Queue Integration | 6 | Can use async task libraries |
| Observability | 6 | Basic middleware |
| Production Ready | 7 | Stable, used in production |
| Community/Ecosystem | 6 | Smaller than FastAPI/Flask |
| Type Safety | 4 | No built-in validation |
| Testing Support | 7 | Test client available |
| Deployment Simplicity | 8 | ASGI-compatible |
| Documentation | 7 | Decent docs |
| Supabase Compatibility | 8 | Async works |
| Scalability | 9 | High performance |
| Maintenance Overhead | 7 | More manual than FastAPI |

**Total: 96/140 (69%)**

**Verdict:** Outclassed by FastAPI (async + less features)

---

### 6. Quart

**Description:** Async re-implementation of Flask API

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 8 | Flask syntax + async |
| Learning Curve | 9 | Flask developers feel at home |
| API Development | 6 | Flask-level (no auto-docs) |
| Job Queue Integration | 7 | Async task queues |
| Observability | 6 | Flask extensions mostly work |
| Production Ready | 7 | Stable, less proven than Flask |
| Community/Ecosystem | 5 | Smaller ecosystem |
| Type Safety | 4 | Manual validation |
| Testing Support | 8 | Flask-like testing |
| Deployment Simplicity | 8 | ASGI |
| Documentation | 7 | Good migration guide from Flask |
| Supabase Compatibility | 8 | Async works |
| Scalability | 8 | Async performance |
| Maintenance Overhead | 7 | More manual work |

**Total: 98/140 (70%)**

**Verdict:** Use if migrating from Flask, otherwise choose FastAPI

---

### 7. Starlette (Bare Framework)

**Description:** Lightweight ASGI toolkit (FastAPI is built on this)

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Velocity | 6 | Very bare-bones |
| Learning Curve | 7 | Minimal concepts |
| API Development | 5 | DIY everything |
| Job Queue Integration | 7 | Library-agnostic |
| Observability | 6 | Middleware support |
| Production Ready | 9 | Powers FastAPI |
| Community/Ecosystem | 7 | Used via FastAPI mostly |
| Type Safety | 3 | No validation layer |
| Testing Support | 7 | Test client included |
| Deployment Simplicity | 9 | Minimal ASGI app |
| Documentation | 7 | Good but minimal |
| Supabase Compatibility | 9 | Pure async |
| Scalability | 10 | Extremely fast |
| Maintenance Overhead | 5 | Too much DIY |

**Total: 97/140 (69%)**

**Verdict:** Just use FastAPI (built on Starlette with better DX)

---

## Job Queue Options

### A. ARQ ⭐ RECOMMENDED (with FastAPI)

**Description:** Async Redis-based task queue

**Pros:**
- ✅ Pure async (works with FastAPI naturally)
- ✅ Simple API, minimal config
- ✅ Cron-like scheduling built-in
- ✅ Good for async Supabase operations
- ✅ Lightweight (no extra dependencies)

**Cons:**
- ⚠️ Requires Redis
- ⚠️ Smaller ecosystem than Celery
- ⚠️ Less monitoring tools

**Example:**
```python
# worker.py
async def process_email(ctx, email_id: str):
    # Async Supabase calls work great
    client = await get_supabase_client()
    email = await client.table('emails').select('*').eq('id', email_id).execute()
    # Process...
    return {"status": "done"}

# main.py
from arq import create_pool
from arq.connections import RedisSettings

async def enqueue_task():
    redis = await create_pool(RedisSettings())
    await redis.enqueue_job('process_email', email_id='123')
```

---

### B. Celery (Industry Standard)

**Description:** Mature distributed task queue

**Pros:**
- ✅ Most mature, battle-tested
- ✅ Advanced features (workflows, routing, retries)
- ✅ Great monitoring (Flower)
- ✅ Works with Flask, FastAPI, Django

**Cons:**
- ⚠️ Complex configuration
- ⚠️ Heavy dependencies
- ⚠️ Sync by default (async support exists but clunky)
- ⚠️ Overkill for POC

**Verdict:** Best for complex workflows, overkill for your use case

---

### C. RQ (Redis Queue)

**Description:** Simple Python job queue

**Pros:**
- ✅ Extremely simple API
- ✅ Good with Flask
- ✅ Easy to understand/debug
- ✅ Web dashboard (rq-dashboard)

**Cons:**
- ⚠️ Synchronous only (doesn't use async/await)
- ⚠️ No cron scheduling (need rq-scheduler)
- ⚠️ Less advanced than Celery

**Verdict:** Good for Flask, but sync-only

---

### D. Dramatiq

**Description:** Fast, reliable alternative to Celery

**Pros:**
- ✅ Simpler than Celery
- ✅ Fast and reliable
- ✅ Good error handling
- ✅ Multiple broker support (Redis, RabbitMQ)

**Cons:**
- ⚠️ Primarily synchronous
- ⚠️ Smaller community than Celery

---

### E. Huey

**Description:** Lightweight task queue

**Pros:**
- ✅ Very simple
- ✅ Redis or SQLite backend
- ✅ Good for small projects

**Cons:**
- ⚠️ Not async-native
- ⚠️ Limited scalability

---

### F. SAQ (Simple Async Queue)

**Description:** Minimalist async task queue

**Pros:**
- ✅ Pure async
- ✅ Very simple
- ✅ Works with FastAPI

**Cons:**
- ⚠️ Minimal features
- ⚠️ Small community
- ⚠️ Less battle-tested

---

## Polling Solutions

For periodic tasks (e.g., Gmail sync every 5 minutes):

### Option 1: APScheduler
- Works with any framework
- In-process or distributed
- Cron-like scheduling

### Option 2: ARQ Cron
- Built into ARQ
- Async-native
- Simple decorator syntax

### Option 3: systemd timers (if deploying to Linux)
- OS-level, most reliable
- Simple cron-like config
- No Python dependency

---

## Final Rankings

### Overall Scores

| Rank | Framework | Score | Job Queue | Best For |
|------|-----------|-------|-----------|----------|
| **🥇 1** | **FastAPI** | **92%** | **ARQ** | ✅ **Your use case** |
| 🥈 2 | Litestar | 81% | ARQ | Structured larger apps |
| 🥉 3 | Flask | 79% | Celery/RQ | Simple sync APIs |
| 4 | Django+DRF | 74% | Celery | ❌ Conflicts with Supabase |
| 5 | Quart | 70% | ARQ | Migrating from Flask |
| 6 | Sanic | 69% | ARQ | Flask-like + async |
| 7 | Starlette | 69% | ARQ | Too bare-bones |

---

## Recommendation for Selko POC

### 🏆 Winner: FastAPI + ARQ + APScheduler

**Architecture:**
```
┌─────────────────┐
│   FastAPI App   │  ← REST APIs (web/mobile/CLI)
│   (Uvicorn)     │
└────────┬────────┘
         │
         ├─→ Supabase Client (async)
         ├─→ ARQ enqueue (background tasks)
         └─→ APScheduler (polling)

┌─────────────────┐
│   ARQ Workers   │  ← Process jobs from Redis queue
│   (async)       │
└────────┬────────┘
         │
         └─→ Supabase Client (async)

┌─────────────────┐
│   Redis         │  ← Job queue + cache
└─────────────────┘
```

**Why This Stack:**

1. **FastAPI** for APIs:
   - Automatic OpenAPI docs (helpful for mobile/web devs)
   - Type-safe with Pydantic (already using type hints)
   - Async = efficient for I/O-bound operations (Supabase calls)
   - Easy to test
   - Can start simple, scales well

2. **ARQ** for background jobs:
   - Native async (works with Supabase async client)
   - Simple Redis-based queue
   - Built-in cron scheduling
   - Minimal config

3. **APScheduler** for polling (if needed):
   - Cron-like scheduling
   - Can run in-process or distributed
   - Flexible

**Implementation Plan:**

```bash
# Install
uv add fastapi uvicorn[standard] arq apscheduler

# Project structure
backend/
├── api/
│   ├── main.py          # FastAPI app
│   ├── routes/
│   │   ├── emails.py    # GET /emails, POST /emails
│   │   └── integrations.py
│   └── dependencies.py  # Supabase client injection
├── workers/
│   ├── tasks.py         # ARQ task definitions
│   └── worker.py        # ARQ worker config
├── scheduler/
│   └── jobs.py          # APScheduler jobs (polling)
└── selko/               # Existing shared services
    └── services/
```

**Minimal FastAPI Example:**
```python
# api/main.py
from fastapi import FastAPI, Depends
from selko.config import load_config
from selko.services.auth import get_authenticated_client

app = FastAPI(title="Selko API")
config = load_config()

@app.get("/emails")
async def list_emails(
    limit: int = 10,
    client = Depends(get_authenticated_client)
):
    result = await client.table("emails").select("*").limit(limit).execute()
    return result.data

# Run with: uvicorn api.main:app --reload
```

**ARQ Background Job:**
```python
# workers/tasks.py
async def fetch_new_emails(ctx):
    """Background job to fetch new emails from Gmail."""
    # Your existing logic from cli_fetch_emails
    return {"emails_fetched": 10}

# workers/worker.py
from arq import create_pool, cron
from arq.connections import RedisSettings

async def startup(ctx):
    ctx['config'] = load_config()

async def shutdown(ctx):
    pass

class WorkerSettings:
    functions = [fetch_new_emails]
    cron_jobs = [
        cron(fetch_new_emails, hour={8, 12, 16, 20})  # 4x daily
    ]
    redis_settings = RedisSettings()
    on_startup = startup
    on_shutdown = shutdown

# Run with: arq workers.worker.WorkerSettings
```

**Migration Path:**
1. Keep existing CLI tools for development/testing
2. Add FastAPI alongside (doesn't replace anything)
3. Move long-running tasks to ARQ as needed
4. Gradual migration, low risk

**Observability:**
```python
# Add middleware for logging
from fastapi.middleware.cors import CORSMiddleware
import logging

app.add_middleware(
    # Structured logging middleware
)

# Prometheus metrics (optional)
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

**Deployment:**
```yaml
# docker-compose.yml
services:
  api:
    build: .
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000
    ports:
      - "8000:8000"
    depends_on:
      - redis

  worker:
    build: .
    command: arq workers.worker.WorkerSettings
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

---

## Alternative: "Wait and See" Approach

**Option:** Stick with CLI-only for now, add API layer later

**Rationale:**
- You're in POC phase
- Current CLI + Supabase works
- Can always add FastAPI later (non-breaking)
- YAGNI principle

**When to add API:**
- When you start building web/mobile UI
- When you need webhooks (e.g., Gmail push notifications)
- When you need scheduled jobs beyond simple cron

**Transition Path:**
```
Current:   CLI → Supabase
           ↓
Phase 1:   CLI → Supabase  (keep working)
           API → Supabase  (add alongside)
           ↓
Phase 2:   API → Supabase  (CLI becomes thin wrapper)
           Workers → Supabase
```

---

## Decision Matrix

| Scenario | Recommendation |
|----------|----------------|
| **Need APIs now** | FastAPI + ARQ |
| **Only CLI for 3+ months** | Wait, stick with current |
| **Heavy background jobs** | FastAPI + Celery |
| **Want Django admin panel** | ❌ Conflicts with Supabase |
| **Coming from Flask** | FastAPI (learn async) or Flask |
| **Maximum simplicity** | Flask + RQ |
| **Best observability** | Litestar + ARQ |

---

## Learning Resources

### FastAPI
- Official Docs: https://fastapi.tiangolo.com
- Tutorial: https://fastapi.tiangolo.com/tutorial/
- Async patterns: https://fastapi.tiangolo.com/async/
- Supabase + FastAPI: https://supabase.com/docs/guides/api/rest

### ARQ
- Docs: https://arq-docs.helpmanual.io
- Examples: https://github.com/samuelcolvin/arq/tree/main/examples

### Deployment
- FastAPI on Fly.io: https://fly.io/docs/python/fastapi/
- Docker best practices: https://fastapi.tiangolo.com/deployment/docker/

---

## Summary

### TL;DR

**For Selko POC:**
- ✅ **Start:** FastAPI + ARQ (if you need APIs/workers now)
- ✅ **Or wait:** Stick with CLI until you build web/mobile UI
- ❌ **Avoid:** Django (conflicts with Supabase architecture)

**Next Steps:**
1. Decide if you need API layer now or can wait
2. If now: Add FastAPI alongside existing code (non-breaking)
3. Start with simple endpoints, add ARQ when you have long tasks
4. Keep CLI tools for development/debugging

**Key Insight:** FastAPI won't slow you down (it's actually faster to develop than writing CLI args), and you'll need it eventually for web/mobile. Start small, grow as needed.
