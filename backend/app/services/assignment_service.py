"""
Assignment Service
Evaluates assignment rules and routes conversations to agents
"""
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.assignment_rule import AssignmentRule
from app.models.agent import Agent
from app.models.conversation import Conversation


async def evaluate_rules(
    db: AsyncSession,
    workspace_id: UUID,
    message_content: str,
    channel_type: str
) -> Optional[AssignmentRule]:
    """
    Evaluate assignment rules in priority order and return the first match.

    Conditions schema: {"keywords": ["billing"], "channel_type": "whatsapp"}
    All specified conditions must match.
    """
    result = await db.execute(
        select(AssignmentRule)
        .where(AssignmentRule.workspace_id == workspace_id)
        .where(AssignmentRule.is_active == True)
        .order_by(AssignmentRule.priority.asc())
    )
    rules = result.scalars().all()

    for rule in rules:
        if _rule_matches(rule, message_content, channel_type):
            return rule

    return None


def _rule_matches(rule: AssignmentRule, message_content: str, channel_type: str) -> bool:
    """Check if a rule's conditions all match."""
    conditions = rule.conditions or {}

    # Check channel_type condition
    if "channel_type" in conditions:
        if conditions["channel_type"] != channel_type:
            return False

    # Check keywords condition
    if "keywords" in conditions:
        content_lower = message_content.lower()
        if not any(kw.lower() in content_lower for kw in conditions["keywords"]):
            return False

    return True


async def assign_by_rule(
    db: AsyncSession,
    rule: AssignmentRule,
    conversation_id: UUID
) -> Optional[UUID]:
    """
    Assign conversation to an agent according to the rule's action.
    Returns the agent_id assigned, or None.
    """
    if rule.action == "specific_agent" and rule.target_agent_id:
        agent_result = await db.execute(
            select(Agent)
            .where(Agent.id == rule.target_agent_id)
            .where(Agent.is_active == True)
            .where(Agent.status == "online")
        )
        agent = agent_result.scalar_one_or_none()
        return agent.id if agent else None

    elif rule.action == "round_robin":
        return await get_round_robin_agent(db, rule.workspace_id)

    elif rule.action == "least_loaded":
        return await get_least_loaded_agent(db, rule.workspace_id)

    return None


async def get_round_robin_agent(
    db: AsyncSession,
    workspace_id: UUID
) -> Optional[UUID]:
    """
    Pick the next online agent in round-robin order.
    Uses the agent with the oldest last_heartbeat_at as a simple approximation
    (they haven't been recently active = they're next in rotation).
    In practice, last_assigned_at would be better but we use heartbeat here.
    """
    result = await db.execute(
        select(Agent)
        .where(Agent.workspace_id == workspace_id)
        .where(Agent.is_active == True)
        .where(Agent.status == "online")
        .order_by(Agent.last_heartbeat_at.asc().nulls_first())
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    return agent.id if agent else None


async def get_least_loaded_agent(
    db: AsyncSession,
    workspace_id: UUID
) -> Optional[UUID]:
    """Pick the online agent with the fewest active conversations."""
    # Subquery: count active conversations per agent
    active_counts = (
        select(
            Conversation.assigned_agent_id,
            func.count(Conversation.id).label("active_count")
        )
        .where(Conversation.workspace_id == workspace_id)
        .where(Conversation.status.in_(["escalated", "agent"]))
        .where(Conversation.assigned_agent_id != None)
        .group_by(Conversation.assigned_agent_id)
        .subquery()
    )

    result = await db.execute(
        select(Agent)
        .outerjoin(active_counts, Agent.id == active_counts.c.assigned_agent_id)
        .where(Agent.workspace_id == workspace_id)
        .where(Agent.is_active == True)
        .where(Agent.status == "online")
        .order_by(func.coalesce(active_counts.c.active_count, 0).asc())
        .limit(1)
    )
    agent = result.scalar_one_or_none()
    return agent.id if agent else None
