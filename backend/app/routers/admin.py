"""
Platform Administration Routes
Super admin endpoints for platform management
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.user import User
from app.services.admin_service import AdminService
from app.middleware.auth_middleware import get_current_user


router = APIRouter(prefix="/api/admin", tags=["administration"])


# Request/Response Models
class PlatformOverviewResponse(BaseModel):
    """Platform overview statistics"""
    total_workspaces: int
    total_users: int
    active_users: int
    tier_breakdown: dict
    current_month_stats: dict
    recent_activity: dict


class WorkspaceListItem(BaseModel):
    """Workspace list item"""
    id: str
    name: str
    slug: str
    tier: str
    owner_email: str
    owner_active: bool
    created_at: str
    tier_changed_at: Optional[str] = None
    tier_changed_by: Optional[str] = None


class UserListItem(BaseModel):
    """User list item"""
    id: str
    email: str
    is_active: bool
    created_at: str
    last_login: Optional[str] = None
    workspace: Optional[dict] = None


class UserActionRequest(BaseModel):
    """User action request"""
    user_id: UUID = Field(..., description="User ID to perform action on")


class TierChangeRequest(BaseModel):
    """Tier change request"""
    workspace_id: UUID = Field(..., description="Workspace ID")
    new_tier: str = Field(..., description="New tier (free, starter, growth, pro)")
    reason: Optional[str] = Field(None, description="Reason for tier change")


class TierChangeHistoryItem(BaseModel):
    """Tier change history item"""
    id: str
    workspace_id: str
    workspace_name: str
    workspace_slug: str
    from_tier: str
    to_tier: str
    changed_by: str
    note: Optional[str] = None
    created_at: str


class WorkspaceDeletionRequest(BaseModel):
    """Workspace deletion request"""
    workspace_id: UUID = Field(..., description="Workspace ID to delete")
    confirmation_name: str = Field(..., description="Workspace name for confirmation")


class AnalyticsDashboardResponse(BaseModel):
    """Analytics dashboard response"""
    message_volume: dict
    signup_trends: dict
    escalation_statistics: dict


class MessageResponse(BaseModel):
    """Generic message response"""
    message: str


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """
    Dependency to require super admin access
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        User if super admin
        
    Raises:
        HTTPException: If not super admin
    """
    from app.config import settings
    
    if current_user.email.lower() != settings.SUPER_ADMIN_EMAIL.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required"
        )
    
    return current_user


@router.get("/overview", response_model=PlatformOverviewResponse)
async def get_platform_overview(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get platform overview with statistics and metrics
    
    Returns workspace counts by tier, user activity, and recent signups.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    overview = await admin_service.get_platform_overview()
    
    return PlatformOverviewResponse(**overview)


@router.get("/workspaces", response_model=List[WorkspaceListItem])
async def list_workspaces(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of workspaces to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    tier: Optional[str] = Query(None, description="Filter by tier (free, starter, growth, pro)")
):
    """
    Get paginated list of workspaces with owner information
    
    Returns workspace details including owner email and tier information.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    workspaces = await admin_service.get_workspace_list(
        limit=limit,
        offset=offset,
        tier_filter=tier
    )
    
    return [WorkspaceListItem(**workspace) for workspace in workspaces]


@router.get("/users", response_model=List[UserListItem])
async def list_users(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of users to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    active_only: bool = Query(False, description="Only return active users")
):
    """
    Get paginated list of users with workspace information
    
    Returns user details including workspace information and activity status.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    users = await admin_service.get_user_list(
        limit=limit,
        offset=offset,
        active_only=active_only
    )
    
    return [UserListItem(**user) for user in users]


@router.post("/users/suspend", response_model=MessageResponse)
async def suspend_user(
    request: UserActionRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Suspend a user account
    
    Deactivates the user account, preventing login.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    
    try:
        await admin_service.suspend_user(
            user_id=request.user_id,
            admin_email=current_user.email
        )
        
        return MessageResponse(message="User suspended successfully")
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users/unsuspend", response_model=MessageResponse)
async def unsuspend_user(
    request: UserActionRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Unsuspend a user account
    
    Reactivates the user account, allowing login.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    
    try:
        await admin_service.unsuspend_user(
            user_id=request.user_id,
            admin_email=current_user.email
        )
        
        return MessageResponse(message="User unsuspended successfully")
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/workspaces/change-tier", response_model=MessageResponse)
async def change_workspace_tier(
    request: TierChangeRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Change workspace tier with audit logging
    
    Updates workspace tier and records the change for audit purposes.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    
    try:
        await admin_service.change_workspace_tier(
            workspace_id=request.workspace_id,
            new_tier=request.new_tier,
            admin_email=current_user.email,
            reason=request.reason
        )
        
        return MessageResponse(message=f"Workspace tier changed to {request.new_tier}")
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/tier-changes", response_model=List[TierChangeHistoryItem])
async def get_tier_change_history(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[UUID] = Query(None, description="Filter by workspace ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of records to return")
):
    """
    Get tier change history with audit information
    
    Returns historical tier changes with admin information and reasons.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    changes = await admin_service.get_tier_change_history(
        workspace_id=workspace_id,
        limit=limit
    )
    
    return [TierChangeHistoryItem(**change) for change in changes]


@router.delete("/workspaces/delete", response_model=MessageResponse)
async def delete_workspace(
    request: WorkspaceDeletionRequest,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete workspace with name confirmation for safety
    
    Permanently deletes a workspace and all associated data.
    Requires workspace name confirmation to prevent accidental deletion.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    
    try:
        await admin_service.delete_workspace(
            workspace_id=request.workspace_id,
            confirmation_name=request.confirmation_name,
            admin_email=current_user.email
        )
        
        return MessageResponse(message="Workspace deleted successfully")
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/feedback/stats")
async def get_feedback_stats(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    workspace_id: Optional[UUID] = Query(None, description="Filter by workspace ID")
):
    """
    Get aggregate AI response feedback statistics.
    Returns positive/negative counts per workspace (or for a specific workspace).
    Only accessible by super admin.
    """
    from sqlalchemy import select, func
    from app.models.ai_feedback import AIFeedback
    from app.models.workspace import Workspace as WorkspaceModel

    query = (
        select(
            AIFeedback.workspace_id,
            AIFeedback.rating,
            func.count(AIFeedback.id).label("count")
        )
        .group_by(AIFeedback.workspace_id, AIFeedback.rating)
    )
    if workspace_id:
        query = query.where(AIFeedback.workspace_id == workspace_id)

    result = await db.execute(query)
    rows = result.all()

    # Aggregate into per-workspace dict
    stats: dict = {}
    for row in rows:
        ws_id = str(row.workspace_id)
        if ws_id not in stats:
            stats[ws_id] = {"workspace_id": ws_id, "positive": 0, "negative": 0, "total": 0}
        stats[ws_id][row.rating] = row.count
        stats[ws_id]["total"] += row.count

    return {"feedback_stats": list(stats.values())}


@router.get("/token-usage", response_model=List[dict])
async def get_token_usage_summary(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
    month: Optional[str] = Query(None, description="Month YYYY-MM, defaults to current month"),
    tier: Optional[str] = Query(None, description="Filter by workspace tier"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Per-workspace monthly token and cost summary.
    Sorted by total cost descending — highest-spend clients first.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    return await admin_service.get_token_usage_summary(
        month=month,
        tier_filter=tier,
        limit=limit,
        offset=offset,
    )


@router.get("/token-usage/{workspace_id}", response_model=dict)
async def get_workspace_token_detail(
    workspace_id: UUID,
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Detailed token/cost breakdown for a single workspace.
    Returns 12-month history, per-call-type and per-model breakdowns.
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    detail = await admin_service.get_workspace_token_detail(str(workspace_id))
    if not detail.get("workspace_name"):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return detail


@router.get("/analytics", response_model=AnalyticsDashboardResponse)
async def get_analytics_dashboard(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Get analytics dashboard with message volume, signup trends, and escalation statistics
    
    Returns comprehensive analytics including:
    - Message volume trends over the last 12 months
    - Signup trends and growth metrics
    - Escalation statistics and rates
    
    Only accessible by super admin.
    """
    admin_service = AdminService(db)
    analytics = await admin_service.get_analytics_dashboard()
    
    return AnalyticsDashboardResponse(**analytics)