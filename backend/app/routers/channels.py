"""
Channel Management Router
Handles channel creation, listing, and management with tier limit checking
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.schemas.widget_config import WidgetConfig
from app.services.channel_validator import ChannelValidator, ChannelValidationError
from app.services.tier_manager import TierManager, TierLimitError
from app.services.encryption import encrypt_credential, decrypt_credential


router = APIRouter(
    prefix="/api/channels",
    tags=["channels"],
    dependencies=[Depends(require_permission("channels.manage"))],
)


# ─── Request/Response Models ──────────────────────────────────────────────────

class ChannelCreateRequest(BaseModel):
    """Request model for creating a channel"""
    channel_type: str = Field(..., description="Channel type: telegram, whatsapp, instagram, webchat")
    name: str = Field(..., min_length=1, max_length=100, description="Channel display name")
    credentials: Dict[str, Any] = Field(..., description="Channel credentials")
    is_active: bool = Field(default=True, description="Whether channel is active")


class WebChatConfigRequest(BaseModel):
    """Request model for WebChat configuration"""
    business_name: str = Field(..., min_length=1, max_length=100)
    primary_color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    position: str = Field(..., pattern=r"^(bottom-right|bottom-left|top-right|top-left)$")
    welcome_message: str = Field(..., min_length=1, max_length=500)


class TelegramConfigRequest(BaseModel):
    """Request model for Telegram configuration"""
    bot_token: str = Field(..., min_length=1)


class WhatsAppConfigRequest(BaseModel):
    """Request model for WhatsApp configuration"""
    phone_number_id: str = Field(..., min_length=1)
    access_token: str = Field(..., min_length=1)


class InstagramConfigRequest(BaseModel):
    """Request model for Instagram configuration"""
    page_id: str = Field(..., min_length=1)
    access_token: str = Field(..., min_length=1)


class UnofficialWhatsAppConfigRequest(BaseModel):
    """Request model for unofficial WhatsApp (Baileys gateway) configuration.
    Gateway URL, API key, and webhook secret are read from server env vars.
    """
    tenant_id: str = Field(..., min_length=1, description="Unique session ID for this workspace on the gateway")


class ChannelResponse(BaseModel):
    """Response model for channel information"""
    id: str
    channel_type: str
    name: str
    is_active: bool
    widget_id: Optional[str] = None
    platform_info: Dict[str, Any]
    created_at: str
    updated_at: str


class ChannelUpdateRequest(BaseModel):
    """Request model for updating a channel"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    credentials: Optional[dict] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _decrypt_channel_config(channel: Channel) -> dict:
    """Decrypt all fields from channel.config, returning a plain dict."""
    raw = channel.config or {}
    decrypted: Dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str) and value:
            try:
                decrypted[key] = decrypt_credential(value)
            except Exception:
                decrypted[key] = value
        else:
            decrypted[key] = value
    return decrypted


def _build_webchat_platform_info(channel: Channel) -> tuple:
    """
    Return (widget_id, platform_info_dict) for a webchat channel.
    platform_info contains all 36 WidgetConfig fields with defaults for missing ones.

    widget_id is now read from the indexed `channel.widget_id` column
    (migration 033). The rest of WidgetConfig still lives in encrypted
    `channel.config` and is decrypted here. For transition rows where the
    column is NULL we fall back to the decrypted config value.
    """
    decrypted = _decrypt_channel_config(channel)
    widget_id = channel.widget_id or decrypted.get("widget_id")
    config_fields = {k: v for k, v in decrypted.items() if k != "widget_id"}
    platform_info = WidgetConfig(**config_fields).model_dump()
    return widget_id, platform_info


# ─── Channel Management Endpoints ─────────────────────────────────────────────

@router.post("/", response_model=ChannelResponse, status_code=201)
async def create_channel(
    request: ChannelCreateRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new channel for the workspace
    
    Args:
        request: Channel creation request
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Created channel information
    
    Raises:
        HTTPException: If validation fails or tier limits exceeded
    """
    try:
        # Check tier limits
        tier_manager = TierManager(db)
        await tier_manager.check_channel_limit(current_workspace.id)
        
        # Validate channel credentials
        validator = ChannelValidator()
        validation_result = await validator.validate_channel_credentials(
            request.channel_type, 
            request.credentials
        )
        
        # Merge validation result (includes widget_id for WebChat) with credentials
        credentials_to_store = {**request.credentials}
        if "widget_id" in validation_result:
            credentials_to_store["widget_id"] = validation_result["widget_id"]

        # For webchat: validate through WidgetConfig so all 36 fields are stored with defaults
        if request.channel_type == "webchat":
            config_fields = {k: v for k, v in credentials_to_store.items() if k != "widget_id"}
            validated_cfg = WidgetConfig(**config_fields)
            credentials_to_store = {
                "widget_id": credentials_to_store["widget_id"],
                **validated_cfg.model_dump(),
            }

        # Encrypt credentials for storage
        encrypted_credentials = {}
        for key, value in credentials_to_store.items():
            if isinstance(value, str) and value:
                encrypted_credentials[key] = encrypt_credential(value)
            else:
                encrypted_credentials[key] = value
        
        # Create channel record. For webchat channels we ALSO write widget_id
        # to the new indexed column on `channels`. We intentionally still keep
        # the encrypted widget_id inside `config` for one deploy cycle of
        # backward compat — a follow-up cleanup PR removes it from config
        # once we've confirmed no old-code worker is reading from there.
        channel = Channel(
            workspace_id=current_workspace.id,
            type=request.channel_type,
            is_active=request.is_active,
            config=encrypted_credentials,
            widget_id=credentials_to_store.get("widget_id") if request.channel_type == "webchat" else None,
        )
        
        db.add(channel)
        await db.commit()
        await db.refresh(channel)

        # Telegram channels must auto-register webhook after successful creation.
        if request.channel_type == "telegram" and request.is_active:
            bot_token = request.credentials.get("bot_token")
            try:
                await validator.register_telegram_webhook(bot_token)
            except ChannelValidationError:
                # Compensating action: remove partially created channel if webhook setup fails.
                await db.delete(channel)
                await db.commit()
                raise
        
        if channel.type == "webchat":
            widget_id_val, platform_info = _build_webchat_platform_info(channel)
        else:
            widget_id_val = validation_result.get("widget_id")
            platform_info = validation_result

        return ChannelResponse(
            id=str(channel.id),
            channel_type=channel.type,
            name=request.name,
            is_active=channel.is_active,
            widget_id=widget_id_val,
            platform_info=platform_info,
            created_at=channel.created_at.isoformat(),
            updated_at=channel.created_at.isoformat()  # No updated_at in model
        )
        
    except TierLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except ChannelValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Channel validation failed: {str(e)}"
        )
    except IntegrityError as e:
        await db.rollback()
        if "uq_workspace_channel_type" in str(e.orig):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A {request.channel_type} channel already exists for this workspace"
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Channel already exists"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create channel: {str(e)}"
        )


@router.get("/", response_model=List[ChannelResponse])
async def list_channels(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    List all channels for the workspace
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of channels
    """
    try:
        result = await db.execute(
            select(Channel)
            .where(Channel.workspace_id == current_workspace.id)
            .order_by(Channel.created_at.desc())
        )
        channels = result.scalars().all()
        
        channel_list = []
        for channel in channels:
            if channel.type == "webchat":
                widget_id_val, platform_info = _build_webchat_platform_info(channel)
            else:
                widget_id_val = None
                platform_info = {}
            channel_list.append(ChannelResponse(
                id=str(channel.id),
                channel_type=channel.type,
                name=f"{channel.type.capitalize()} Channel",
                is_active=channel.is_active,
                widget_id=widget_id_val,
                platform_info=platform_info,
                created_at=channel.created_at.isoformat(),
                updated_at=channel.created_at.isoformat()
            ))
        
        return channel_list
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list channels: {str(e)}"
        )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get channel by ID
    
    Args:
        channel_id: Channel ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Channel information
    
    Raises:
        HTTPException: If channel not found
    """
    try:
        result = await db.execute(
            select(Channel)
            .where(Channel.id == channel_id)
            .where(Channel.workspace_id == current_workspace.id)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found"
            )
        
        if channel.type == "webchat":
            widget_id_val, platform_info = _build_webchat_platform_info(channel)
        else:
            widget_id_val = None
            platform_info = {}

        return ChannelResponse(
            id=str(channel.id),
            channel_type=channel.type,
            name=f"{channel.type.capitalize()} Channel",
            is_active=channel.is_active,
            widget_id=widget_id_val,
            platform_info=platform_info,
            created_at=channel.created_at.isoformat(),
            updated_at=channel.created_at.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get channel: {str(e)}"
        )


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    request: ChannelUpdateRequest,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Update channel information
    
    Args:
        channel_id: Channel ID
        request: Update request
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Updated channel information
    
    Raises:
        HTTPException: If channel not found
    """
    try:
        result = await db.execute(
            select(Channel)
            .where(Channel.id == channel_id)
            .where(Channel.workspace_id == current_workspace.id)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found"
            )
        
        # Track old state so we can trigger side effects on activation.
        old_is_active = channel.is_active

        # Update fields
        if request.is_active is not None:
            channel.is_active = request.is_active
        # Note: name is not stored in the simple Channel model

        # Merge and validate webchat credentials
        if request.credentials is not None and channel.type == "webchat":
            existing = _decrypt_channel_config(channel)
            merged = {**existing, **request.credentials}
            validated_cfg = WidgetConfig(**{k: v for k, v in merged.items() if k != "widget_id"})
            plain_dict = validated_cfg.model_dump()
            new_config: Dict[str, Any] = {}
            for key, value in plain_dict.items():
                if isinstance(value, str) and value:
                    new_config[key] = encrypt_credential(value)
                else:
                    new_config[key] = value
            # Preserve the existing encrypted widget_id
            if "widget_id" in (channel.config or {}):
                new_config["widget_id"] = channel.config["widget_id"]
            channel.config = new_config

        # Re-activate Telegram webhook when channel transitions to active.
        if channel.type == "telegram" and request.is_active is True and not old_is_active:
            validator = ChannelValidator()
            encrypted_token = (channel.config or {}).get("bot_token")
            if not encrypted_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Telegram channel is missing bot_token configuration"
                )
            bot_token = decrypt_credential(encrypted_token)
            await validator.register_telegram_webhook(bot_token)

        await db.commit()
        await db.refresh(channel)

        # Invalidate the widget cache (L1 + L2) on every webchat update —
        # deactivation, config change, or a future widget_id change all
        # need other workers to refetch. Cheap if a no-op.
        if channel.type == "webchat" and channel.widget_id:
            from app.services.widget_cache import invalidate_widget_cache
            await invalidate_widget_cache(channel.widget_id)

        if channel.type == "webchat":
            widget_id_val, platform_info = _build_webchat_platform_info(channel)
        else:
            widget_id_val = None
            platform_info = {}

        return ChannelResponse(
            id=str(channel.id),
            channel_type=channel.type,
            name=f"{channel.type.capitalize()} Channel",
            is_active=channel.is_active,
            widget_id=widget_id_val,
            platform_info=platform_info,
            created_at=channel.created_at.isoformat(),
            updated_at=channel.created_at.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update channel: {str(e)}"
        )


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a channel
    
    Args:
        channel_id: Channel ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If channel not found
    """
    try:
        result = await db.execute(
            select(Channel)
            .where(Channel.id == channel_id)
            .where(Channel.workspace_id == current_workspace.id)
        )
        channel = result.scalar_one_or_none()
        
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Channel not found"
            )

        # Capture widget_id before delete so we can invalidate caches after commit.
        deleted_widget_id = channel.widget_id if channel.type == "webchat" else None

        await db.delete(channel)
        await db.commit()

        if deleted_widget_id:
            from app.services.widget_cache import invalidate_widget_cache
            await invalidate_widget_cache(deleted_widget_id)

        return Response(status_code=204)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete channel: {str(e)}"
        )


# ─── Channel Validation Endpoints ─────────────────────────────────────────────

@router.post("/validate/{channel_type}")
async def validate_channel_credentials(
    channel_type: str,
    credentials: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace)
):
    """
    Validate channel credentials without creating a channel
    
    Args:
        channel_type: Channel type
        credentials: Channel credentials
        current_user: Current authenticated user
        current_workspace: Current workspace
    
    Returns:
        Validation result
    
    Raises:
        HTTPException: If validation fails
    """
    try:
        validator = ChannelValidator()
        validation_result = await validator.validate_channel_credentials(
            channel_type, 
            credentials
        )
        
        return {
            "valid": True,
            "channel_type": channel_type,
            "validation_result": validation_result
        }
        
    except ChannelValidationError as e:
        return {
            "valid": False,
            "channel_type": channel_type,
            "error": str(e)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation error: {str(e)}"
        )


# ─── Channel Statistics Endpoint ──────────────────────────────────────────────

@router.get("/stats/summary")
async def get_channel_statistics(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Get channel statistics for the workspace
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Channel statistics
    """
    try:
        from sqlalchemy import func
        
        # Get channel counts by type and status
        result = await db.execute(
            select(
                Channel.type,
                Channel.is_active,
                func.count(Channel.id).label('count')
            )
            .where(Channel.workspace_id == current_workspace.id)
            .group_by(Channel.type, Channel.is_active)
        )
        
        stats = {
            "total_channels": 0,
            "active_channels": 0,
            "inactive_channels": 0,
            "by_type": {}
        }
        
        for row in result:
            channel_type = row.type
            is_active = row.is_active
            count = row.count
            
            stats["total_channels"] += count
            
            if is_active:
                stats["active_channels"] += count
            else:
                stats["inactive_channels"] += count
            
            if channel_type not in stats["by_type"]:
                stats["by_type"][channel_type] = {"active": 0, "inactive": 0}
            
            if is_active:
                stats["by_type"][channel_type]["active"] += count
            else:
                stats["by_type"][channel_type]["inactive"] += count
        
        # Get tier information
        tier_manager = TierManager(db)
        tier_info = await tier_manager.get_workspace_tier_info(current_workspace.id)
        
        stats["tier_info"] = {
            "current_tier": tier_info["tier"],
            "channel_limit": tier_info["limits"]["channels"],
            "channels_remaining": tier_info["remaining"]["channels"]
        }
        
        return stats
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get channel statistics: {str(e)}"
        )