"""
Document Management Router
Handles document upload, processing, and management with authentication and tier limits
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace, require_permission
from app.models.user import User
from app.models.workspace import Workspace
from app.models.document import Document
from app.services.document_processor import DocumentProcessor, DocumentProcessingError
from app.services.tier_manager import TierManager, TierLimitError


router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
    dependencies=[Depends(require_permission("knowledge_base.documents"))],
)


# ─── Request/Response Models ──────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    """Response model for document information"""
    id: str
    name: str
    file_path: str        # R2 URL
    status: str
    chunks_count: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str


class DocumentListResponse(BaseModel):
    """Response model for document list"""
    documents: List[DocumentResponse]
    total_count: int
    tier_info: dict


class DocumentStatsResponse(BaseModel):
    """Response model for document statistics"""
    total_documents: int
    processing_documents: int
    completed_documents: int
    failed_documents: int
    total_chunks: int
    tier_info: dict


# ─── Document Management Endpoints ────────────────────────────────────────────

@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="Document file (PDF or TXT, max 10MB)"),
    name: Optional[str] = Form(None, description="Custom document name"),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Upload and process a document for the workspace knowledge base."""
    try:
        # Check tier limits before upload
        tier_manager = TierManager(db)
        await tier_manager.check_document_limit(current_workspace.id)

        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )

        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds 10MB limit"
            )

        allowed_types = ["application/pdf", "text/plain"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF and TXT files are supported"
            )

        processor = DocumentProcessor(db)
        document = await processor.upload_and_process_document(
            workspace_id=current_workspace.id,
            filename=name or file.filename,
            original_filename=file.filename,
            content=content,
            content_type=file.content_type,
            uploaded_by_user_id=current_user.id,
        )

        return DocumentResponse(
            id=str(document.id),
            name=document.name,
            file_path=document.file_path,
            status=document.status,
            chunks_count=document.chunks_count,
            error_message=document.error_message,
            created_at=document.created_at.isoformat(),
        )

    except TierLimitError as e:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(e))
    except DocumentProcessingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {str(e)}"
        )


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    status_filter: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """List documents for the workspace."""
    try:
        from sqlalchemy import select, func

        query = select(Document).where(Document.workspace_id == current_workspace.id)
        if status_filter:
            query = query.where(Document.status == status_filter)

        count_query = select(func.count(Document.id)).where(Document.workspace_id == current_workspace.id)
        if status_filter:
            count_query = count_query.where(Document.status == status_filter)

        total_result = await db.execute(count_query)
        total_count = total_result.scalar()

        query = query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        documents = result.scalars().all()

        document_responses = [
            DocumentResponse(
                id=str(doc.id),
                name=doc.name,
                file_path=doc.file_path,
                status=doc.status,
                chunks_count=doc.chunks_count,
                error_message=doc.error_message,
                created_at=doc.created_at.isoformat(),
            )
            for doc in documents
        ]

        tier_manager = TierManager(db)
        tier_info = await tier_manager.get_workspace_tier_info(current_workspace.id)

        return DocumentListResponse(
            documents=document_responses,
            total_count=total_count,
            tier_info={
                "current_tier": tier_info["tier"],
                "document_limit": tier_info["limits"].get("documents_max", 0),
                "documents_remaining": tier_info["remaining"]["documents"]
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {str(e)}"
        )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Get document by ID."""
    try:
        from sqlalchemy import select

        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        return DocumentResponse(
            id=str(document.id),
            name=document.name,
            file_path=document.file_path,
            status=document.status,
            chunks_count=document.chunks_count,
            error_message=document.error_message,
            created_at=document.created_at.isoformat(),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Delete a document and its chunks."""
    try:
        from sqlalchemy import select

        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        processor = DocumentProcessor(db)
        await processor.delete_document(document.id)

        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}"
        )


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Reprocess a failed or completed document."""
    try:
        from sqlalchemy import select

        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()

        if not document:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        if document.status not in ["failed", "completed", "processing", "pending"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document can only be reprocessed if failed, completed, pending, or stuck in processing"
            )

        processor = DocumentProcessor(db)
        await processor.reprocess_document(document.id)

        return {"message": "Document reprocessing started"}

    except HTTPException:
        raise
    except DocumentProcessingError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reprocess document: {str(e)}"
        )


@router.get("/stats/summary", response_model=DocumentStatsResponse)
async def get_document_statistics(
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """Get document statistics for the workspace."""
    try:
        from sqlalchemy import select, func

        result = await db.execute(
            select(
                Document.status,
                func.count(Document.id).label('count')
            )
            .where(Document.workspace_id == current_workspace.id)
            .group_by(Document.status)
        )

        stats = {
            "total_documents": 0,
            "processing_documents": 0,
            "completed_documents": 0,
            "failed_documents": 0
        }

        for row in result:
            count = row.count
            stats["total_documents"] += count
            if row.status in ["pending", "processing"]:
                stats["processing_documents"] += count
            elif row.status == "completed":
                stats["completed_documents"] += count
            elif row.status == "failed":
                stats["failed_documents"] += count

        from app.models.document_chunk import DocumentChunk
        chunk_result = await db.execute(
            select(func.count(DocumentChunk.id))
            .where(DocumentChunk.workspace_id == current_workspace.id)
        )
        total_chunks = chunk_result.scalar() or 0

        tier_manager = TierManager(db)
        tier_info = await tier_manager.get_workspace_tier_info(current_workspace.id)

        return DocumentStatsResponse(
            total_documents=stats["total_documents"],
            processing_documents=stats["processing_documents"],
            completed_documents=stats["completed_documents"],
            failed_documents=stats["failed_documents"],
            total_chunks=total_chunks,
            tier_info={
                "current_tier": tier_info["tier"],
                "document_limit": tier_info["limits"].get("documents_max", 0),
                "documents_remaining": tier_info["remaining"]["documents"]
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document statistics: {str(e)}"
        )
