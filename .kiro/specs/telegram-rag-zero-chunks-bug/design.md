# Telegram RAG Zero Chunks Bug Design

## Overview

The RAG system fails to retrieve relevant document chunks when queries are sent via Telegram, despite the knowledge base containing the requested information. The system consistently returns 0 relevant chunks and falls back to the default message. This appears to be a workspace isolation issue where the RAG query is not properly matching the workspace_id of the stored document chunks, or the workspace_id is being passed incorrectly through the Telegram webhook pipeline.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when a Telegram query fails to retrieve chunks that exist in the knowledge base
- **Property (P)**: The desired behavior - Telegram queries should retrieve relevant chunks with the same workspace_id
- **Preservation**: Existing RAG behavior for other channels (webchat, WhatsApp, Instagram) that must remain unchanged
- **generate_rag_response**: The function in `backend/app/services/rag_engine.py` that orchestrates the RAG pipeline
- **search_similar_chunks**: The method in `RAGEngine` class that performs vector similarity search with workspace_id filtering
- **_run_message_pipeline**: The function in `backend/app/routers/webhooks.py` that processes incoming messages from all channels
- **workspace_id**: The UUID that isolates data between different workspaces - stored as PostgresUUID in the database

## Bug Details

### Bug Condition

The bug manifests when a user sends a query via Telegram that should match content in the knowledge base. The `search_similar_chunks` method in the RAG engine is either not finding chunks due to workspace_id mismatch, UUID type casting issues in the SQL query, or the workspace_id being incorrectly extracted/passed through the Telegram webhook flow.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type TelegramQuery
  OUTPUT: boolean
  
  RETURN input.channel_type == "telegram"
         AND input.query_text IS NOT NULL
         AND relevantChunksExistInDatabase(input.workspace_id, input.query_text)
         AND retrievedChunksCount(input.workspace_id, input.query_text) == 0
END FUNCTION
```

### Examples

- **Example 1**: User sends "What are your business hours?" via Telegram. Knowledge base contains a document with business hours. Expected: 3-5 relevant chunks retrieved. Actual: 0 chunks retrieved, fallback message sent.

- **Example 2**: Same query sent via webchat. Expected: 3-5 relevant chunks retrieved. Actual: Works correctly, chunks are retrieved and response is generated.

- **Example 3**: User sends "Hello" via Telegram with no matching content. Expected: 0 chunks retrieved, fallback message sent. Actual: 0 chunks retrieved, fallback message sent (correct behavior).

- **Edge Case**: User sends query via Telegram immediately after document upload completes. Expected: Chunks should be retrievable if embeddings are generated. Actual: May fail if workspace_id is not properly propagated.

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Webchat RAG queries must continue to retrieve chunks correctly
- WhatsApp RAG queries must continue to retrieve chunks correctly
- Instagram RAG queries must continue to retrieve chunks correctly
- Document upload and embedding generation must continue to work
- Fallback message behavior when no chunks match must remain unchanged
- Vector similarity search algorithm and threshold must remain unchanged

**Scope:**
All inputs that do NOT involve Telegram channel queries should be completely unaffected by this fix. This includes:
- RAG queries from other channels (webchat, WhatsApp, Instagram)
- Document processing and chunk creation
- Embedding generation
- Workspace isolation for other operations

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **UUID Type Casting Issue**: The workspace_id is passed as a string to the SQL query in `search_similar_chunks`, but PostgreSQL's UUID comparison might not be working correctly. The query uses `:workspace_id` as a bind parameter, and asyncpg might not be casting the string to UUID properly for the WHERE clause comparison.

2. **Workspace ID Extraction Error**: The workspace_id extracted from the Telegram webhook handler might be incorrect, corrupted, or in the wrong format. The flow is: `handle_telegram_webhook` → `result["workspace_id"]` → `str(result["workspace_id"])` → `generate_rag_response`.

3. **Database Session Isolation**: The conversation and message are created in one transaction, but the RAG query might be running in a different session context that doesn't see the committed data, or the workspace_id lookup is failing due to session isolation.

4. **SQL Query Join Issue**: The query joins `document_chunks dc` with `documents d` and filters on `d.workspace_id`, but if there's a mismatch between `dc.workspace_id` (denormalized) and `d.workspace_id`, chunks won't be found.

## Correctness Properties

Property 1: Bug Condition - Telegram Queries Retrieve Relevant Chunks

_For any_ Telegram query where relevant chunks exist in the knowledge base for the same workspace_id, the fixed search_similar_chunks function SHALL retrieve those chunks with similarity scores above the threshold, enabling the RAG system to generate contextual responses instead of fallback messages.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-Telegram Channel Behavior

_For any_ RAG query from channels other than Telegram (webchat, WhatsApp, Instagram), the fixed code SHALL produce exactly the same chunk retrieval results as the original code, preserving all existing RAG functionality for non-Telegram channels.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `backend/app/services/rag_engine.py`

**Function**: `search_similar_chunks`

**Specific Changes**:
1. **UUID Type Casting**: Ensure the workspace_id parameter is explicitly cast to UUID in the SQL query or before passing to the query. Change the bind parameter to use explicit UUID casting: `WHERE d.workspace_id = :workspace_id::uuid` or convert the string to UUID object before passing.

2. **Add Diagnostic Logging**: Add logging to capture the workspace_id value, type, and query results to help diagnose the issue in production:
   - Log workspace_id value and type before query execution
   - Log the number of chunks found
   - Log the SQL query parameters

3. **Verify Workspace ID Format**: Add validation to ensure workspace_id is a valid UUID string before executing the query.

4. **Add Denormalized Workspace Check**: Optionally add a check on `dc.workspace_id` in addition to `d.workspace_id` to ensure consistency: `AND dc.workspace_id = :workspace_id`

5. **Database Session Verification**: Ensure the database session used for RAG queries is properly committed and refreshed before executing the similarity search.

**File**: `backend/app/routers/webhooks.py`

**Function**: `telegram_webhook` and `_run_message_pipeline`

**Specific Changes**:
1. **Workspace ID Logging**: Add logging to capture workspace_id at each step of the Telegram webhook flow to trace where it might be getting corrupted.

2. **UUID Validation**: Validate that `result["workspace_id"]` is a valid UUID before converting to string.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that create a workspace, upload a document, generate embeddings, then send a Telegram query and verify chunks are retrieved. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Telegram Query with Matching Content**: Create workspace, upload document with "business hours", send Telegram query "business hours", assert chunks > 0 (will fail on unfixed code)
2. **Webchat Query with Same Content**: Same setup, but send query via webchat, assert chunks > 0 (should pass on unfixed code)
3. **Workspace ID Mismatch Test**: Create two workspaces, upload document to workspace A, send Telegram query from workspace B, assert chunks == 0 (should pass - correct isolation)
4. **UUID Format Test**: Log and verify the workspace_id format at each step of the Telegram pipeline (will reveal format issues on unfixed code)

**Expected Counterexamples**:
- Telegram queries return 0 chunks while webchat queries return >0 chunks for the same content
- Possible causes: UUID type mismatch, workspace_id extraction error, SQL query filtering issue

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := search_similar_chunks_fixed(input.workspace_id, input.query_embedding)
  ASSERT len(result) > 0
  ASSERT all(chunk.workspace_id == input.workspace_id for chunk, _ in result)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT search_similar_chunks_original(input) = search_similar_chunks_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-Telegram inputs

**Test Plan**: Observe behavior on UNFIXED code first for webchat, WhatsApp, and Instagram queries, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Webchat Preservation**: Observe that webchat queries retrieve chunks correctly on unfixed code, then write test to verify this continues after fix
2. **WhatsApp Preservation**: Observe that WhatsApp queries retrieve chunks correctly on unfixed code, then write test to verify this continues after fix
3. **Instagram Preservation**: Observe that Instagram queries retrieve chunks correctly on unfixed code, then write test to verify this continues after fix
4. **Fallback Behavior Preservation**: Verify that queries with no matching content still return 0 chunks and trigger fallback message

### Unit Tests

- Test workspace_id UUID casting in SQL query
- Test workspace_id extraction from Telegram webhook result
- Test search_similar_chunks with valid and invalid workspace_id formats
- Test that document chunks are created with correct workspace_id

### Property-Based Tests

- Generate random workspace IDs and verify Telegram queries retrieve only chunks from that workspace
- Generate random queries and verify Telegram retrieves same chunks as webchat for the same workspace
- Test that all channels (Telegram, webchat, WhatsApp, Instagram) retrieve identical chunks for identical queries in the same workspace

### Integration Tests

- Test full Telegram webhook flow: receive message → extract workspace_id → query RAG → retrieve chunks
- Test that document upload → embedding generation → Telegram query works end-to-end
- Test workspace isolation: verify Telegram queries from workspace A don't retrieve chunks from workspace B
