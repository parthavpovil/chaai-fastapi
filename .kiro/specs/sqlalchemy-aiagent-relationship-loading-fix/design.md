# SQLAlchemy AIAgent Relationship Loading Fix - Bugfix Design

## Overview

The `/api/ai-agents` endpoint fails with a `MissingGreenlet` error when Pydantic attempts to serialize AIAgent objects after the database session has closed. Although the `tools` and `guardrails` relationships are eagerly loaded using `selectinload()`, Pydantic's `from_attributes=True` configuration triggers lazy-loading attempts during serialization in the maintenance middleware's response validation phase. The fix involves converting ORM objects to Pydantic models within the active database session context before the response is returned.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when Pydantic serializes AIAgent ORM objects with relationships after the database session closes
- **Property (P)**: The desired behavior - AIAgent objects should be fully serialized to Pydantic models within the active session context
- **Preservation**: Existing eager loading behavior and response schemas that must remain unchanged by the fix
- **selectinload()**: SQLAlchemy's eager loading strategy that loads relationships in a separate SELECT query
- **from_attributes**: Pydantic configuration that enables ORM model serialization by accessing object attributes
- **MissingGreenlet**: SQLAlchemy async error raised when attempting async operations in a synchronous context
- **Maintenance Middleware**: FastAPI middleware that processes responses after endpoint execution, potentially outside the database session context

## Bug Details

### Bug Condition

The bug manifests when the `/api/ai-agents` endpoint returns AIAgent ORM objects that are serialized by Pydantic after the database session closes. The `list_agents()` and `get_agent()` endpoints use `selectinload()` to eagerly load the `tools` and `guardrails` relationships, but Pydantic's serialization with `from_attributes=True` occurs during response validation in the maintenance middleware, which happens after the database session context has exited.

**Formal Specification:**
```
FUNCTION isBugCondition(request)
  INPUT: request of type HTTPRequest to /api/ai-agents endpoints
  OUTPUT: boolean
  
  RETURN request.endpoint IN ['list_agents', 'get_agent']
         AND response_contains_orm_objects(request)
         AND pydantic_serialization_occurs_after_session_close(request)
         AND relationships_accessed_during_serialization(['tools', 'guardrails'])
END FUNCTION
```

### Examples

- **List Agents**: GET `/api/ai-agents` returns multiple AIAgent objects with tools and guardrails → MissingGreenlet error during Pydantic serialization in middleware
- **Get Single Agent**: GET `/api/ai-agents/{agent_id}` returns one AIAgent object with tools and guardrails → MissingGreenlet error during Pydantic serialization in middleware
- **Create Agent**: POST `/api/ai-agents/` returns newly created AIAgent (no relationships loaded yet) → May work if tools/guardrails are empty, but same issue if relationships exist
- **Update Agent**: PUT `/api/ai-agents/{agent_id}` returns updated AIAgent with relationships → MissingGreenlet error during Pydantic serialization in middleware

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Eager loading with `selectinload()` must continue to work for all endpoints that use it
- Response schemas (`AIAgentResponse`, `AIAgentToolResponse`, `AIAgentGuardrailResponse`) must remain unchanged
- The maintenance middleware must continue to validate responses correctly
- Other endpoints that return ORM objects must continue to work if they serialize within the session context

**Scope:**
All endpoints that do NOT return AIAgent objects with relationships should be completely unaffected by this fix. This includes:
- Endpoints that return simple data types (strings, integers, booleans)
- Endpoints that manually construct Pydantic models before returning
- Endpoints that use different ORM models without relationship loading issues

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **Session Context Timing**: The database session closes before Pydantic serialization completes
   - FastAPI's dependency injection closes the session after the endpoint function returns
   - Maintenance middleware validates the response after the session is closed
   - Pydantic's `from_attributes=True` triggers attribute access during validation

2. **Lazy Loading Fallback**: Despite `selectinload()`, SQLAlchemy attempts lazy loading during serialization
   - Pydantic accesses relationship attributes (`agent.tools`, `agent.guardrails`)
   - SQLAlchemy detects the relationships are not in the current session
   - SQLAlchemy attempts to lazy-load in a synchronous context where async is not available

3. **Response Model Conversion Timing**: ORM objects are returned directly instead of being converted to Pydantic models
   - Endpoints return ORM objects (AIAgent instances)
   - FastAPI/Pydantic converts them during response validation
   - This conversion happens outside the database session context

4. **Middleware Processing Order**: The maintenance middleware processes responses after session closure
   - Middleware runs after the endpoint function completes
   - Database session is already closed by this point
   - Response validation triggers attribute access on detached ORM objects

## Correctness Properties

Property 1: Bug Condition - Successful Serialization Within Session

_For any_ request to `/api/ai-agents` endpoints that returns AIAgent objects with `tools` and `guardrails` relationships, the fixed code SHALL convert ORM objects to Pydantic models within the active database session context, preventing MissingGreenlet errors during response validation.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Unchanged Response Structure

_For any_ request to `/api/ai-agents` endpoints, the fixed code SHALL produce exactly the same response structure and data as the original code would have produced if serialization had succeeded, preserving the response schema and all relationship data.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `backend/app/routers/ai_agents.py`

**Function**: `list_agents()` and `get_agent()`

**Specific Changes**:
1. **Explicit Pydantic Conversion**: Convert ORM objects to Pydantic models within the endpoint function before returning
   - Use `AIAgentResponse.model_validate(agent)` to convert each AIAgent ORM object
   - This triggers Pydantic serialization while the database session is still active
   - Return Pydantic models instead of ORM objects

2. **List Endpoint Conversion**: Apply conversion to all agents in the list
   - Iterate through the list of AIAgent ORM objects
   - Convert each one to AIAgentResponse within the session context
   - Return list of Pydantic models

3. **Single Agent Endpoint Conversion**: Apply conversion to the single agent
   - Convert the AIAgent ORM object to AIAgentResponse
   - Return the Pydantic model

4. **Other Endpoints**: Apply the same pattern to other endpoints that return AIAgent objects
   - `create_agent()`: Convert before returning
   - `update_agent()`: Convert before returning
   - `publish_agent()`: Convert before returning

5. **Verify Session Context**: Ensure conversions happen before the database session closes
   - All conversions must occur within the `async with db` context
   - No ORM objects should be returned directly from endpoints

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write integration tests that call the `/api/ai-agents` endpoints and observe the MissingGreenlet error. Run these tests on the UNFIXED code to confirm the bug manifests as described.

**Test Cases**:
1. **List Agents with Relationships**: Call GET `/api/ai-agents` when agents have tools and guardrails (will fail on unfixed code with MissingGreenlet)
2. **Get Single Agent with Relationships**: Call GET `/api/ai-agents/{agent_id}` when agent has tools and guardrails (will fail on unfixed code with MissingGreenlet)
3. **Create Agent Then Fetch**: Create an agent with tools, then fetch it (will fail on unfixed code with MissingGreenlet)
4. **Update Agent Then Fetch**: Update an agent, then fetch it with relationships (will fail on unfixed code with MissingGreenlet)

**Expected Counterexamples**:
- MissingGreenlet error: "greenlet_spawn has not been called; can't call await_only() here"
- Error occurs during response validation in maintenance middleware
- Possible causes: session closed before serialization, lazy loading triggered, ORM objects returned directly

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL request WHERE isBugCondition(request) DO
  response := handle_request_fixed(request)
  ASSERT response.status_code == 200
  ASSERT response.body contains serialized AIAgent data
  ASSERT no MissingGreenlet error occurs
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL request WHERE NOT isBugCondition(request) DO
  ASSERT handle_request_original(request) = handle_request_fixed(request)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for endpoints that don't return AIAgent objects, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Tool Endpoints Preservation**: Verify that tool CRUD endpoints continue to work correctly (GET/POST/PUT/DELETE `/api/ai-agents/{agent_id}/tools`)
2. **Guardrail Endpoints Preservation**: Verify that guardrail CRUD endpoints continue to work correctly (GET/POST/DELETE `/api/ai-agents/{agent_id}/guardrails`)
3. **Channel Assignment Preservation**: Verify that channel assignment endpoints continue to work correctly
4. **Sandbox Endpoints Preservation**: Verify that sandbox endpoints continue to work correctly

### Unit Tests

- Test that `list_agents()` converts ORM objects to Pydantic models within session context
- Test that `get_agent()` converts ORM object to Pydantic model within session context
- Test that relationships (`tools`, `guardrails`) are fully loaded and serialized
- Test that the response schema matches `AIAgentResponse` structure

### Property-Based Tests

- Generate random AIAgent configurations with varying numbers of tools and guardrails
- Verify that all agents serialize successfully without MissingGreenlet errors
- Generate random request patterns to `/api/ai-agents` endpoints
- Verify that response structure is consistent across all test cases

### Integration Tests

- Test full request/response cycle for GET `/api/ai-agents`
- Test full request/response cycle for GET `/api/ai-agents/{agent_id}`
- Test that maintenance middleware processes responses correctly after the fix
- Test that eager loading with `selectinload()` continues to work as expected
