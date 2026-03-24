"""
AI Agent Runner
Stateless orchestrator — reconstructs all context from DB on each call.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.ai_agent import AIAgentConversation, AIAgent, AIAgentTool
from app.services.ai_agent_service import get_agent_for_channel, get_or_create_session
from app.services.tool_executor import ToolExecutor
from app.services.ai_agent_token_tracker import log_token_usage
from app.services.ai_provider import get_llm_provider_for_workspace

logger = logging.getLogger(__name__)

ESCALATE_PREFIX = "ESCALATE:"


class _SandboxSession:
    """Lightweight stand-in for AIAgentConversation in sandbox mode (no DB write)."""
    def __init__(self, agent_id: str, turn_count: int = 0):
        from uuid import uuid4
        self.id = uuid4()
        self.agent_id = agent_id
        self.turn_count = turn_count
        self.status = "active"


@dataclass
class AgentTurnResult:
    handled: bool
    reply: str = ""
    escalated: bool = False
    escalation_reason: str = ""
    debug: Dict[str, Any] = field(default_factory=dict)


class AIAgentRunner:
    """
    Stateless orchestrator — all state is loaded from DB per call.
    Returns AgentTurnResult.handled=False to fall through to RAG.
    """

    async def run(
        self,
        db: AsyncSession,
        conversation_id: str,
        new_message: str,
        workspace_id: str,
        channel_id: Optional[str] = None,
        sandbox: bool = False,
        agent: Optional[AIAgent] = None,
    ) -> AgentTurnResult:
        """
        Main entry point. If channel_id provided, look up the assigned agent.
        In sandbox mode, the caller must provide the agent directly.
        """
        # 1. Resolve agent
        if agent is None and channel_id:
            agent = await get_agent_for_channel(db, channel_id)
        if agent is None:
            return AgentTurnResult(handled=False)

        # 2. Get or create session (skip DB session in sandbox mode to avoid FK constraint)
        if sandbox:
            session = _SandboxSession(agent_id=str(agent.id), turn_count=0)
        else:
            session = await get_or_create_session(db, str(agent.id), conversation_id, workspace_id)

        # 3. Check turn limit
        if session.turn_count >= agent.max_turns:
            if not sandbox:
                await self._escalate(
                    db, session, conversation_id,
                    reason="max_turns_exceeded",
                    summary=f"Conversation handed off after {agent.max_turns} turns.",
                )
            return AgentTurnResult(
                handled=True,
                reply=agent.escalation_message,
                escalated=True,
                escalation_reason="max_turns_exceeded",
            )

        # 4. Load conversation history (skip in sandbox — no real conversation exists)
        history = [] if sandbox else await self._load_history(db, conversation_id)

        # 5. Build tool schemas for LLM
        active_tools = [t for t in agent.tools if t.is_active]
        tool_schemas = self._build_tool_schemas(active_tools)

        # 6. Build full message list
        messages = self._build_messages(agent, history, new_message)

        # 7. Trim to token budget (rough estimate: 1 token ≈ 4 chars)
        messages = self._trim_to_budget(messages, agent.token_budget)

        # 8. Get workspace meta for provider selection
        workspace_meta = await self._get_workspace_meta(db, workspace_id)
        provider = get_llm_provider_for_workspace(workspace_meta)
        model_name = workspace_meta.get("ai_model", "gemini-2.0-flash")

        # 9. Call LLM (with tools if any active tools exist)
        tool_call_info: Dict[str, Any] = {}
        if active_tools and hasattr(provider, "generate_response_with_tools"):
            text, tool_call, in_tok, out_tok = await provider.generate_response_with_tools(
                messages=messages,
                tools=tool_schemas,
                max_tokens=800,
                temperature=0.3,
            )
        else:
            text, in_tok, out_tok = await provider.generate_response(
                messages=messages,
                max_tokens=800,
                temperature=0.3,
            )
            tool_call = None

        # 10. Log LLM call tokens (skip in sandbox to avoid DB noise)
        if not sandbox:
            await log_token_usage(
                db=db,
                workspace_id=workspace_id,
                model=model_name,
                call_type="response_generation",
                input_tokens=in_tok,
                output_tokens=out_tok,
                agent_id=str(agent.id),
                agent_conversation_id=str(session.id),
            )

        # 11. Execute tool if requested
        final_reply = text
        if tool_call:
            tool_name = tool_call["name"]
            tool_params = tool_call.get("params", {})
            tool_obj = next((t for t in active_tools if t.name == tool_name), None)
            tool_call_info = {"tool_called": tool_name, "tool_params": tool_params}

            if tool_obj:
                executor = ToolExecutor()
                result = await executor.execute(tool_obj, tool_params)
                tool_call_info.update({
                    "tool_result": result.data if result.success else result.error,
                    "tool_success": result.success,
                    "tool_latency_ms": result.latency_ms,
                })

                if not sandbox:
                    await log_token_usage(
                        db=db,
                        workspace_id=workspace_id,
                        model=model_name,
                        call_type="tool_selection",
                        input_tokens=0,
                        output_tokens=0,
                        agent_id=str(agent.id),
                        agent_conversation_id=str(session.id),
                        tool_name=tool_name,
                        tool_latency_ms=result.latency_ms,
                        tool_success=result.success,
                    )

                # Feed tool result back to LLM for final answer
                tool_result_str = (
                    json.dumps(result.data) if result.success else f"Tool error: {result.error}"
                )
                followup_messages = messages + [
                    {"role": "assistant", "content": f"[Called {tool_name} with {json.dumps(tool_params)}]"},
                    {"role": "user", "content": f"Tool result: {tool_result_str}. Now provide the final answer to the customer."},
                ]
                final_reply, f_in, f_out = await provider.generate_response(
                    messages=followup_messages,
                    max_tokens=600,
                    temperature=0.3,
                )
                if not sandbox:
                    await log_token_usage(
                        db=db,
                        workspace_id=workspace_id,
                        model=model_name,
                        call_type="response_generation",
                        input_tokens=f_in,
                        output_tokens=f_out,
                        agent_id=str(agent.id),
                        agent_conversation_id=str(session.id),
                    )
            else:
                final_reply = text or agent.escalation_message

        # 12. Check for escalation signal
        escalated = False
        escalation_reason = ""
        if final_reply and final_reply.strip().startswith(ESCALATE_PREFIX):
            escalation_reason = final_reply[len(ESCALATE_PREFIX):].strip()
            final_reply = agent.escalation_message
            escalated = True
            if not sandbox:
                await self._escalate(db, session, conversation_id, reason=escalation_reason, summary=escalation_reason)

        # 13. Increment turn count (skip in sandbox)
        if not sandbox:
            await db.execute(
                update(AIAgentConversation)
                .where(AIAgentConversation.id == session.id)
                .values(turn_count=AIAgentConversation.turn_count + 1)
            )
            await db.commit()

        debug = {
            **tool_call_info,
            "model_used": model_name,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": 0.0,  # approximated in token tracker
            "turn_count": session.turn_count + 1,
            "escalated": escalated,
        }

        return AgentTurnResult(
            handled=True,
            reply=final_reply or agent.escalation_message,
            escalated=escalated,
            escalation_reason=escalation_reason,
            debug=debug,
        )

    # ─── Helpers ──────────────────────────────────────────────────────────────

    async def _load_history(self, db: AsyncSession, conversation_id: str) -> List[Message]:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(50)
        )
        return list(result.scalars().all())

    def _build_tool_schemas(self, tools: List[AIAgentTool]) -> List[Dict[str, Any]]:
        schemas = []
        for tool in tools:
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or [],
            })
        return schemas

    def _build_messages(
        self,
        agent: AIAgent,
        history: List[Message],
        new_message: str,
    ) -> List[Dict[str, Any]]:
        # System prompt
        system_parts = [agent.system_prompt]
        if agent.guardrails:
            guardrail_lines = "\n".join(
                f"- [{g.rule_type}] {g.description}" for g in agent.guardrails
            )
            system_parts.append(f"\nGuardrails:\n{guardrail_lines}")
        system_parts.append(
            f"\nIf you cannot help or detect a sensitive topic, respond with exactly: "
            f"{ESCALATE_PREFIX}<reason>"
        )
        system_content = "\n".join(system_parts)

        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_content}]

        # Conversation history
        for msg in history:
            if msg.role == "customer":
                messages.append({"role": "user", "content": msg.content or ""})
            elif msg.role in ("ai", "assistant"):
                messages.append({"role": "assistant", "content": msg.content or ""})

        # New message
        messages.append({"role": "user", "content": new_message})
        return messages

    def _trim_to_budget(self, messages: List[Dict[str, Any]], token_budget: int) -> List[Dict[str, Any]]:
        """Rough token trimming: 1 token ≈ 4 chars. Keep system + last N messages."""
        char_budget = token_budget * 4
        total = sum(len(m.get("content") or "") for m in messages)
        if total <= char_budget:
            return messages

        # Always keep system message, trim from the middle
        system = messages[:1]
        rest = messages[1:]
        while rest and sum(len(m.get("content") or "") for m in system + rest) > char_budget:
            rest.pop(0)
        return system + rest

    async def _get_workspace_meta(self, db: AsyncSession, workspace_id: str) -> Dict[str, Any]:
        from app.models.workspace import Workspace
        result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        workspace = result.scalar_one_or_none()
        return (workspace.meta or {}) if workspace else {}

    async def _escalate(
        self,
        db: AsyncSession,
        session: AIAgentConversation,
        conversation_id: str,
        reason: str,
        summary: str,
    ) -> None:
        """Mark session as escalated, update conversation status, post internal note."""
        from datetime import datetime, timezone

        await db.execute(
            update(AIAgentConversation)
            .where(AIAgentConversation.id == session.id)
            .values(status="escalated", escalation_reason=reason, ended_at=datetime.now(timezone.utc))
        )

        # Update conversation status
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(status="escalated", escalation_reason="explicit")
        )

        # Post internal note with AI summary (agent_id=None = system note)
        try:
            from app.models.internal_note import InternalNote
            note = InternalNote(
                conversation_id=conversation_id,
                content=f"[AI Agent] Escalated: {summary}",
                agent_id=None,
            )
            db.add(note)
        except Exception:
            pass

        await db.commit()


# ─── Singleton ────────────────────────────────────────────────────────────────

ai_agent_runner = AIAgentRunner()
