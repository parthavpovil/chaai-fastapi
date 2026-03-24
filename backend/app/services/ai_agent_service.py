"""
AI Agent Service
CRUD operations and channel-to-agent lookup for AI Agents
"""
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.ai_agent import (
    AIAgent, AIAgentTool, AIAgentGuardrail,
    AIAgentChannelAssignment, AIAgentConversation,
)


# ─── Agent CRUD ───────────────────────────────────────────────────────────────

async def create_agent(
    db: AsyncSession,
    workspace_id: str,
    **kwargs,
) -> AIAgent:
    agent = AIAgent(workspace_id=workspace_id, **kwargs)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


async def get_agent(
    db: AsyncSession,
    agent_id: str,
    workspace_id: str,
) -> Optional[AIAgent]:
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.guardrails))
        .where(AIAgent.id == agent_id, AIAgent.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()


async def get_agents(
    db: AsyncSession,
    workspace_id: str,
) -> List[AIAgent]:
    result = await db.execute(
        select(AIAgent)
        .options(selectinload(AIAgent.tools), selectinload(AIAgent.guardrails))
        .where(AIAgent.workspace_id == workspace_id)
        .order_by(AIAgent.created_at.desc())
    )
    return list(result.scalars().all())


async def update_agent(
    db: AsyncSession,
    agent: AIAgent,
    **kwargs,
) -> AIAgent:
    for key, value in kwargs.items():
        if value is not None:
            setattr(agent, key, value)
    await db.commit()
    await db.refresh(agent)
    return agent


async def delete_agent(db: AsyncSession, agent: AIAgent) -> None:
    await db.delete(agent)
    await db.commit()


async def publish_agent(db: AsyncSession, agent: AIAgent) -> AIAgent:
    """Validate and mark an agent as live (not draft)."""
    errors = []
    if not agent.system_prompt or not agent.system_prompt.strip():
        errors.append("system_prompt is required")
    if not agent.escalation_message or not agent.escalation_message.strip():
        errors.append("escalation_message is required")

    # Load tools count
    result = await db.execute(
        select(AIAgentTool).where(AIAgentTool.agent_id == agent.id, AIAgentTool.is_active == True)
    )
    tools = result.scalars().all()
    if len(tools) == 0:
        errors.append("at least one active tool is required to publish")

    if errors:
        raise ValueError(f"Agent validation failed: {'; '.join(errors)}")

    agent.is_draft = False
    await db.commit()
    await db.refresh(agent)
    return agent


# ─── Tool CRUD ────────────────────────────────────────────────────────────────

async def create_tool(
    db: AsyncSession,
    agent_id: str,
    **kwargs,
) -> AIAgentTool:
    tool = AIAgentTool(agent_id=agent_id, **kwargs)
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return tool


async def get_tool(
    db: AsyncSession,
    tool_id: str,
    agent_id: str,
) -> Optional[AIAgentTool]:
    result = await db.execute(
        select(AIAgentTool).where(AIAgentTool.id == tool_id, AIAgentTool.agent_id == agent_id)
    )
    return result.scalar_one_or_none()


async def update_tool(
    db: AsyncSession,
    tool: AIAgentTool,
    **kwargs,
) -> AIAgentTool:
    for key, value in kwargs.items():
        if value is not None:
            setattr(tool, key, value)
    await db.commit()
    await db.refresh(tool)
    return tool


async def delete_tool(db: AsyncSession, tool: AIAgentTool) -> None:
    await db.delete(tool)
    await db.commit()


# ─── Guardrail CRUD ───────────────────────────────────────────────────────────

async def create_guardrail(
    db: AsyncSession,
    agent_id: str,
    rule_type: str,
    description: str,
) -> AIAgentGuardrail:
    guardrail = AIAgentGuardrail(agent_id=agent_id, rule_type=rule_type, description=description)
    db.add(guardrail)
    await db.commit()
    await db.refresh(guardrail)
    return guardrail


async def delete_guardrail(db: AsyncSession, guardrail: AIAgentGuardrail) -> None:
    await db.delete(guardrail)
    await db.commit()


async def get_guardrail(
    db: AsyncSession,
    guardrail_id: str,
    agent_id: str,
) -> Optional[AIAgentGuardrail]:
    result = await db.execute(
        select(AIAgentGuardrail).where(
            AIAgentGuardrail.id == guardrail_id,
            AIAgentGuardrail.agent_id == agent_id,
        )
    )
    return result.scalar_one_or_none()


# ─── Channel Assignment CRUD ──────────────────────────────────────────────────

async def assign_channel(
    db: AsyncSession,
    agent_id: str,
    channel_id: str,
    priority: int = 0,
) -> AIAgentChannelAssignment:
    # Check for existing assignment
    result = await db.execute(
        select(AIAgentChannelAssignment).where(
            AIAgentChannelAssignment.agent_id == agent_id,
            AIAgentChannelAssignment.channel_id == channel_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.priority = priority
        await db.commit()
        await db.refresh(existing)
        return existing

    assignment = AIAgentChannelAssignment(agent_id=agent_id, channel_id=channel_id, priority=priority)
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def unassign_channel(
    db: AsyncSession,
    agent_id: str,
    channel_id: str,
) -> bool:
    result = await db.execute(
        select(AIAgentChannelAssignment).where(
            AIAgentChannelAssignment.agent_id == agent_id,
            AIAgentChannelAssignment.channel_id == channel_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        return False
    await db.delete(assignment)
    await db.commit()
    return True


# ─── Runtime Lookup ───────────────────────────────────────────────────────────

async def get_agent_for_channel(
    db: AsyncSession,
    channel_id: str,
) -> Optional[AIAgent]:
    """
    Find the active, published AI agent assigned to this channel.
    Returns None if no agent is assigned (pipeline falls through to RAG).
    """
    result = await db.execute(
        select(AIAgent)
        .join(AIAgentChannelAssignment, AIAgentChannelAssignment.agent_id == AIAgent.id)
        .options(
            selectinload(AIAgent.tools),
            selectinload(AIAgent.guardrails),
        )
        .where(
            AIAgentChannelAssignment.channel_id == channel_id,
            AIAgentChannelAssignment.is_active == True,
            AIAgent.is_active == True,
            AIAgent.is_draft == False,
        )
        .order_by(AIAgentChannelAssignment.priority.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_or_create_session(
    db: AsyncSession,
    agent_id: str,
    conversation_id: str,
    workspace_id: str,
) -> AIAgentConversation:
    """Get an existing active session or create a new one."""
    result = await db.execute(
        select(AIAgentConversation).where(
            AIAgentConversation.agent_id == agent_id,
            AIAgentConversation.conversation_id == conversation_id,
            AIAgentConversation.status == "active",
        )
    )
    session = result.scalar_one_or_none()
    if session:
        return session

    session = AIAgentConversation(
        agent_id=agent_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        status="active",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session
