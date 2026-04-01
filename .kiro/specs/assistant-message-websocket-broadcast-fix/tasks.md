# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Assistant Messages Not Broadcast in Real-Time
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For deterministic bugs, scope the property to the concrete failing case(s) to ensure reproducibility
  - Test that assistant messages created in escalation_router.py, message_processor.py, webhooks.py, and webchat.py are NOT broadcast via websocket on unfixed code
  - The test assertions should match the Expected Behavior Properties from design (Property 1)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found to understand root cause:
    - Escalation acknowledgment messages created without websocket broadcast
    - Blocked contact error messages created without websocket broadcast
    - Business hours auto-reply messages created without websocket broadcast
    - AI agent response messages created without websocket broadcast
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Existing Broadcast Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs:
    - RAG responses in webhooks.py (lines 519-548) ARE broadcast via websocket
    - RAG responses in webchat.py (lines 533-565) ARE broadcast via websocket
    - User messages from all channels ARE broadcast via websocket
    - Redis pub/sub mechanism works across multiple workers
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Fix assistant message websocket broadcasting

  - [ ] 3.1 Add websocket broadcast to escalation acknowledgment messages
    - Open `backend/app/services/escalation_router.py`
    - Locate `send_customer_acknowledgment` method (around line 116)
    - After line 166 (`await self.db.refresh(message)`), add websocket broadcast:
      ```python
      from app.services.websocket_events import notify_new_message
      await notify_new_message(
          db=self.db,
          workspace_id=workspace_id,
          conversation_id=conversation_id,
          message_id=str(message.id),
      )
      ```
    - _Bug_Condition: isBugCondition(input) where input.code_path = "escalation_router.send_customer_acknowledgment"_
    - _Expected_Behavior: All escalation acknowledgment messages SHALL be broadcast via notify_new_message() immediately after creation_
    - _Preservation: RAG response broadcasting and user message broadcasting must remain unchanged_
    - _Requirements: 1.1, 2.1_

  - [ ] 3.2 Add websocket broadcast to blocked contact error messages
    - Open `backend/app/services/message_processor.py`
    - Locate blocked contact error message creation (around line 485)
    - After creating the error message, add websocket broadcast:
      ```python
      from app.services.websocket_events import notify_new_message
      await notify_new_message(
          db=self.db,
          workspace_id=workspace_id,
          conversation_id=str(conversation.id),
          message_id=str(error_message.id),
      )
      ```
    - _Bug_Condition: isBugCondition(input) where input.code_path = "message_processor.blocked_contact_error"_
    - _Expected_Behavior: All blocked contact error messages SHALL be broadcast via notify_new_message() immediately after creation_
    - _Preservation: RAG response broadcasting and user message broadcasting must remain unchanged_
    - _Requirements: 1.2, 2.2_

  - [ ] 3.3 Add websocket broadcast to business hours auto-reply messages
    - Open `backend/app/services/message_processor.py`
    - Locate business hours auto-reply message creation (around line 517)
    - After creating the auto-reply message, add websocket broadcast:
      ```python
      from app.services.websocket_events import notify_new_message
      await notify_new_message(
          db=self.db,
          workspace_id=workspace_id,
          conversation_id=str(conversation.id),
          message_id=str(auto_reply_message.id),
      )
      ```
    - _Bug_Condition: isBugCondition(input) where input.code_path = "message_processor.business_hours_auto_reply"_
    - _Expected_Behavior: All business hours auto-reply messages SHALL be broadcast via notify_new_message() immediately after creation_
    - _Preservation: RAG response broadcasting and user message broadcasting must remain unchanged_
    - _Requirements: 1.3, 2.3_

  - [ ] 3.4 Add websocket broadcast to AI agent responses in webhooks
    - Open `backend/app/routers/webhooks.py`
    - Locate AI agent response creation in Telegram/WhatsApp webhook handler (around line 450)
    - After the `ai_msg` is created, add websocket broadcast:
      ```python
      from app.services.websocket_events import notify_new_message
      await notify_new_message(
          db=db,
          workspace_id=workspace_id,
          conversation_id=conversation_id,
          message_id=str(ai_msg.id),
      )
      ```
    - _Bug_Condition: isBugCondition(input) where input.code_path = "webhooks.ai_agent_response"_
    - _Expected_Behavior: All AI agent responses in webhooks SHALL be broadcast via notify_new_message() immediately after creation_
    - _Preservation: RAG response broadcasting and user message broadcasting must remain unchanged_
    - _Requirements: 1.4, 2.4_

  - [ ] 3.5 Verify websocket broadcast exists for AI agent responses in webchat
    - Open `backend/app/routers/webchat.py`
    - Locate AI agent response creation (around line 496)
    - Verify that `notify_new_message()` is already called after message creation
    - If missing, add websocket broadcast following the same pattern as other fixes
    - Ensure `notify_new_message` is imported at the top of the file
    - _Bug_Condition: isBugCondition(input) where input.code_path = "webchat.ai_agent_response"_
    - _Expected_Behavior: All AI agent responses in webchat SHALL be broadcast via notify_new_message() immediately after creation_
    - _Preservation: RAG response broadcasting and user message broadcasting must remain unchanged_
    - _Requirements: 1.5, 2.5_

  - [ ] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Assistant Messages Broadcast in Real-Time
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify all assistant message types are now broadcast via websocket:
      - Escalation acknowledgment messages
      - Blocked contact error messages
      - Business hours auto-reply messages
      - AI agent response messages (webhooks)
      - AI agent response messages (webchat)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Existing Broadcast Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all existing broadcast behaviors remain unchanged:
      - RAG responses in webhooks.py continue to broadcast
      - RAG responses in webchat.py continue to broadcast
      - User messages from all channels continue to broadcast
      - Redis pub/sub mechanism continues to work across multiple workers
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
