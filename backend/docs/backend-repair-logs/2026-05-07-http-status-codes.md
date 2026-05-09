# §6.2 — Correct HTTP Status Codes on DELETE and Create Endpoints

## Problem

Three DELETE endpoints returned `200 OK` with a JSON body
`{"message": "... deleted successfully"}`.  RFC 9110 §15.3.5 specifies that a
successful DELETE with no response body should return `204 No Content`.
Returning a body with `200` is not incorrect but conflicts with RESTful
conventions that front-end clients (and OpenAPI generators) rely on.

Two POST create endpoints returned `200 OK` instead of `201 Created`.
RFC 9110 §15.3.2 reserves `201 Created` for successful resource creation; it
signals to clients (and caching proxies) that a new resource was produced.

## Fix

### DELETE → 204 No Content

| File | Endpoint |
|---|---|
| `routers/documents.py` | `DELETE /api/documents/{document_id}` |
| `routers/channels.py`  | `DELETE /api/channels/{channel_id}` |
| `routers/agents.py`    | `DELETE /api/agents/{agent_id}` |

For each:
- Added `status_code=204` to the `@router.delete(...)` decorator.
- Changed `return {"message": "..."}` → `return Response(status_code=204)`.
  FastAPI serialises the return value; returning an explicit `Response` with
  no body avoids the framework accidentally including a JSON null or empty
  object in the response.

### POST → 201 Created

| File | Endpoint |
|---|---|
| `routers/documents.py` | `POST /api/documents/upload` |
| `routers/agents.py`    | `POST /api/agents/invite` |

`routers/channels.py POST /api/channels/` already had `status_code=201` from
a previous fix.

For each: added `status_code=201` to the `@router.post(...)` decorator.

## Files Changed

- `backend/app/routers/documents.py`
- `backend/app/routers/channels.py`
- `backend/app/routers/agents.py`
