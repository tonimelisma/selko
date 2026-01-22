# Hosting & Deployment Evaluation for Selko

**Date:** 2026-01-22
**Context:** POC → MVP deployment, solo developer, FastAPI + ARQ stack
**Current State:** Local development only, Supabase cloud (staging/production)

## Requirements Summary

### Must Have
- ✅ Host FastAPI application (async ASGI)
- ✅ Run ARQ background workers (Redis required)
- ✅ PostgreSQL database (Supabase hosted separately)
- ✅ Object storage (Supabase Storage hosted separately)
- ✅ Redis for job queue + caching
- ✅ Low operational overhead (solo developer)
- ✅ Good observability (logs, metrics, errors)
- ✅ Reasonable cost for POC/MVP

### Nice to Have
- Auto-scaling for traffic spikes
- Zero-downtime deployments
- CI/CD integration (GitHub Actions)
- Easy rollbacks
- Staging + production environments
- CDN for static assets (future web UI)
- Email sending (transactional)
- Custom domain + SSL
- Background job monitoring

### Constraints
- Solo developer (minimize DevOps complexity)
- Budget-conscious (POC/early MVP stage)
- Already using: Supabase (database + storage + auth)
- Future needs: Web UI, mobile API access
- No Kubernetes expertise (avoid if possible)

---

## Evaluation Criteria

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **Developer Experience** | 10 | Ease of deployment, CLI quality, docs |
| **Operational Overhead** | 10 | How much DevOps work required |
| **Cost (POC/MVP)** | 9 | Monthly cost for small traffic (<1000 users) |
| **FastAPI Support** | 9 | Native ASGI, async worker support |
| **Redis Hosting** | 8 | Built-in or easy add-on |
| **Observability** | 9 | Logs, metrics, error tracking, APM |
| **Scaling Path** | 7 | Can grow from POC to production |
| **CI/CD Integration** | 7 | GitHub Actions, auto-deploy |
| **Docker Support** | 8 | Native containerization |
| **Background Workers** | 9 | Run ARQ workers alongside API |
| **Database Proximity** | 6 | Latency to Supabase (US-based) |
| **Free Tier** | 8 | Can start free/cheap |
| **Community/Docs** | 7 | Python ecosystem support |
| **Vendor Lock-in** | 6 | Ease of migration later |

**Scoring:** 1-10 scale (10 = best)

---

## Hosting Options

### 1. Fly.io ⭐ RECOMMENDED

**Description:** Modern app platform, Docker-native, edge deployment

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 10 | Excellent CLI (`flyctl`), simple config |
| Operational Overhead | 9 | Minimal - just `fly deploy` |
| Cost (POC/MVP) | 9 | Free tier: 3 VMs (256MB), generous allowance |
| FastAPI Support | 10 | ASGI native, excellent Python docs |
| Redis Hosting | 9 | Upstash Redis add-on (serverless) |
| Observability | 8 | Built-in logs/metrics, Sentry integration |
| Scaling Path | 9 | Auto-scale, multi-region, proven at scale |
| CI/CD Integration | 9 | GitHub Actions official support |
| Docker Support | 10 | Docker-native platform |
| Background Workers | 10 | Multiple processes in fly.toml |
| Database Proximity | 8 | Deploy near Supabase region |
| Free Tier | 10 | Generous free tier (3 shared VMs) |
| Community/Docs | 9 | Great Python/FastAPI examples |
| Vendor Lock-in | 8 | Standard Docker, easy migration |

**Total: 128/140 (91%)**

**Pros:**
- ✅ **Best free tier** - Can run POC entirely free
- ✅ **Docker-native** - No platform-specific config
- ✅ **Multi-process** - API + workers in same app
- ✅ **Edge deployment** - Global low-latency
- ✅ **Simple scaling** - `fly scale count 3`
- ✅ **Great DX** - `fly deploy` and done
- ✅ **Upstash Redis** - Serverless Redis, pay-per-request
- ✅ **Secrets management** - `fly secrets set KEY=value`

**Cons:**
- ⚠️ Still relatively new (2020), less battle-tested than AWS/GCP
- ⚠️ Fewer managed services (no managed Postgres, but you have Supabase)
- ⚠️ Logs retention limited on free tier

**Cost Breakdown (MVP ~1000 users):**
| Component | Estimate |
|-----------|----------|
| API (1x shared-1x, 256MB) | Free |
| Worker (1x shared-1x, 256MB) | Free |
| Upstash Redis (serverless) | $0-10/mo |
| **Total** | **~$10/mo or less** |

**Configuration:**
```toml
# fly.toml
app = "selko-api"
primary_region = "sjc"  # Near Supabase

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "8000"
  ENVIRONMENT = "production"

[[services]]
  internal_port = 8000
  protocol = "tcp"

  [[services.ports]]
    port = 80
    handlers = ["http"]
  [[services.ports]]
    port = 443
    handlers = ["tls", "http"]

  [services.concurrency]
    type = "connections"
    hard_limit = 25
    soft_limit = 20

# Run ARQ worker as second process
[processes]
  app = "uvicorn api.main:app --host 0.0.0.0 --port 8000"
  worker = "arq workers.worker.WorkerSettings"
```

**Deployment:**
```bash
# First time setup
fly launch

# Deploy
fly deploy

# Scale
fly scale count 2  # 2 instances

# Check status
fly status
fly logs

# Set secrets
fly secrets set SUPABASE_URL=https://... SUPABASE_KEY=...
```

**Upstash Redis Setup:**
```bash
# Provision Redis
fly redis create

# Auto-configures REDIS_URL secret
# Use in ARQ workers
```

---

### 2. Railway ⭐ STRONG ALTERNATIVE

**Description:** Heroku-like platform, Git-based deployment

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 10 | Best-in-class UI, zero config |
| Operational Overhead | 10 | Fully managed, auto-deploy from Git |
| Cost (POC/MVP) | 8 | $5/mo credit, then ~$10-20/mo |
| FastAPI Support | 9 | Python templates, ASGI support |
| Redis Hosting | 10 | One-click Redis deployment |
| Observability | 8 | Logs, metrics, integrations |
| Scaling Path | 8 | Vertical + horizontal scaling |
| CI/CD Integration | 10 | Auto-deploy on Git push |
| Docker Support | 9 | Dockerfile or Nixpacks auto-detect |
| Background Workers | 9 | Deploy workers as separate service |
| Database Proximity | 7 | US regions available |
| Free Tier | 7 | $5/mo trial, then paid |
| Community/Docs | 8 | Growing community |
| Vendor Lock-in | 8 | Standard Docker/Buildpacks |

**Total: 121/140 (86%)**

**Pros:**
- ✅ **Easiest deployment** - Connect GitHub, done
- ✅ **Beautiful UI** - Best dashboard experience
- ✅ **One-click Redis** - Managed Redis included
- ✅ **Zero config** - Auto-detects Python/FastAPI
- ✅ **Environment variables** - Easy management
- ✅ **Preview deployments** - PR-based staging
- ✅ **Volume storage** - Persistent storage available

**Cons:**
- ⚠️ No free tier (trial only)
- ⚠️ More expensive than Fly.io (~$10-20/mo minimum)
- ⚠️ Younger platform (2020)

**Cost Breakdown (MVP):**
| Component | Estimate |
|-----------|----------|
| API service | ~$5/mo |
| Worker service | ~$5/mo |
| Redis | ~$5/mo |
| **Total** | **~$15/mo** |

**Deployment:**
```bash
# Railway CLI (or use web UI)
railway login
railway init
railway up

# Or just connect GitHub repo in UI - auto-deploys!
```

---

### 3. Render

**Description:** Heroku alternative, fully managed platform

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 9 | Clean UI, good docs |
| Operational Overhead | 9 | Fully managed |
| Cost (POC/MVP) | 8 | Free tier, then $7/mo per service |
| FastAPI Support | 9 | Python runtime, ASGI support |
| Redis Hosting | 8 | Managed Redis available |
| Observability | 7 | Logs, basic metrics |
| Scaling Path | 8 | Auto-scale available |
| CI/CD Integration | 9 | Auto-deploy from Git |
| Docker Support | 9 | Native Docker or buildpack |
| Background Workers | 9 | Background workers supported |
| Database Proximity | 7 | US/EU regions |
| Free Tier | 9 | Free web services (sleeps after 15min) |
| Community/Docs | 8 | Good tutorials |
| Vendor Lock-in | 8 | Standard containers |

**Total: 117/140 (84%)**

**Pros:**
- ✅ **Good free tier** - Can start free (with sleep)
- ✅ **Managed services** - Redis, Postgres, Cron
- ✅ **Background workers** - Native support
- ✅ **Git-based deploys** - Auto-deploy on push
- ✅ **Preview environments** - PR-based staging

**Cons:**
- ⚠️ Free tier sleeps after 15min inactivity (startup delay)
- ⚠️ More expensive than Fly.io for paid tier
- ⚠️ Slower cold starts

**Cost Breakdown (MVP):**
| Component | Estimate |
|-----------|----------|
| API (Starter) | $7/mo |
| Worker (Starter) | $7/mo |
| Redis (Starter) | $7/mo |
| **Total** | **~$21/mo** |

---

### 4. Google Cloud Run ⭐ SERVERLESS OPTION

**Description:** Serverless container platform, pay-per-request

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 7 | Good CLI, some GCP complexity |
| Operational Overhead | 8 | Serverless, auto-scale to zero |
| Cost (POC/MVP) | 10 | Pay-per-request, very cheap for low traffic |
| FastAPI Support | 9 | Container-based, any runtime |
| Redis Hosting | 6 | Memorystore expensive, use Upstash |
| Observability | 9 | Google Cloud Logging/Monitoring |
| Scaling Path | 10 | Infinite scale, battle-tested |
| CI/CD Integration | 8 | Cloud Build, GitHub Actions |
| Docker Support | 10 | Native container platform |
| Background Workers | 7 | Need Cloud Tasks or Pub/Sub trigger |
| Database Proximity | 9 | Global regions, near Supabase |
| Free Tier | 10 | 2M requests/mo free |
| Community/Docs | 9 | Excellent GCP docs |
| Vendor Lock-in | 7 | Container-based, but GCP-specific deploy |

**Total: 119/140 (85%)**

**Pros:**
- ✅ **Best pricing model** - Only pay for requests
- ✅ **Auto-scale to zero** - $0 when idle
- ✅ **Google infrastructure** - Highly reliable
- ✅ **Generous free tier** - 2M requests/mo
- ✅ **Global CDN** - Built-in
- ✅ **Excellent observability** - Cloud Logging/Trace

**Cons:**
- ⚠️ **Complex for workers** - Need Cloud Tasks/Pub/Sub
- ⚠️ **Cold starts** - 1-3s latency when scaling from zero
- ⚠️ **GCP learning curve** - More complex than Fly/Railway
- ⚠️ **Redis costly** - Memorystore is expensive, use external (Upstash)
- ⚠️ **Stateless** - Can't run long-running ARQ workers directly

**Cost Breakdown (MVP <10k requests/day):**
| Component | Estimate |
|-----------|----------|
| Cloud Run (API) | $0-5/mo |
| Upstash Redis | $0-10/mo |
| Cloud Tasks (job queue) | $0-5/mo |
| **Total** | **~$5-10/mo** |

**Note:** Workers need different approach (Cloud Tasks for job queue, not ARQ)

---

### 5. AWS (Elastic Beanstalk or ECS Fargate)

**Description:** Amazon's platform services

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 5 | Complex, steep learning curve |
| Operational Overhead | 5 | High - many services to configure |
| Cost (POC/MVP) | 6 | ~$20-50/mo minimum |
| FastAPI Support | 7 | Supports via Docker/Python runtime |
| Redis Hosting | 7 | ElastiCache (expensive) or self-host |
| Observability | 8 | CloudWatch, X-Ray (complex setup) |
| Scaling Path | 10 | Unlimited scale |
| CI/CD Integration | 7 | CodePipeline or GitHub Actions |
| Docker Support | 8 | ECS/Fargate support |
| Background Workers | 7 | ECS tasks or Lambda |
| Database Proximity | 9 | Global regions |
| Free Tier | 6 | 12-month free tier (limited) |
| Community/Docs | 9 | Extensive but overwhelming |
| Vendor Lock-in | 6 | Heavy AWS-specific services |

**Total: 100/140 (71%)**

**Pros:**
- ✅ **Industry standard** - Most mature platform
- ✅ **Infinite scale** - Can handle any load
- ✅ **All services available** - Complete ecosystem
- ✅ **Global infrastructure** - Worldwide regions

**Cons:**
- ⚠️ **High complexity** - VPCs, subnets, security groups, IAM
- ⚠️ **Expensive** - Hard to stay under $50/mo
- ⚠️ **Overkill for solo dev** - Too many moving parts
- ⚠️ **Slow iteration** - Complex deployments
- ⚠️ **ElastiCache expensive** - Redis costs $15+/mo minimum

**Verdict:** ❌ Not recommended for solo POC/MVP (overkill, expensive, complex)

---

### 6. Azure (App Service or Container Apps)

**Description:** Microsoft's platform services

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 6 | Improving, but complex |
| Operational Overhead | 6 | Moderate complexity |
| Cost (POC/MVP) | 6 | ~$15-30/mo minimum |
| FastAPI Support | 7 | Python/Docker support |
| Redis Hosting | 7 | Azure Cache for Redis (expensive) |
| Observability | 8 | Application Insights |
| Scaling Path | 9 | Enterprise-grade scaling |
| CI/CD Integration | 8 | Azure DevOps, GitHub Actions |
| Docker Support | 8 | Container Apps, ACI |
| Background Workers | 7 | Azure Functions or Container Apps |
| Database Proximity | 8 | Global regions |
| Free Tier | 7 | $200 credit first month |
| Community/Docs | 7 | Good docs, smaller Python community |
| Vendor Lock-in | 6 | Azure-specific services |

**Total: 100/140 (71%)**

**Verdict:** Similar to AWS - overkill for solo dev, too complex

---

### 7. DigitalOcean App Platform

**Description:** Simplified PaaS from DigitalOcean

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 8 | Clean UI, simple |
| Operational Overhead | 8 | Managed platform |
| Cost (POC/MVP) | 7 | $5/mo basic, $12/mo professional |
| FastAPI Support | 8 | Python runtime support |
| Redis Hosting | 8 | Managed Redis available |
| Observability | 6 | Basic logs/metrics |
| Scaling Path | 7 | Limited compared to others |
| CI/CD Integration | 8 | Auto-deploy from Git |
| Docker Support | 8 | Dockerfile support |
| Background Workers | 8 | Worker components |
| Database Proximity | 7 | US/EU regions |
| Free Tier | 3 | No free tier (trial credits only) |
| Community/Docs | 7 | Good tutorials |
| Vendor Lock-in | 7 | Mostly standard |

**Total: 100/140 (71%)**

**Pros:**
- ✅ Simple, clean interface
- ✅ Predictable pricing
- ✅ Good for small apps

**Cons:**
- ⚠️ No free tier
- ⚠️ Less powerful than competitors
- ⚠️ Limited scaling options

---

### 8. Heroku

**Description:** Original PaaS, now Salesforce-owned

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 9 | Pioneered great DX |
| Operational Overhead | 9 | Fully managed |
| Cost (POC/MVP) | 4 | Expensive - removed free tier |
| FastAPI Support | 8 | Python buildpack |
| Redis Hosting | 7 | Heroku Redis add-on |
| Observability | 7 | Logs, metrics add-ons |
| Scaling Path | 8 | Good scaling |
| CI/CD Integration | 8 | GitHub integration |
| Docker Support | 7 | Container registry |
| Background Workers | 9 | Excellent worker dyno support |
| Database Proximity | 7 | US/EU regions |
| Free Tier | 1 | ❌ Removed in 2022 |
| Community/Docs | 9 | Extensive legacy docs |
| Vendor Lock-in | 7 | Procfile/buildpack specific |

**Total: 99/140 (71%)**

**Pros:**
- ✅ Best-in-class DX (historically)
- ✅ Great worker support
- ✅ Add-on ecosystem

**Cons:**
- ⚠️ **Expensive** - $7/mo minimum per dyno (need 2+ = $21+)
- ⚠️ **No free tier** - Used to have one, removed 2022
- ⚠️ **Stagnant** - Little innovation since Salesforce acquisition
- ⚠️ **Better alternatives exist** - Railway/Render/Fly are better value

**Verdict:** ❌ Overpriced compared to modern alternatives

---

### 9. Vercel / Netlify (Serverless Functions)

**Description:** Frontend-focused platforms with serverless functions

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 9 | Excellent for frontend |
| Operational Overhead | 8 | Serverless, low overhead |
| Cost (POC/MVP) | 7 | Free tier, then costly for backend |
| FastAPI Support | 3 | ❌ Not designed for ASGI apps |
| Redis Hosting | 4 | External only (Upstash) |
| Observability | 7 | Good logs/analytics |
| Scaling Path | 8 | Auto-scale |
| CI/CD Integration | 10 | Best Git integration |
| Docker Support | 2 | ❌ Serverless functions only |
| Background Workers | 5 | Limited to 10s-60s function timeout |
| Database Proximity | 8 | Edge network |
| Free Tier | 9 | Generous for frontend |
| Community/Docs | 9 | Excellent for frontend |
| Vendor Lock-in | 6 | Serverless function format |

**Total: 95/140 (68%)**

**Verdict:** ❌ Not suitable for FastAPI backend (designed for Next.js/React frontends)

---

### 10. Self-Hosted VPS (DigitalOcean Droplet, Linode, Hetzner)

**Description:** Traditional VM, you manage everything

**Scores:**
| Criterion | Score | Notes |
|-----------|-------|-------|
| Developer Experience | 4 | Manual setup, SSH, Linux admin |
| Operational Overhead | 3 | ❌ High - manage OS, security, updates |
| Cost (POC/MVP) | 9 | $5-10/mo for basic VM |
| FastAPI Support | 7 | Install anything you want |
| Redis Hosting | 7 | Self-install Redis |
| Observability | 4 | Manual setup (Prometheus, Grafana, etc.) |
| Scaling Path | 5 | Manual, vertical only |
| CI/CD Integration | 5 | DIY GitHub Actions + SSH |
| Docker Support | 8 | Install Docker yourself |
| Background Workers | 8 | Run anything via systemd |
| Database Proximity | 7 | Choose region |
| Free Tier | 5 | Some have trials |
| Community/Docs | 8 | Lots of tutorials |
| Vendor Lock-in | 10 | Zero lock-in, standard Linux |

**Total: 90/140 (64%)**

**Pros:**
- ✅ **Cheapest** - $5/mo for basic VM
- ✅ **Full control** - Install anything
- ✅ **No vendor lock-in** - Standard Linux
- ✅ **Learning opportunity** - Good for DevOps skills

**Cons:**
- ⚠️ **High maintenance** - Security patches, monitoring, backups
- ⚠️ **No auto-scale** - Manual vertical scaling
- ⚠️ **Solo dev burden** - You're the ops team
- ⚠️ **Single point of failure** - No redundancy
- ⚠️ **Time sink** - Focus on product, not server admin

**Verdict:** ❌ Not recommended for solo dev focused on product

---

## Managed Redis Options (For Any Platform)

### Upstash Redis ⭐ RECOMMENDED

**Description:** Serverless Redis, pay-per-request

**Pros:**
- ✅ **Serverless pricing** - $0.20 per 100k requests
- ✅ **Free tier** - 10k requests/day
- ✅ **Global replication** - Low latency worldwide
- ✅ **REST API** - HTTP access (no persistent connection)
- ✅ **Perfect for ARQ** - Works great with async workers

**Pricing (MVP):**
- Free tier: 10k requests/day (enough for POC)
- Paid: ~$5-10/mo for MVP traffic

**Integration:**
```python
# ARQ with Upstash
from arq.connections import RedisSettings

redis_settings = RedisSettings(
    host="your-redis.upstash.io",
    port=6379,
    password=os.getenv("UPSTASH_REDIS_PASSWORD"),
    ssl=True,
)
```

### Redis Cloud (Redis Labs)

**Pros:**
- Managed by Redis creators
- Free tier: 30MB
- Production-grade

**Cons:**
- More expensive than Upstash
- Overkill for POC

### Platform-Native Redis

| Platform | Service | Cost |
|----------|---------|------|
| Fly.io | Upstash integration | $0-10/mo |
| Railway | One-click Redis | ~$5/mo |
| Render | Managed Redis | $7/mo |
| AWS | ElastiCache | $15+/mo ❌ Expensive |
| Azure | Cache for Redis | $15+/mo ❌ Expensive |

---

## Final Rankings

### Overall Scores

| Rank | Platform | Score | Cost (MVP) | Best For |
|------|----------|-------|------------|----------|
| **🥇 1** | **Fly.io** | **91%** | **~$0-10/mo** | ✅ **Your use case** |
| 🥈 2 | Railway | 86% | ~$15/mo | Best DX, worth premium |
| 🥉 3 | Cloud Run | 85% | ~$5-10/mo | Serverless, cheap |
| 4 | Render | 84% | ~$21/mo | Heroku alternative |
| 5 | AWS | 71% | ~$30-50/mo | ❌ Overkill |
| 6 | Azure | 71% | ~$20-40/mo | ❌ Overkill |
| 7 | DigitalOcean | 71% | ~$15/mo | Simple but limited |
| 8 | Heroku | 71% | ~$21+/mo | ❌ Overpriced |
| 9 | Vercel/Netlify | 68% | N/A | ❌ Not for FastAPI |
| 10 | Self-hosted VPS | 64% | ~$5/mo | ❌ Too much ops work |

---

## Recommendation for Selko

### 🏆 Winner: Fly.io + Upstash Redis

**Why This Combination:**

1. **Best Free Tier**
   - Fly.io: 3 shared VMs free (256MB each)
   - Upstash: 10k Redis requests/day free
   - **Total POC cost: $0/month**

2. **Perfect for FastAPI + ARQ**
   - Native ASGI support
   - Multi-process (API + workers in one app)
   - Upstash Redis works great with ARQ

3. **Minimal DevOps**
   - `fly deploy` and done
   - Automatic SSL/DNS
   - Built-in secrets management
   - Logs/metrics included

4. **Production-Ready Path**
   - Scales horizontally: `fly scale count N`
   - Multi-region deployment
   - Auto-scaling available
   - Used by real production apps

5. **Solo Developer Friendly**
   - Simple CLI workflow
   - Great documentation
   - Active community
   - No complex configuration

**Architecture:**
```
┌─────────────────────────────┐
│     Fly.io Application      │
│  ┌─────────┐  ┌──────────┐  │
│  │ FastAPI │  │ ARQ      │  │  ← Two processes in one app
│  │ (API)   │  │ Workers  │  │
│  └────┬────┘  └────┬─────┘  │
│       │            │         │
└───────┼────────────┼─────────┘
        │            │
        ├─────────→  │  Upstash Redis (serverless)
        │            │
        └─────────→ Supabase (PostgreSQL + Storage + Auth)
```

---

## Alternative Recommendation: Railway

**If you value best DX over cost:**

Railway has the **best developer experience** of all platforms:
- Beautiful UI dashboard
- Zero-config deployment (connect GitHub repo, done)
- One-click Redis
- Environment variable management
- Preview deployments for PRs
- Volume storage

**Cost:** ~$15/mo for MVP (vs Fly.io's $0-10/mo)

**Worth it if:** You want to focus 100% on product, never think about infrastructure

---

## Deployment Configurations

### Fly.io Setup (Recommended)

**1. Install CLI:**
```bash
# macOS
brew install flyctl

# Linux/Windows
curl -L https://fly.io/install.sh | sh
```

**2. Create `fly.toml`:**
```toml
app = "selko-api"
primary_region = "sjc"  # San Jose (close to Supabase US)

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "8000"
  ENVIRONMENT = "production"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false  # Keep running (not serverless)
  auto_start_machines = true
  min_machines_running = 1

  [http_service.concurrency]
    type = "connections"
    hard_limit = 100
    soft_limit = 80

# Run both API and ARQ worker
[processes]
  app = "uvicorn api.main:app --host 0.0.0.0 --port 8000"
  worker = "arq workers.worker.WorkerSettings"

# Machine resources
[[vm]]
  size = "shared-cpu-1x"  # 256MB RAM (free tier)
```

**3. Create `Dockerfile`:**
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependencies
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -e .

# Copy code
COPY . .

# Fly.io uses processes from fly.toml
# Default command (overridden by fly.toml processes)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**4. Deploy:**
```bash
# Login
fly auth login

# Create app (first time)
fly launch

# Set secrets
fly secrets set \
  SUPABASE_URL=https://khahcozfbnpykspvatrg.supabase.co \
  SUPABASE_KEY=your-key \
  SUPABASE_SERVICE_ROLE_KEY=your-service-key

# Deploy
fly deploy

# Check status
fly status
fly logs

# Scale (if needed)
fly scale count 2  # Run 2 instances
```

**5. Setup Upstash Redis:**
```bash
# Option 1: Fly.io + Upstash integration
fly redis create

# Option 2: Manual Upstash setup
# 1. Create account at upstash.com
# 2. Create Redis database
# 3. Get connection details
fly secrets set REDIS_URL=redis://default:xxx@xxx.upstash.io:6379
```

---

### Railway Setup (Alternative)

**1. Install CLI (optional - can use web UI):**
```bash
npm install -g @railway/cli
```

**2. Create `railway.toml`:**
```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "uvicorn api.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
```

**3. Deploy:**
```bash
# Option 1: CLI
railway login
railway init
railway up

# Option 2: Web UI (easier!)
# 1. Go to railway.app
# 2. Connect GitHub repo
# 3. Auto-deploys on push!
```

**4. Add Redis:**
- Click "New" → "Database" → "Redis"
- Automatically sets `REDIS_URL` environment variable

**5. Add Worker:**
- Create second service in same project
- Use same Dockerfile
- Override start command: `arq workers.worker.WorkerSettings`

---

### Cloud Run Setup (Serverless Alternative)

**1. Create `cloudbuild.yaml`:**
```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/selko-api', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/selko-api']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'selko-api'
      - '--image'
      - 'gcr.io/$PROJECT_ID/selko-api'
      - '--region'
      - 'us-west1'
      - '--platform'
      - 'managed'
      - '--allow-unauthenticated'
```

**2. Deploy:**
```bash
gcloud run deploy selko-api \
  --source . \
  --region us-west1 \
  --allow-unauthenticated
```

**Note:** Cloud Run is serverless (cold starts), workers need Cloud Tasks

---

## Observability & Monitoring

### Recommended Stack (All Platforms)

| Tool | Purpose | Cost | Integration |
|------|---------|------|-------------|
| **Sentry** | Error tracking | Free (5k errors/mo) | FastAPI middleware |
| **Better Stack** | Log management | Free (1GB/mo) | Stdout forwarding |
| **Prometheus + Grafana** | Metrics | Self-hosted free | FastAPI instrumentator |
| **Uptime Robot** | Uptime monitoring | Free (50 monitors) | HTTP ping |

### FastAPI Integration

```python
# main.py
from fastapi import FastAPI
import sentry_sdk
from prometheus_fastapi_instrumentator import Instrumentator

# Sentry (errors)
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    traces_sample_rate=0.1,  # 10% of requests
)

app = FastAPI()

# Prometheus (metrics)
Instrumentator().instrument(app).expose(app)

# Logs (stdout → platform handles forwarding)
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## CI/CD Setup

### GitHub Actions (Works with Any Platform)

**`.github/workflows/deploy.yml`:**
```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Fly.io CLI
        uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Deploy to Fly.io
        run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**With tests:**
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install uv
      - run: uv sync --extra test
      - run: uv run pytest backend/tests/

  deploy:
    needs: test
    # ... deploy after tests pass
```

---

## Regional Deployment

**Supabase Regions:**
- Staging: Check project location
- Production: Check project location

**Recommended Host Regions:**

| Supabase Location | Fly.io Region | Cloud Run Region |
|-------------------|---------------|------------------|
| US West (AWS) | `sjc` (San Jose) | `us-west1` |
| US East (AWS) | `iad` (Virginia) | `us-east1` |
| EU West (AWS) | `ams` (Amsterdam) | `europe-west1` |
| Asia (AWS) | `sin` (Singapore) | `asia-southeast1` |

**Check latency:**
```bash
# From your Fly.io app to Supabase
fly ssh console
curl -w "@curl-format.txt" -o /dev/null -s https://khahcozfbnpykspvatrg.supabase.co
```

---

## Cost Projections

### POC Stage (0-100 users)

| Platform | Cost | Notes |
|----------|------|-------|
| **Fly.io** | **$0-5/mo** | Free tier sufficient |
| Railway | $5-10/mo | Trial credit → paid |
| Cloud Run | $0-5/mo | Pay per request |
| Render | $0-7/mo | Free tier (with sleep) |

**+ Supabase:** Free tier or ~$25/mo (Pro)
**+ Upstash Redis:** Free tier or ~$5/mo

**Total POC:** $0-10/mo (excluding Supabase)

### MVP Stage (100-1000 users)

| Platform | Cost | Notes |
|----------|------|-------|
| **Fly.io** | **$10-20/mo** | 2-3 instances |
| Railway | $15-30/mo | 2 services + Redis |
| Cloud Run | $10-20/mo | Serverless scaling |
| Render | $21-40/mo | Paid tier required |

**+ Supabase:** $25/mo (Pro)
**+ Upstash Redis:** $5-10/mo

**Total MVP:** $40-60/mo (all-in)

### Growth Stage (1k-10k users)

| Platform | Cost | Notes |
|----------|------|-------|
| **Fly.io** | **$30-100/mo** | 5-10 instances, autoscale |
| Railway | $50-150/mo | Scales with usage |
| Cloud Run | $20-80/mo | Serverless cost efficient |
| AWS/GCP | $100-500/mo | More control, more cost |

**+ Supabase:** $25/mo (Pro) or $599/mo (Team)
**+ Upstash Redis:** $10-30/mo

---

## Migration Path

### Phase 1: POC (Now)
- **Host:** Fly.io free tier
- **Redis:** Upstash free tier
- **DB:** Supabase staging (free)
- **Cost:** $0/mo

### Phase 2: MVP Launch
- **Host:** Fly.io paid (2 instances)
- **Redis:** Upstash paid
- **DB:** Supabase production (Pro $25/mo)
- **Monitoring:** Sentry free tier
- **Cost:** ~$50/mo all-in

### Phase 3: Growth
- **Host:** Fly.io autoscale or Cloud Run
- **Redis:** Upstash or Redis Cloud
- **DB:** Supabase Team plan
- **Monitoring:** Sentry paid, Datadog/New Relic
- **Cost:** $200-500/mo

### Phase 4: Scale (Optional)
- **Host:** AWS/GCP with Kubernetes
- **Redis:** ElastiCache/Memorystore
- **DB:** Self-hosted Postgres or RDS
- **Cost:** $1k+/mo (if you reach this, congrats!)

---

## Decision Matrix

| Your Situation | Recommendation |
|----------------|----------------|
| **Solo dev, POC phase** | ✅ **Fly.io** (free tier) |
| **Want best DX, budget flexible** | ✅ **Railway** ($15/mo) |
| **Minimal cost, serverless OK** | ✅ **Cloud Run** ($5-10/mo) |
| **Need traditional PaaS** | Render ($21/mo) |
| **Have GCP/AWS credits** | Cloud Run / Elastic Beanstalk |
| **Want to learn DevOps** | Self-hosted VPS ($5/mo) |
| **Enterprise requirements** | AWS/GCP/Azure |

---

## Summary

### TL;DR

**For Selko POC/MVP:**
- ✅ **Winner: Fly.io + Upstash Redis**
- ✅ **Alternative: Railway** (easier, slightly pricier)
- ❌ **Avoid: AWS/Azure** (overkill), **Heroku** (overpriced), **VPS** (too much ops)

**Why Fly.io:**
- Free tier for POC ($0/mo)
- Perfect FastAPI + ARQ support
- Minimal DevOps overhead
- Production-ready scaling path
- `fly deploy` and done

**Next Steps:**
1. Start with Fly.io free tier
2. Deploy POC at zero cost
3. Evaluate if you need Railway's better DX
4. Scale on Fly.io or migrate to Cloud Run if cost becomes issue

**Key Insight:** Modern platforms (Fly/Railway/Render) are **vastly better** than traditional cloud (AWS/Azure/GCP) for solo developers. Save the complexity for when you actually need it.
