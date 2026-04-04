"""
WhatsApp Templates Router
CRUD + Meta submission for WhatsApp message templates
"""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.auth_middleware import get_current_workspace, require_permission
from app.models.whatsapp_template import WhatsAppTemplate
from app.models.workspace import Workspace
from app.services.template_service import submit_template_to_meta

router = APIRouter(
    prefix="/api/templates",
    tags=["templates"],
    dependencies=[Depends(require_permission("automation.templates"))],
)


class TemplateCreate(BaseModel):
    name: str
    category: str           # MARKETING | UTILITY | AUTHENTICATION
    language: str           # en | hi | ml | ta
    header_type: Optional[str] = None
    header_content: Optional[str] = None
    body: str
    footer: Optional[str] = None
    buttons: Optional[list] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    header_type: Optional[str] = None
    header_content: Optional[str] = None
    body: Optional[str] = None
    footer: Optional[str] = None
    buttons: Optional[list] = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    template = WhatsAppTemplate(
        workspace_id=str(workspace.id),
        **body.model_dump()
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.get("")
async def list_templates(
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WhatsAppTemplate)
        .where(WhatsAppTemplate.workspace_id == str(workspace.id))
        .order_by(WhatsAppTemplate.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{template_id}")
async def get_template(
    template_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return await _get_template_or_404(db, template_id, workspace.id)


@router.put("/{template_id}")
async def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template_or_404(db, template_id, workspace.id)
    if template.status not in ("draft", "rejected"):
        raise HTTPException(status_code=400, detail="Only draft or rejected templates can be edited")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(template, field, value)
    template.status = "draft"
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template_or_404(db, template_id, workspace.id)
    await db.delete(template)
    await db.commit()


@router.post("/{template_id}/submit")
async def submit_template(
    template_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template_or_404(db, template_id, workspace.id)
    if template.status not in ("draft", "rejected"):
        raise HTTPException(status_code=400, detail="Only draft or rejected templates can be submitted")
    template = await submit_template_to_meta(db, template, str(workspace.id))
    return {"status": template.status, "meta_template_id": template.meta_template_id}


@router.get("/{template_id}/preview")
async def preview_template(
    template_id: UUID,
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    template = await _get_template_or_404(db, template_id, workspace.id)
    return {
        "name": template.name,
        "language": template.language,
        "header": {"type": template.header_type, "content": template.header_content},
        "body": template.body,
        "footer": template.footer,
        "buttons": template.buttons,
    }


async def _get_template_or_404(db: AsyncSession, template_id: UUID, workspace_id) -> WhatsAppTemplate:
    result = await db.execute(
        select(WhatsAppTemplate)
        .where(WhatsAppTemplate.id == str(template_id))
        .where(WhatsAppTemplate.workspace_id == str(workspace_id))
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template
