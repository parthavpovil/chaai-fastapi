"""
Ownership helper — fetch a resource and assert it belongs to the current workspace.

Usage:
    from app.utils.owned import get_owned
    document = await get_owned(Document, document_id, current_workspace.id, db)
"""
from typing import Any, Type, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def get_owned(
    model: Type[T],
    resource_id: Any,
    workspace_id: Any,
    db: AsyncSession,
    *,
    id_column: str = "id",
    workspace_column: str = "workspace_id",
) -> T:
    """
    Fetch model where id = resource_id AND workspace_id = workspace_id.

    Raises 404 if the row does not exist or belongs to a different workspace.
    Using a single query with both predicates prevents insecure direct object
    reference (IDOR) — a valid ID from workspace A cannot be accessed by workspace B.
    """
    id_col = getattr(model, id_column)
    ws_col = getattr(model, workspace_column)

    # Normalise UUIDs so callers can pass str or UUID interchangeably.
    def _coerce(val: Any, col_attr: Any) -> Any:
        try:
            col_type = col_attr.property.columns[0].type
            if hasattr(col_type, "impl") and hasattr(col_type.impl, "python_type"):
                if col_type.impl.python_type is type(UUID(str(val))):
                    return UUID(str(val))
        except Exception:
            pass
        return val

    result = await db.execute(
        select(model).where(id_col == resource_id).where(ws_col == workspace_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return obj
