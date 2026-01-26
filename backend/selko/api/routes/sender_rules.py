"""Sender rules API routes."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import get_authenticated_client
from selko.api.schemas.events import SenderRuleRequest, SenderRuleResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sender-rules", tags=["sender-rules"])


@router.get("", response_model=list[SenderRuleResponse])
async def list_sender_rules(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> list[SenderRuleResponse]:
    """List user's sender rules."""
    try:
        user_id = client.auth.get_user().user.id
        
        result = client.table("sender_rules").select("*").eq(
            "user_id", user_id
        ).order("created_at").execute()
        
        return [
            SenderRuleResponse(
                id=rule["id"],
                sender_domain=rule.get("sender_domain"),
                sender_email=rule.get("sender_email"),
                action=rule["action"],
                created_at=rule["created_at"],
            )
            for rule in result.data
        ]
        
    except Exception as e:
        logger.error(f"Failed to list sender rules: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=SenderRuleResponse)
async def create_sender_rule(
    request: SenderRuleRequest,
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> SenderRuleResponse:
    """Create rule (auto_approve or ignore)."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Validate at least one of domain or email is set
        if not request.sender_domain and not request.sender_email:
            raise HTTPException(
                status_code=400,
                detail="Either sender_domain or sender_email must be provided"
            )
        
        result = client.table("sender_rules").insert({
            "user_id": user_id,
            "sender_domain": request.sender_domain,
            "sender_email": request.sender_email,
            "action": request.action,
        }).execute()
        
        rule = result.data[0]
        
        return SenderRuleResponse(
            id=rule["id"],
            sender_domain=rule.get("sender_domain"),
            sender_email=rule.get("sender_email"),
            action=rule["action"],
            created_at=rule["created_at"],
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create sender rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{rule_id}")
async def delete_sender_rule(
    rule_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Delete rule."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        rule_result = client.table("sender_rules").select("user_id").eq(
            "id", str(rule_id)
        ).single().execute()
        
        if rule_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        client.table("sender_rules").delete().eq("id", str(rule_id)).execute()
        
        return {"status": "deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete sender rule: {e}")
        raise HTTPException(status_code=500, detail=str(e))
