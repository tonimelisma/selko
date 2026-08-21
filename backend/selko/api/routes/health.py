"""Health check endpoints."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status

from selko.api.deps import get_config
from selko.api.schemas.common import (
    EgressOperationResponse,
    ErrorCode,
    HealthDbResponse,
    HealthEgressResponse,
    HealthIngestionResponse,
    HealthIngestionTaskResponse,
    HealthResponse,
    error_detail,
)
from selko.config import Config, load_config
from selko.services.auth import get_service_client
from selko.services.egress import egress_snapshot
from selko.services.resolution_metrics import resolution_metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _work_state_status() -> str:
    """Top-level ``/health`` status, driven by the same roll-up the workers
    use to claim work — never hard-coded ``ok``.

    Best-effort: an unreachable database degrades the status rather than
    failing the route, matching ``_pending_email_metrics`` below.
    """
    try:
        cfg = load_config()
        client = get_service_client(cfg)
        result = client.rpc(
            "health_work_state",
            {"p_warning_seconds": int(cfg.email_health_warning_seconds or 1800)},
        ).execute()
        data = getattr(result, "data", None)
        row = (data or [None])[0] if isinstance(data, list) else data
        if not isinstance(row, dict):
            return "degraded"
        return "ok" if row.get("status") == "ok" else "degraded"
    except Exception:
        logger.exception("Work state health check failed")
        return "degraded"


def _pending_email_metrics() -> dict[str, int | None]:
    """Return queue age gauges without exposing email identity or content."""
    try:
        client = get_service_client(load_config())
        result = (
            client.table("emails")
            .select("created_at", count="exact")
            .eq("processing_status", "pending")
            .order("created_at")
            .limit(1)
            .execute()
        )
        pending = getattr(result, "count", None)
        if pending is None:
            pending = len(result.data or [])
        oldest_age = None
        if result.data:
            created_at = result.data[0].get("created_at")
            if created_at:
                created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                oldest_age = max(0, int((datetime.now(timezone.utc) - created).total_seconds()))
        return {
            "pending_emails": int(pending or 0),
            "oldest_pending_age_seconds": oldest_age,
        }
    except Exception:
        logger.exception("Resolution queue health snapshot failed")
        return {"pending_emails": None, "oldest_pending_age_seconds": None}


@router.get("/health", response_model=HealthResponse)
async def health_check(config: Config = Depends(get_config)) -> HealthResponse:
    """Basic health check endpoint.

    Returns 200 OK if the API is running.
    """
    resolution = resolution_metrics.snapshot()
    resolution.update(_pending_email_metrics())
    return HealthResponse(
        status=_work_state_status(),
        build_sha=config.build_sha,
        resolution=resolution,
    )


@router.get("/health/db", response_model=HealthDbResponse)
async def health_db_check(
    config: Config = Depends(get_config),
) -> HealthDbResponse:
    """Database connectivity health check.

    Tests connection to Supabase and returns status.
    """
    try:
        # Must use the service role: 20260714000003 deliberately leaves `anon`
        # with no table privileges, so an anon probe reports the database as
        # down even when it is perfectly healthy. The key stays server-side and
        # only a status string is returned.
        client = get_service_client(config)

        # Simple query to test connectivity, returning minimal data.
        client.table("users").select("id").limit(1).execute()

        return HealthDbResponse(status="ok", database="connected")

    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Database health check failed"),
        )


@router.get("/health/ingestion", response_model=HealthIngestionResponse)
async def health_ingestion_check(request: Request) -> HealthIngestionResponse:
    """Live ingestion health — the surface Render's health check should watch.

    ``/health`` shares the same ``health_work_state`` roll-up but has no task
    supervision of its own; this route adds per-task alive/restart state, due /
    lease / pending / dead-letter counts, and open email-sync incidents.
    ``down`` when any task is not alive; ``degraded`` on dead letters, open
    incidents, or the oldest pending poll past the warning SLO; otherwise ``ok``.

    Safe codes only — no payloads, addresses, message ids or tokens.
    """
    # Imported lazily to avoid importing FastAPI app state at module import
    # time (the routes module is imported during app construction).
    from selko.api.app import ingestion_runtime

    listener_status = None
    work_listener = getattr(request.app.state, "work_listener", None)
    if work_listener is not None:
        listener_status = work_listener.status()

    if ingestion_runtime is None:
        # Background processing disabled (local servers, tests, CI). Nothing
        # is running, so the system cannot be "down"; report the disabled
        # state instead of pretending ingestion is healthy.
        return HealthIngestionResponse(
            status="ok",
            background_processing_enabled=False,
            listener=listener_status,
        )

    try:
        snapshot = ingestion_runtime.health_snapshot()
    except Exception:
        logger.exception("Ingestion health snapshot failed")
        return HealthIngestionResponse(
            status="degraded",
            background_processing_enabled=True,
            instance_id=ingestion_runtime.instance_id,
            listener=listener_status,
        )

    return HealthIngestionResponse(
        status=snapshot["status"],
        background_processing_enabled=True,
        instance_id=snapshot.get("instance_id"),
        listener=listener_status,
        tasks=[
            HealthIngestionTaskResponse(**task) for task in snapshot.get("tasks", [])
        ],
        integrations_due=snapshot.get("integrations_due"),
        oldest_next_poll_seconds=snapshot.get("oldest_next_poll_seconds"),
        leases_held=snapshot.get("leases_held"),
        items_pending=snapshot.get("items_pending"),
        items_dead_letter=snapshot.get("items_dead_letter"),
        attachments_dead_letter=snapshot.get("attachments_dead_letter"),
        open_incidents=snapshot.get("open_incidents"),
        ready_emails=snapshot.get("ready_emails"),
        processing_emails=snapshot.get("processing_emails"),
        stale_processing_emails=snapshot.get("stale_processing_emails"),
        unclaimable_emails=snapshot.get("unclaimable_emails"),
        stale_sync_runs=snapshot.get("stale_sync_runs"),
    )


@router.get("/health/egress", response_model=HealthEgressResponse)
async def health_egress_check(request: Request) -> HealthEgressResponse:
    """Where this instance's outbound bytes are going.

    The platform bandwidth graph reports a monthly total with no attribution,
    which cannot distinguish a constant database polling loop from a genuine
    provider download — the two look identical at that level, and the fix for
    each is completely different. This route attributes the traffic per
    destination and operation.

    Counters are per-process and reset on restart. Read it against a
    long-running instance; a freshly deployed one has nothing to say yet.
    """
    snapshot = egress_snapshot()
    # Inc6: bytes per mailbox per day — supabase bytes projected per mailbox
    bytes_per_mailbox = None
    try:
        supabase_bytes = (snapshot.get("by_destination", {}).get("supabase", {}) or {}).get("bytes", 0) or snapshot.get("total_bytes", 0)
        # Best-effort mailbox count; failure degrades to total per day
        mailbox_count = 1
        try:
            from selko.services.auth import get_service_client
            from selko.config import load_config
            cfg = load_config()
            svc = get_service_client(cfg)
            # Count active email integrations (gmail/outlook)
            res = svc.table("integrations").select("id", count="exact").in_("provider", ["gmail", "outlook"]).eq("status", "active").execute()
            cnt = getattr(res, "count", None)
            if cnt is None and hasattr(res, "data"):
                cnt = len(res.data or [])
            if cnt and cnt > 0:
                mailbox_count = int(cnt)
        except Exception:
            mailbox_count = 1
        uptime = max(snapshot.get("uptime_seconds", 1), 1)
        bytes_per_day = supabase_bytes / uptime * 86400
        bytes_per_mailbox = int(bytes_per_day / max(mailbox_count, 1))
    except Exception:
        bytes_per_mailbox = None

    return HealthEgressResponse(
        uptime_seconds=snapshot["uptime_seconds"],
        total_calls=snapshot["total_calls"],
        total_bytes=snapshot["total_bytes"],
        calls_per_second=snapshot["calls_per_second"],
        bytes_per_hour=snapshot["bytes_per_hour"],
        projected_bytes_per_30d=snapshot["projected_bytes_per_30d"],
        by_destination=snapshot["by_destination"],
        top_operations=[
            EgressOperationResponse(**row) for row in snapshot["top_operations"]
        ],
        bytes_per_mailbox_per_day=bytes_per_mailbox,
        transport="asyncpg" if getattr(request.app.state, "pg_pool", None) is not None else "none",
    )
