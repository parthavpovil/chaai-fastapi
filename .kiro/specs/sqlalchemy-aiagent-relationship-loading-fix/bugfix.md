# Bugfix Requirements Document

## Introduction

The `/api/ai-agents` GET endpoint fails with a `MissingGreenlet` error when returning AIAgent objects. The error occurs during response validation in the maintenance middleware when Pydantic attempts to serialize the `tools` and `guardrails` relationships. Although these relationships are eagerly loaded using `selectinload()`, Pydantic's serialization happens after the database session closes, causing it to attempt lazy-loading in a synchronous context where async operations are not available.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the `/api/ai-agents` endpoint returns AIAgent objects with `tools` and `guardrails` relationships THEN the system raises `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` during response validation

1.2 WHEN Pydantic serializes AIAgent objects using `from_attributes=True` after the database session closes THEN the system attempts to access lazy-loaded relationships in a synchronous context

1.3 WHEN the maintenance middleware validates the response THEN the system fails because SQLAlchemy relationships are accessed outside the async context

### Expected Behavior (Correct)

2.1 WHEN the `/api/ai-agents` endpoint returns AIAgent objects with `tools` and `guardrails` relationships THEN the system SHALL successfully serialize the response without MissingGreenlet errors

2.2 WHEN Pydantic serializes AIAgent objects THEN the system SHALL access all relationship data within the active database session context

2.3 WHEN the maintenance middleware validates the response THEN the system SHALL complete successfully with all relationship data already loaded

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the `/api/ai-agents` endpoint returns AIAgent objects THEN the system SHALL CONTINUE TO include `tools` and `guardrails` data in the response

3.2 WHEN other endpoints use `selectinload()` for eager loading THEN the system SHALL CONTINUE TO work correctly if they serialize within the session context

3.3 WHEN the response schema uses `from_attributes=True` THEN the system SHALL CONTINUE TO support ORM model serialization

3.4 WHEN the maintenance middleware processes responses THEN the system SHALL CONTINUE TO validate responses correctly
