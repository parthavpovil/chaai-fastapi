# Assistant Message Websocket Broadcast Fix - Bugfix Design

## Overview

This bugfix addresses the inconsistent websocket broadcasting of AI assistant messages to the workspace owner's dashboard. Currently, user messages appear in real-time via websocket, but assistant messages only appear after manual refresh or API polling. The root cause is that `notify_new_message()` is called inconsistently across different code paths that create assistant messages. Some paths (RAG responses) broadcast correctly, while others (escalation acknowledgments, error messages, business hours messages, AI agent responses) do not broadcast at all.

The fix will add `notify_new_message()` calls to all code paths that create assistant messages, ensuring consistent real-time delivery across all message types.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when assistant messages are created without calling `notify_new_message()`
- **Property (P)**: The desired behavior - all assistant messages should be broadcast via websocket immediately after creation
- **Preservation**: Existing websocket broadcast behavior for RAG responses and user messages must remain unchanged
- **notify_new_message()**: The function in `backend/app/services/websocket_events.py` that broadcasts message events via Redis pub/sub to all workspace connections
- **MessageProcessor.create_message()**: The method that persists messages to the database
- **workspace_id**: The UUID identifying which workspace should receive the websocket broadcast
- **conversation_id**: The UUID identifying which conversation the message belongs to
- **message_id**: The UUID of the newly created message that needs to be broadcast

## Bug Details

### Bug Condition

The bug manifests when an assistant message is created via `MessageProcessor.create_message()` but the subsequent `notify_new_message()` call is omitted. This causes the message to be persisted to the database but not broadcast to connected websocket clients, forcing workspace owners to manually refresh to see assistant responses.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type MessageCreationContext
  OUTPUT: boolean
  
  RETURN input.role == "assistant"
         AND input.message_created == True
         AND input.notify_new_message_called == False
         AND input.code_path IN [
           "escalation_router.send_customer_acknowledgment",
           "message_processor.blocked_contact_error",
           "message_processor.business_hours_auto_reply",
           "webhooks.ai_agent_response",
           "webchat.ai_agent_response"
         ]
END FUNCTION
```

### Examples

- **Escalation Acknowledgment**: When `escalation_router.py:116` creates an acknowledgment message after escalation, the message is saved but not broadcast. Workspace owner sees the escalation event but not the acknowledgment message until refresh.

- **Blocked Contact Error**: When `message_processor.py:485` creates an error message for blocked contacts, the message is saved but not broadcast. The error response is invisible to workspace owners in real-time.

- **Business Hours Auto-Reply**: When `message_processor.py:517` creates a business hours auto-reply, the message is saved but not broadcast. Customers receive the message via their channel, but workspace owners don't see it in real-time.

- **AI Agent Response (Webhooks)**: When `webhooks.py:450` creates an AI agent response for Telegram/WhatsApp, the message is saved but not broadcast. Workspace owners must refresh to see AI agent replies.

- **AI Agent Response (Webchat)**: When `webchat.py:496` creates an AI agent response for webchat, the message is saved but not broadcast. This was recently fixed in one code path but remains broken in the fallback path.

- **Edge Case - RAG Response (Working Correctly)**: When `webhooks.py:540` or `webchat.py:560` creates a RAG response, the message IS broadcast correctly. This demonstrates the expected behavior that should be applied to all assistant messages.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- RAG response broadcasting in `webhooks.py` (lines 519-548) must continue to work exactly as before
- RAG response broadcasting in `webchat.py` (lines 533-565) must continue to work exactly as before
- User message broadcasting from all channels (Telegram, WhatsApp, webchat) must remain unchanged
- Redis pub/sub mechanism in `notify_new_message()` must continue to broadcast across multiple workers
- Websocket connection management and authentication must remain unchanged
- Message persistence logic in `MessageProcessor.create_message()` must remain unchanged

**Scope:**
All code paths that do NOT create assistant messages should be completely unaffected by this fix. This includes:
- User message creation and broadcasting
- Websocket connection lifecycle (connect, disconnect, ping/pong)
- Redis pub/sub infrastructure
- Database message persistence
- Customer websocket notifications (separate from workspace owner notifications)

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **Inconsistent Pattern Application**: The codebase has two patterns for creating assistant messages:
   - Pattern A (Correct): `create_message()` → `notify_new_message()` (used in RAG responses)
   - Pattern B (Buggy): `create_message()` only (used in escalation, errors, business hours, AI agent)
   
   The bug exists because Pattern B was used in multiple locations, likely due to:
   - Copy-paste from older code before websocket broadcasting was implemented
   - Different developers working on different features without a unified pattern
   - Missing code review checklist item for websocket broadcasting

2. **Missing Abstraction**: There is no single method that combines message creation + broadcasting. Each call site must remember to call both functions, creating opportunities for omission.

3. **Silent Failure**: The websocket broadcasting is fire-and-forget with no validation that it was called. The system doesn't detect or log when messages are created without broadcasting.

4. **Gradual Feature Addition**: Websocket broadcasting was likely added after initial message creation logic was written, and not all code paths were updated to include the new broadcasting step.

## Correctness Properties

Property 1: Bug Condition - Assistant Messages Broadcast in Real-Time

_For any_ assistant message created via `MessageProcessor.create_message()` where the message is successfully persisted to the database, the system SHALL immediately call `notify_new_message()` with the correct workspace_id, conversation_id, and message_id, causing the message to be broadcast via Redis pub/sub to all connected websocket clients in that workspace.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - Existing Broadcast Behavior Unchanged

_For any_ code path that currently calls `notify_new_message()` after creating assistant messages (RAG responses in webhooks.py and webchat.py), the system SHALL continue to broadcast those messages exactly as before, with no changes to timing, message format, or delivery guarantees.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `backend/app/services/escalation_router.py`

**Function**: `send_customer_acknowledgment`

**Specific Changes**:
1. **Add websocket broadcast after message creation**: After line 166 (`await self.db.refresh(message)`), add:
   ```python
   from app.services.websocket_events import notify_new_message
   await notify_new_message(
       db=self.db,
       workspace_id=workspace_id,
       conversation_id=conversation_id,
       message_id=str(message.id),
   )
   ```

**File**: `backend/app/services/message_processor.py`

**Function**: `process_incoming_message`

**Specific Changes**:
1. **Add websocket broadcast after blocked contact error message** (around line 485): After creating the error message, add:
   ```python
   await notify_new_message(
       db=self.db,
       workspace_id=workspace_id,
       conversation_id=str(conversation.id),
       message_id=str(error_message.id),
   )
   ```

2. **Add websocket broadcast after business hours auto-reply** (around line 517): After creating the auto-reply message, add:
   ```python
   await notify_new_message(
       db=self.db,
       workspace_id=workspace_id,
       conversation_id=str(conversation.id),
       message_id=str(auto_reply_message.id),
   )
   ```

**File**: `backend/app/routers/webhooks.py`

**Function**: Telegram/WhatsApp webhook handler (around line 450)

**Specific Changes**:
1. **Add websocket broadcast after AI agent response**: After the `ai_msg` is created, add:
   ```python
   await notify_new_message(
       db=db,
       workspace_id=workspace_id,
       conversation_id=conversation_id,
       message_id=str(ai_msg.id),
   )
   ```

**File**: `backend/app/routers/webchat.py`

**Function**: Webchat message handler (around line 496)

**Specific Changes**:
1. **Verify websocket broadcast exists after AI agent response**: The code at line 496-510 already has the correct pattern with `notify_new_message()` call. Verify this is working correctly and no changes are needed.

2. **Add import if missing**: Ensure `notify_new_message` is imported at the top of the file:
   ```python
   from app.services.websocket_events import notify_new_message
   ```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code by observing that websocket broadcasts are NOT sent, then verify the fix works correctly by confirming broadcasts ARE sent for all assistant message types.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that assistant messages are created without websocket broadcasts in the identified code paths.

**Test Plan**: Write integration tests that create assistant messages through each buggy code path and assert that websocket broadcasts are NOT sent (on unfixed code). Use mock websocket connections or Redis pub/sub listeners to detect whether broadcasts occur.

**Test Cases**:
1. **Escalation Acknowledgment Test**: Trigger escalation and verify acknowledgment message is created but NOT broadcast (will fail on unfixed code - no broadcast detected)
2. **Blocked Contact Error Test**: Send message from blocked contact and verify error message is created but NOT broadcast (will fail on unfixed code - no broadcast detected)
3. **Business Hours Auto-Reply Test**: Send message outside business hours and verify auto-reply is created but NOT broadcast (will fail on unfixed code - no broadcast detected)
4. **AI Agent Response Test (Webhooks)**: Trigger AI agent response via Telegram/WhatsApp and verify message is created but NOT broadcast (will fail on unfixed code - no broadcast detected)
5. **RAG Response Test (Control)**: Trigger RAG response and verify message IS broadcast (will pass on unfixed code - demonstrates working broadcast)

**Expected Counterexamples**:
- Websocket broadcast is not sent for escalation acknowledgments, blocked contact errors, business hours auto-replies, and AI agent responses
- Possible causes: missing `notify_new_message()` calls in these code paths

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (assistant messages created), the fixed function produces the expected behavior (websocket broadcast sent).

**Pseudocode:**
```
FOR ALL message_creation_context WHERE isBugCondition(message_creation_context) DO
  result := create_assistant_message_fixed(message_creation_context)
  ASSERT websocket_broadcast_sent(result.workspace_id, result.message_id)
  ASSERT message_persisted_to_database(result.message_id)
END FOR
```

**Test Plan**: After implementing the fix, run the same integration tests and verify that websocket broadcasts ARE now sent for all assistant message types.

**Test Cases**:
1. **Escalation Acknowledgment Broadcast**: Trigger escalation and verify acknowledgment message is broadcast via websocket
2. **Blocked Contact Error Broadcast**: Send message from blocked contact and verify error message is broadcast via websocket
3. **Business Hours Auto-Reply Broadcast**: Send message outside business hours and verify auto-reply is broadcast via websocket
4. **AI Agent Response Broadcast (Webhooks)**: Trigger AI agent response via Telegram/WhatsApp and verify message is broadcast via websocket
5. **AI Agent Response Broadcast (Webchat)**: Trigger AI agent response via webchat and verify message is broadcast via websocket

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (existing working broadcasts), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL message_creation_context WHERE NOT isBugCondition(message_creation_context) DO
  ASSERT create_assistant_message_original(message_creation_context) = create_assistant_message_fixed(message_creation_context)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for RAG responses and user messages, then write property-based tests capturing that behavior and verify it remains unchanged after the fix.

**Test Cases**:
1. **RAG Response Preservation (Webhooks)**: Verify RAG responses in webhooks.py continue to broadcast exactly as before
2. **RAG Response Preservation (Webchat)**: Verify RAG responses in webchat.py continue to broadcast exactly as before
3. **User Message Preservation**: Verify user messages from all channels continue to broadcast exactly as before
4. **Redis Pub/Sub Preservation**: Verify Redis pub/sub mechanism continues to work across multiple workers
5. **Websocket Connection Preservation**: Verify websocket connection lifecycle (connect, disconnect, ping/pong) remains unchanged
6. **Message Persistence Preservation**: Verify message database persistence logic remains unchanged

### Unit Tests

- Test that `notify_new_message()` is called with correct parameters after each assistant message creation
- Test that websocket broadcast includes correct message data (type, conversation_id, message_id, role, content)
- Test that broadcasts are sent to correct workspace_id (workspace isolation)
- Test that broadcasts work across multiple workers via Redis pub/sub
- Test error handling when websocket broadcast fails (should not prevent message persistence)

### Property-Based Tests

- Generate random assistant message creation scenarios and verify all result in websocket broadcasts
- Generate random workspace configurations and verify broadcasts maintain workspace isolation
- Generate random message content and verify broadcasts preserve message integrity
- Test that broadcast timing is immediate (no significant delay between message creation and broadcast)

### Integration Tests

- Test full flow: incoming message → AI response → message persistence → websocket broadcast → dashboard update
- Test escalation flow: user message → escalation trigger → acknowledgment message → websocket broadcast
- Test business hours flow: message outside hours → auto-reply → websocket broadcast
- Test multi-worker scenario: message created on worker A → broadcast via Redis → received on worker B
- Test websocket reconnection: client disconnects → reconnects → receives missed messages (if applicable)
