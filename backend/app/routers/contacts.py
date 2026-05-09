"""
Contact Management Router
Full CRUD for contacts: search, tag, block, and GDPR delete
"""
from typing import List, Optional, Any, Dict
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, get_workspace_from_token, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.config import TIER_LIMITS


router = APIRouter(prefix="/api/contacts", tags=["contacts"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    id: str
    status: str
    channel_type: str
    created_at: str
    updated_at: str


class ContactOut(BaseModel):
    id: str
    external_id: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    tags: List[str]
    custom_fields: Dict[str, Any]
    source: Optional[str]
    is_blocked: bool
    created_at: str


class ContactDetailOut(ContactOut):
    recent_conversations: List[ConversationSummary]


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    email: Optional[str] = Field(None, max_length=320)
    phone: Optional[str] = Field(None, max_length=50)
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


class ContactListResponse(BaseModel):
    contacts: List[ContactOut]
    total_count: int
    has_more: bool


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_out(c: Contact) -> ContactOut:
    return ContactOut(
        id=str(c.id),
        external_id=c.external_id,
        name=c.name,
        email=c.email,
        phone=c.phone,
        tags=c.tags or [],
        custom_fields=c.custom_fields or {},
        source=c.source,
        is_blocked=c.is_blocked,
        created_at=c.created_at.isoformat(),
    )


def _has_custom_fields(workspace: Workspace) -> bool:
    return TIER_LIMITS.get(workspace.tier or "free", {}).get("has_api_access", False)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=ContactListResponse)
async def list_contacts(
    q: Optional[str] = Query(None, description="Search by name, email, or phone"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    is_blocked: Optional[bool] = Query(None, description="Filter by blocked status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """List contacts for the workspace with optional search and filters."""
    query = select(Contact).where(Contact.workspace_id == current_workspace.id)

    if q:
        q_pat = f"%{q}%"
        query = query.where(
            or_(
                Contact.name.ilike(q_pat),
                Contact.email.ilike(q_pat),
                Contact.phone.ilike(q_pat),
            )
        )

    if tag is not None:
        query = query.where(Contact.tags.contains([tag]))

    if is_blocked is not None:
        query = query.where(Contact.is_blocked == is_blocked)

    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total_count = count_result.scalar() or 0

    query = query.order_by(Contact.created_at.desc()).limit(limit + 1).offset(offset)
    result = await db.execute(query)
    contacts = result.scalars().all()
    has_more = len(contacts) > limit
    contacts = contacts[:limit]

    return ContactListResponse(
        contacts=[_to_out(c) for c in contacts],
        total_count=total_count,
        has_more=has_more,
    )


@router.get("/{contact_id}", response_model=ContactDetailOut)
async def get_contact(
    contact_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Get contact detail with recent conversation history."""
    result = await db.execute(
        select(Contact)
        .where(Contact.id == UUID(contact_id))
        .where(Contact.workspace_id == current_workspace.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    conv_result = await db.execute(
        select(Conversation)
        .where(Conversation.contact_id == contact.id)
        .order_by(Conversation.updated_at.desc())
        .limit(10)
    )
    conversations = conv_result.scalars().all()

    base = _to_out(contact)
    return ContactDetailOut(
        **base.model_dump(),
        recent_conversations=[
            ConversationSummary(
                id=str(c.id),
                status=c.status,
                channel_type=c.channel_type,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in conversations
        ],
    )


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: str,
    request: ContactUpdate,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Update contact fields. custom_fields requires Growth+ tier."""
    result = await db.execute(
        select(Contact)
        .where(Contact.id == UUID(contact_id))
        .where(Contact.workspace_id == current_workspace.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    if request.custom_fields is not None and not _has_custom_fields(current_workspace):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="custom_fields requires Growth or Pro tier.",
        )

    if request.name is not None:
        contact.name = request.name
    if request.email is not None:
        contact.email = request.email
    if request.phone is not None:
        contact.phone = request.phone
    if request.tags is not None:
        contact.tags = request.tags
    if request.custom_fields is not None:
        contact.custom_fields = request.custom_fields

    await db.commit()
    await db.refresh(contact)

    # Fire outbound webhook (fire-and-forget)
    from app.services.outbound_webhook_service import trigger_event
    from app.utils.tasks import safe_create_task
    safe_create_task(trigger_event(
        workspace_id=str(current_workspace.id),
        event_type="contact.updated",
        payload={"workspace_id": str(current_workspace.id), "contact_id": str(contact.id)},
    ), name="outbound_webhook.contact.updated")

    return _to_out(contact)


@router.post("/{contact_id}/block", response_model=dict, dependencies=[Depends(require_permission("contacts.moderation"))])
async def block_contact(
    contact_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Block a contact. Blocked contacts receive an auto-reply and are not processed through AI."""
    result = await db.execute(
        select(Contact)
        .where(Contact.id == UUID(contact_id))
        .where(Contact.workspace_id == current_workspace.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.is_blocked = True
    await db.commit()
    return {"message": "Contact blocked", "contact_id": contact_id}


@router.post("/{contact_id}/unblock", response_model=dict, dependencies=[Depends(require_permission("contacts.moderation"))])
async def unblock_contact(
    contact_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Unblock a previously blocked contact."""
    result = await db.execute(
        select(Contact)
        .where(Contact.id == UUID(contact_id))
        .where(Contact.workspace_id == current_workspace.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    contact.is_blocked = False
    await db.commit()
    return {"message": "Contact unblocked", "contact_id": contact_id}


@router.delete("/{contact_id}", status_code=204, dependencies=[Depends(require_permission("contacts.moderation"))])
async def delete_contact(
    contact_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_workspace_from_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a contact and all their data (GDPR compliance).
    Cascades to conversations and messages via FK constraints.
    """
    result = await db.execute(
        select(Contact)
        .where(Contact.id == UUID(contact_id))
        .where(Contact.workspace_id == current_workspace.id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    await db.delete(contact)
    await db.commit()
