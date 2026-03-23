"""
Flow Engine Service
Handles interactive message flow execution for WhatsApp conversations.
Plugs into the webhook pipeline before the RAG call.
"""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.flow import Flow, ConversationFlowState
from app.models.channel import Channel


async def handle_message_with_flow_check(
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    workspace_id: str,
    channel: Channel
) -> bool:
    """
    Returns True if message was handled by a flow (caller should skip RAG).
    Returns False if no flow — caller proceeds to RAG.
    """
    # 1. Is conversation mid-flow?
    flow_state = await get_active_flow_state(db, str(conversation.id))
    if flow_state:
        await advance_flow(db, conversation, message, flow_state, channel)
        return True

    # 2. Does message trigger a flow by keyword?
    triggered = await find_keyword_trigger(db, workspace_id, message.content or "")
    if triggered:
        flow_state = await start_flow(db, str(conversation.id), triggered)
        await send_flow_step(db, conversation, flow_state, channel)
        return True

    return False  # proceed to RAG


async def get_active_flow_state(
    db: AsyncSession,
    conversation_id: str
) -> Optional[ConversationFlowState]:
    """Return the active (non-completed, non-abandoned) flow state for a conversation."""
    result = await db.execute(
        select(ConversationFlowState)
        .where(ConversationFlowState.conversation_id == conversation_id)
        .where(ConversationFlowState.completed_at.is_(None))
        .where(ConversationFlowState.abandoned_at.is_(None))
    )
    return result.scalar_one_or_none()


async def find_keyword_trigger(
    db: AsyncSession,
    workspace_id: str,
    content: str
) -> Optional[Flow]:
    """Find an active flow whose trigger_keywords match the message content."""
    result = await db.execute(
        select(Flow)
        .where(Flow.workspace_id == workspace_id)
        .where(Flow.is_active == True)
        .where(Flow.trigger_type == "keyword")
    )
    flows = result.scalars().all()

    content_lower = content.strip().lower()
    for flow in flows:
        keywords = flow.trigger_keywords or []
        if any(kw.lower() in content_lower for kw in keywords):
            return flow

    return None


async def start_flow(
    db: AsyncSession,
    conversation_id: str,
    flow: Flow
) -> ConversationFlowState:
    """Create a new ConversationFlowState at the first step of the flow."""
    steps = flow.steps or {}
    # Expect steps to be a dict with a "start" key or a list where first item has an "id"
    first_step_id = _get_first_step_id(steps)

    state = ConversationFlowState(
        conversation_id=conversation_id,
        flow_id=str(flow.id),
        current_step_id=first_step_id,
        collected_data={},
    )
    db.add(state)
    await db.commit()
    await db.refresh(state)
    return state


async def advance_flow(
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    flow_state: ConversationFlowState,
    channel: Channel
) -> None:
    """
    Advance the flow based on the user's reply.
    Saves collected data, determines next step, sends next message.
    """
    result = await db.execute(
        select(Flow).where(Flow.id == flow_state.flow_id)
    )
    flow = result.scalar_one_or_none()
    if not flow:
        return

    steps = flow.steps or {}
    current_step = _get_step(steps, flow_state.current_step_id)
    if not current_step:
        return

    step_type = current_step.get("type")

    # Save collected data
    if step_type == "free_text":
        collected = dict(flow_state.collected_data or {})
        collected[current_step.get("saves_as", flow_state.current_step_id)] = message.content
        flow_state.collected_data = collected

    # Determine next step
    next_step_id = _resolve_next_step(current_step, message)

    if next_step_id in ("end", None):
        flow_state.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return

    if next_step_id == "handoff":
        flow_state.abandoned_at = datetime.now(timezone.utc)
        await db.commit()
        # Escalate conversation
        conversation.status = "escalated"
        await db.commit()
        return

    flow_state.current_step_id = next_step_id
    await db.commit()
    await db.refresh(flow_state)

    await send_flow_step(db, conversation, flow_state, channel)


async def send_flow_step(
    db: AsyncSession,
    conversation: Conversation,
    flow_state: ConversationFlowState,
    channel: Channel
) -> None:
    """
    Send the current flow step as a WhatsApp message.
    Handles buttons, list, and free_text step types.
    """
    result = await db.execute(
        select(Flow).where(Flow.id == flow_state.flow_id)
    )
    flow = result.scalar_one_or_none()
    if not flow:
        return

    step = _get_step(flow.steps or {}, flow_state.current_step_id)
    if not step:
        return

    step_type = step.get("type")

    # Get channel credentials
    if not channel.config:
        return
    try:
        from app.services.encryption import decrypt_credential
        access_token = decrypt_credential(channel.config.get("access_token", ""))
        phone_number_id = decrypt_credential(channel.config.get("phone_number_id", ""))
    except Exception:
        return

    # Get recipient phone from conversation contact
    from app.models.contact import Contact
    contact_result = await db.execute(
        select(Contact).where(Contact.id == conversation.contact_id)
    )
    contact = contact_result.scalar_one_or_none()
    if not contact or not contact.phone:
        return

    import httpx
    payload = _build_whatsapp_payload(step, step_type, phone_number_id, contact.phone)
    if not payload:
        return

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://graph.facebook.com/v17.0/{phone_number_id}/messages",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10.0
            )
    except Exception:
        pass


def _build_whatsapp_payload(step: dict, step_type: str, phone_number_id: str, to: str) -> Optional[dict]:
    """Build the WhatsApp Cloud API payload for a flow step."""
    base = {"messaging_product": "whatsapp", "to": to}

    if step_type == "free_text":
        return {**base, "type": "text", "text": {"body": step.get("text", "")}}

    elif step_type == "buttons":
        buttons = [
            {"type": "reply", "reply": {"id": b.get("id", b.get("title")), "title": b["title"]}}
            for b in step.get("buttons", [])[:3]
        ]
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": step.get("text", "")},
                "action": {"buttons": buttons}
            }
        }

    elif step_type == "list":
        rows = [
            {"id": r.get("id", r.get("title")), "title": r["title"], "description": r.get("description", "")}
            for r in step.get("rows", [])
        ]
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": step.get("text", "")},
                "action": {
                    "button": step.get("button_text", "Choose"),
                    "sections": [{"title": step.get("section_title", "Options"), "rows": rows}]
                }
            }
        }

    return None


def _get_first_step_id(steps: dict) -> str:
    """Get the ID of the first step in a flow."""
    if isinstance(steps, dict):
        return steps.get("start", next(iter(steps), "start"))
    if isinstance(steps, list) and steps:
        return steps[0].get("id", "start")
    return "start"


def _get_step(steps: dict, step_id: str) -> Optional[dict]:
    """Look up a step by ID."""
    if isinstance(steps, dict):
        # steps can be {"start": {...}, "step2": {...}} or {"steps": [...]}
        if step_id in steps:
            return steps[step_id]
        # nested list
        step_list = steps.get("steps", [])
        for s in step_list:
            if s.get("id") == step_id:
                return s
    if isinstance(steps, list):
        for s in steps:
            if s.get("id") == step_id:
                return s
    return None


def _resolve_next_step(step: dict, message: Message) -> Optional[str]:
    """Determine next step ID based on user reply and step config."""
    step_type = step.get("type")

    if step_type in ("buttons", "list", "interactive"):
        interactive_id = (message.extra_data or {}).get("interactive_id", "")
        transitions = step.get("transitions", {})
        if interactive_id in transitions:
            return transitions[interactive_id]
        return step.get("default_next")

    elif step_type == "condition":
        # Simple condition: check collected data against rules
        return step.get("default_next")

    # free_text, webhook — just go to next
    return step.get("next")
