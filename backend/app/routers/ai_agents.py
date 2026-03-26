"""
AI Agents Router
REST API for managing AI Agents and their tools, guardrails, channel assignments, and sandbox.
"""
import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.ai_agent import AIAgent, AIAgentTool, AIAgentGuardrail, AIAgentChannelAssignment
from app.models.channel import Channel
from app.schemas.ai_agent import (
    AIAgentCreate, AIAgentUpdate, AIAgentResponse,
    AIAgentToolCreate, AIAgentToolUpdate, AIAgentToolResponse,
    AIAgentGuardrailCreate, AIAgentGuardrailResponse,
    ChannelAssignmentResponse,
    ToolTestRequest, ToolTestResponse,
    SandboxMessageRequest, SandboxMessageResponse, DebugInfo,
    AgentAnalyticsResponse,
)
from app.services import ai_agent_service as svc
from app.services.tool_executor import ToolExecutor
from app.services.ai_agent_token_tracker import get_agent_analytics
from app.services.ai_agent_runner import AIAgentRunner
from app.config import TIER_LIMITS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-agents", tags=["ai-agents"])

# In-memory sandbox sessions: {agent_id: conversation_id}
_sandbox_sessions: dict = {}


# ─── Tier Gate Helper ─────────────────────────────────────────────────────────

def _require_ai_agents_tier(workspace: Workspace):
    limits = TIER_LIMITS.get(workspace.tier or "free", {})
    if limits.get("ai_agents", 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="AI Agents require Starter tier or above.",
        )


async def _get_agent_or_404(
    agent_id: UUID,
    workspace: Workspace,
    db: AsyncSession,
) -> AIAgent:
    agent = await svc.get_agent(db, str(agent_id), str(workspace.id))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# ─── Agent CRUD ───────────────────────────────────────────────────────────────

@router.post("/", response_model=AIAgentResponse, status_code=201)
async def create_agent(
    payload: AIAgentCreate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    _require_ai_agents_tier(workspace)
    # Check agent count limit
    limits = TIER_LIMITS.get(workspace.tier or "free", {})
    existing = await svc.get_agents(db, str(workspace.id))
    max_agents = limits.get("ai_agents", 0)
    if len(existing) >= max_agents:
        raise HTTPException(
            status_code=402,
            detail=f"AI agent limit ({max_agents}) reached for {workspace.tier} tier.",
        )

    agent = await svc.create_agent(db, str(workspace.id), **payload.model_dump())
    return agent


@router.get("", response_model=List[AIAgentResponse])
async def list_agents(
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return await svc.get_agents(db, str(workspace.id))


@router.get("/{agent_id}", response_model=AIAgentResponse)
async def get_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    return await _get_agent_or_404(agent_id, workspace, db)


@router.put("/{agent_id}", response_model=AIAgentResponse)
async def update_agent(
    agent_id: UUID,
    payload: AIAgentUpdate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    return await svc.update_agent(db, agent, **updates)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    await svc.delete_agent(db, agent)


@router.post("/{agent_id}/publish", response_model=AIAgentResponse)
async def publish_agent(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    try:
        return await svc.publish_agent(db, agent)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Tool CRUD ────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/tools", response_model=AIAgentToolResponse, status_code=201)
async def create_tool(
    agent_id: UUID,
    payload: AIAgentToolCreate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    data = payload.model_dump()
    # Serialize parameters list to plain dicts
    data["parameters"] = [p.model_dump() if hasattr(p, "model_dump") else p for p in data.get("parameters", [])]
    return await svc.create_tool(db, str(agent.id), **data)


@router.get("/{agent_id}/tools", response_model=List[AIAgentToolResponse])
async def list_tools(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    return agent.tools


@router.put("/{agent_id}/tools/{tool_id}", response_model=AIAgentToolResponse)
async def update_tool(
    agent_id: UUID,
    tool_id: UUID,
    payload: AIAgentToolUpdate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, workspace, db)
    tool = await svc.get_tool(db, str(tool_id), str(agent_id))
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    return await svc.update_tool(db, tool, **updates)


@router.delete("/{agent_id}/tools/{tool_id}", status_code=204)
async def delete_tool(
    agent_id: UUID,
    tool_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, workspace, db)
    tool = await svc.get_tool(db, str(tool_id), str(agent_id))
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    await svc.delete_tool(db, tool)


@router.post("/{agent_id}/tools/{tool_id}/test", response_model=ToolTestResponse)
async def test_tool(
    agent_id: UUID,
    tool_id: UUID,
    payload: ToolTestRequest,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Dry-run a tool call without quota charges."""
    await _get_agent_or_404(agent_id, workspace, db)
    tool = await svc.get_tool(db, str(tool_id), str(agent_id))
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    executor = ToolExecutor()
    result = await executor.execute(tool, payload.params)
    return ToolTestResponse(
        success=result.success,
        data=result.data,
        error=result.error,
        latency_ms=result.latency_ms,
        status_code=result.status_code,
    )


# ─── Guardrail CRUD ───────────────────────────────────────────────────────────

@router.post("/{agent_id}/guardrails", response_model=AIAgentGuardrailResponse, status_code=201)
async def create_guardrail(
    agent_id: UUID,
    payload: AIAgentGuardrailCreate,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    return await svc.create_guardrail(db, str(agent.id), payload.rule_type, payload.description)


@router.get("/{agent_id}/guardrails", response_model=List[AIAgentGuardrailResponse])
async def list_guardrails(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    return agent.guardrails


@router.delete("/{agent_id}/guardrails/{guardrail_id}", status_code=204)
async def delete_guardrail(
    agent_id: UUID,
    guardrail_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, workspace, db)
    guardrail = await svc.get_guardrail(db, str(guardrail_id), str(agent_id))
    if not guardrail:
        raise HTTPException(status_code=404, detail="Guardrail not found")
    await svc.delete_guardrail(db, guardrail)


# ─── Channel Assignments ──────────────────────────────────────────────────────

@router.post("/{agent_id}/channels/{channel_id}", response_model=ChannelAssignmentResponse, status_code=201)
async def assign_channel(
    agent_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    # Verify channel belongs to this workspace
    ch_result = await db.execute(
        select(Channel).where(Channel.id == channel_id, Channel.workspace_id == workspace.id)
    )
    channel = ch_result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return await svc.assign_channel(db, str(agent.id), str(channel_id))


@router.delete("/{agent_id}/channels/{channel_id}", status_code=204)
async def unassign_channel(
    agent_id: UUID,
    channel_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    removed = await svc.unassign_channel(db, str(agent.id), str(channel_id))
    if not removed:
        raise HTTPException(status_code=404, detail="Channel assignment not found")


# ─── Sandbox ──────────────────────────────────────────────────────────────────

@router.post("/{agent_id}/sandbox/message", response_model=SandboxMessageResponse)
async def sandbox_message(
    agent_id: UUID,
    payload: SandboxMessageRequest,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Send a test message to an agent in sandbox mode (no quota charge)."""
    agent = await _get_agent_or_404(agent_id, workspace, db)

    # Use a stable fake conversation_id per agent for sandbox
    conv_id = payload.conversation_id or f"sandbox-{agent_id}"

    runner = AIAgentRunner()
    result = await runner.run(
        db=db,
        conversation_id=conv_id,
        new_message=payload.message,
        workspace_id=str(workspace.id),
        sandbox=True,
        agent=agent,
    )

    debug = DebugInfo(
        tool_called=result.debug.get("tool_called"),
        tool_params=result.debug.get("tool_params"),
        tool_result=result.debug.get("tool_result"),
        tool_success=result.debug.get("tool_success"),
        tool_latency_ms=result.debug.get("tool_latency_ms"),
        model_used=result.debug.get("model_used", "unknown"),
        input_tokens=result.debug.get("input_tokens", 0),
        output_tokens=result.debug.get("output_tokens", 0),
        cost_usd=result.debug.get("cost_usd", 0.0),
        turn_count=result.debug.get("turn_count", 1),
        escalated=result.escalated,
    )

    return SandboxMessageResponse(
        reply=result.reply,
        escalated=result.escalated,
        escalation_reason=result.escalation_reason or None,
        debug=debug,
    )


@router.delete("/{agent_id}/sandbox/reset", status_code=204)
async def sandbox_reset(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    """Clear sandbox session for agent."""
    await _get_agent_or_404(agent_id, workspace, db)
    _sandbox_sessions.pop(str(agent_id), None)

    # Remove any sandbox ai_agent_conversations
    from sqlalchemy import delete as sql_delete
    from app.models.ai_agent import AIAgentConversation
    conv_id = f"sandbox-{agent_id}"
    await db.execute(
        sql_delete(AIAgentConversation).where(
            AIAgentConversation.conversation_id == conv_id
        )
    )
    await db.commit()


# ─── Analytics ────────────────────────────────────────────────────────────────

@router.get("/{agent_id}/analytics", response_model=AgentAnalyticsResponse)
async def get_analytics(
    agent_id: UUID,
    current_user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db),
):
    agent = await _get_agent_or_404(agent_id, workspace, db)
    data = await get_agent_analytics(db, str(agent.id))
    return AgentAnalyticsResponse(agent_id=agent.id, **data)
