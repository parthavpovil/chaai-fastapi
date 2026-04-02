# Implementation Plan

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Telegram Queries Fail to Retrieve Relevant Chunks
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For deterministic bugs, scope the property to the concrete failing case(s) to ensure reproducibility
  - Test that Telegram queries retrieve relevant chunks when matching content exists in the knowledge base
  - Create a workspace, upload a document with known content (e.g., "business hours: 9am-5pm")
  - Generate embeddings for the document chunks
  - Send a Telegram query that should match the content (e.g., "What are your business hours?")
  - Assert that search_similar_chunks returns > 0 chunks with the correct workspace_id
  - The test assertions should match the Expected Behavior Properties from design (Property 1)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found to understand root cause (e.g., "Telegram query returns 0 chunks while webchat returns 3 chunks for same content")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Telegram Channel Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-Telegram channels (webchat, WhatsApp, Instagram)
  - Test that webchat queries retrieve chunks correctly (observe on unfixed code first)
  - Test that WhatsApp queries retrieve chunks correctly (observe on unfixed code first)
  - Test that Instagram queries retrieve chunks correctly (observe on unfixed code first)
  - Test that fallback message behavior is unchanged when no chunks match
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Fix for Telegram RAG zero chunks bug

  - [ ] 3.1 Implement the fix in search_similar_chunks
    - Add explicit UUID type casting in the SQL query WHERE clause: `WHERE d.workspace_id = :workspace_id::uuid`
    - Add diagnostic logging to capture workspace_id value, type, and query results
    - Add validation to ensure workspace_id is a valid UUID string before executing query
    - Optionally add denormalized workspace check: `AND dc.workspace_id = :workspace_id::uuid`
    - Ensure database session is properly committed and refreshed before similarity search
    - _Bug_Condition: isBugCondition(input) where input.channel_type == "telegram" AND relevantChunksExistInDatabase(input.workspace_id, input.query_text) AND retrievedChunksCount == 0_
    - _Expected_Behavior: For all Telegram queries where relevant chunks exist, search_similar_chunks SHALL retrieve chunks with similarity scores above threshold_
    - _Preservation: Non-Telegram channel RAG queries (webchat, WhatsApp, Instagram) SHALL produce identical results as before the fix_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.2 Add workspace_id logging in Telegram webhook flow
    - Add logging in telegram_webhook function to capture workspace_id from result
    - Add logging in _run_message_pipeline to capture workspace_id parameter
    - Add UUID validation before converting result["workspace_id"] to string
    - Log workspace_id at each step to trace potential corruption
    - _Requirements: 2.3_

  - [ ] 3.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Telegram Queries Retrieve Relevant Chunks
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Telegram Channel Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
