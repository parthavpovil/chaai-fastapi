"""
AI Agent Token Tracker
Logs per-call token usage to ai_agent_token_log AND updates the workspace usage counter.
"""
from typing import Optional
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func

from app.models.ai_agent import AIAgentTokenLog, AIAgentConversation
from app.services.usage_tracker import track_message_usage


# Cost estimates (USD per 1K tokens) — update as pricing changes
MODEL_COSTS: dict = {
    "claude-haiku-4-5": {"input": 0.00025, "output": 0.00125},
    "claude-haiku-4-5-20251001": {"input": 0.00025, "output": 0.00125},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gemini-2.0-flash": {"input": 0.000075, "output": 0.0003},
    "llama-3.3-70b-versatile": {"input": 0.00059, "output": 0.00079},
}

DEFAULT_COST = {"input": 0.0001, "output": 0.0003}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    costs = MODEL_COSTS.get(model, DEFAULT_COST)
    usd = (input_tokens / 1000) * costs["input"] + (output_tokens / 1000) * costs["output"]
    return Decimal(str(round(usd, 8)))


async def log_token_usage(
    db: AsyncSession,
    workspace_id: str,
    model: str,
    call_type: str,
    input_tokens: int,
    output_tokens: int,
    agent_id: Optional[str] = None,
    agent_conversation_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_latency_ms: Optional[int] = None,
    tool_success: Optional[bool] = None,
) -> AIAgentTokenLog:
    """
    Write one row to ai_agent_token_log and update the workspace usage counter.
    """
    cost = _estimate_cost(model, input_tokens, output_tokens)

    log_entry = AIAgentTokenLog(
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_conversation_id=agent_conversation_id,
        model=model,
        call_type=call_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost_usd=cost,
        tool_name=tool_name,
        tool_latency_ms=tool_latency_ms,
        tool_success=tool_success,
    )
    db.add(log_entry)

    # Update ai_agent_conversations token totals
    if agent_conversation_id:
        await db.execute(
            update(AIAgentConversation)
            .where(AIAgentConversation.id == agent_conversation_id)
            .values(
                total_input_tokens=AIAgentConversation.total_input_tokens + input_tokens,
                total_output_tokens=AIAgentConversation.total_output_tokens + output_tokens,
            )
        )

    await db.commit()

    # Also update the unified workspace quota counter
    await track_message_usage(
        db=db,
        workspace_id=workspace_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    return log_entry


async def get_agent_analytics(
    db: AsyncSession,
    agent_id: str,
) -> dict:
    """Aggregate token usage stats for an agent."""
    from sqlalchemy import select, func, Integer
    from sqlalchemy import case
    from app.models.ai_agent import AIAgentConversation, AIAgentTokenLog

    conv_result = await db.execute(
        select(
            func.count(AIAgentConversation.id).label("total"),
            func.sum(case((AIAgentConversation.status == "active", 1), else_=0)).label("active"),
            func.sum(case((AIAgentConversation.status == "escalated", 1), else_=0)).label("escalated"),
            func.sum(case((AIAgentConversation.status == "resolved", 1), else_=0)).label("resolved"),
            func.coalesce(func.sum(AIAgentConversation.turn_count), 0).label("total_turns"),
            func.coalesce(func.sum(AIAgentConversation.total_input_tokens), 0).label("total_input"),
            func.coalesce(func.sum(AIAgentConversation.total_output_tokens), 0).label("total_output"),
        ).where(AIAgentConversation.agent_id == agent_id)
    )
    conv_row = conv_result.first()

    token_result = await db.execute(
        select(
            func.coalesce(func.sum(AIAgentTokenLog.total_cost_usd), 0).label("total_cost"),
            func.count(AIAgentTokenLog.id).label("tool_calls_total"),
            func.sum(case((AIAgentTokenLog.tool_success == True, 1), else_=0)).label("tool_calls_success"),
        ).where(
            AIAgentTokenLog.agent_id == agent_id,
            AIAgentTokenLog.tool_name.isnot(None),
        )
    )
    token_row = token_result.first()

    model_result = await db.execute(
        select(
            AIAgentTokenLog.model,
            func.coalesce(func.sum(AIAgentTokenLog.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(AIAgentTokenLog.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(AIAgentTokenLog.total_cost_usd), 0).label("cost"),
        )
        .where(AIAgentTokenLog.agent_id == agent_id)
        .group_by(AIAgentTokenLog.model)
    )
    model_rows = model_result.all()

    return {
        "total_conversations": conv_row.total or 0,
        "active_conversations": int(conv_row.active or 0),
        "escalated_conversations": int(conv_row.escalated or 0),
        "resolved_conversations": int(conv_row.resolved or 0),
        "total_turns": int(conv_row.total_turns or 0),
        "total_input_tokens": int(conv_row.total_input or 0),
        "total_output_tokens": int(conv_row.total_output or 0),
        "total_cost_usd": float(token_row.total_cost or 0),
        "tool_calls_total": int(token_row.tool_calls_total or 0),
        "tool_calls_success": int(token_row.tool_calls_success or 0),
        "model_breakdown": [
            {
                "model": r.model,
                "input_tokens": int(r.input_tokens or 0),
                "output_tokens": int(r.output_tokens or 0),
                "cost_usd": float(r.cost or 0),
            }
            for r in model_rows
        ],
    }
