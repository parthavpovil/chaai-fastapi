# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - MissingGreenlet Error on AIAgent Serialization
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases: GET /api/ai-agents and GET /api/ai-agents/{agent_id} with agents that have tools and guardrails
  - Test that GET /api/ai-agents returns 200 status without MissingGreenlet error when agents have tools and guardrails
  - Test that GET /api/ai-agents/{agent_id} returns 200 status without MissingGreenlet error when agent has tools and guardrails
  - Test that response body contains serialized AIAgent data with tools and guardrails arrays
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS with MissingGreenlet error (this is correct - it proves the bug exists)
  - Document counterexamples found: "MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here" during response validation
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-AIAgent Endpoints Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for endpoints that don't return AIAgent objects with relationships
  - Test tool CRUD endpoints: GET/POST/PUT/DELETE /api/ai-agents/{agent_id}/tools
  - Test guardrail CRUD endpoints: GET/POST/DELETE /api/ai-agents/{agent_id}/guardrails
  - Test channel assignment endpoints: POST/DELETE /api/ai-agents/{agent_id}/channels/{channel_id}
  - Test sandbox endpoints: POST /api/ai-agents/{agent_id}/sandbox/message, DELETE /api/ai-agents/{agent_id}/sandbox/reset
  - Write property-based tests capturing observed behavior patterns: all endpoints return expected status codes and response structures
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Fix for MissingGreenlet error in /api/ai-agents endpoints

  - [ ] 3.1 Implement explicit Pydantic conversion in list_agents()
    - Convert each AIAgent ORM object to AIAgentResponse within the database session context
    - Use `AIAgentResponse.model_validate(agent)` for each agent in the list
    - Return list of Pydantic models instead of ORM objects
    - Ensure conversion happens before the database session closes
    - _Bug_Condition: isBugCondition(request) where request.endpoint IN ['list_agents', 'get_agent'] AND response_contains_orm_objects(request) AND pydantic_serialization_occurs_after_session_close(request)_
    - _Expected_Behavior: Convert ORM objects to Pydantic models within active session context, preventing MissingGreenlet errors_
    - _Preservation: Eager loading with selectinload() continues to work, response schemas remain unchanged, maintenance middleware validates correctly_
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.2 Implement explicit Pydantic conversion in get_agent()
    - Convert the AIAgent ORM object to AIAgentResponse within the database session context
    - Use `AIAgentResponse.model_validate(agent)` for the single agent
    - Return Pydantic model instead of ORM object
    - Ensure conversion happens before the database session closes
    - _Bug_Condition: Same as 3.1_
    - _Expected_Behavior: Same as 3.1_
    - _Preservation: Same as 3.1_
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.3 Apply same pattern to create_agent(), update_agent(), and publish_agent()
    - Convert AIAgent ORM objects to AIAgentResponse before returning
    - Use `AIAgentResponse.model_validate(agent)` in each endpoint
    - Ensure conversions happen within the database session context
    - _Bug_Condition: Same as 3.1_
    - _Expected_Behavior: Same as 3.1_
    - _Preservation: Same as 3.1_
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.4 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Successful Serialization Within Session
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify GET /api/ai-agents returns 200 without MissingGreenlet error
    - Verify GET /api/ai-agents/{agent_id} returns 200 without MissingGreenlet error
    - Verify response contains complete AIAgent data with tools and guardrails
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-AIAgent Endpoints Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tool, guardrail, channel assignment, and sandbox endpoints still work correctly
    - Confirm response structures and status codes match baseline behavior
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
