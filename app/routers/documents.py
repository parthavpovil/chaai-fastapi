"""
Document Management Router
Handles document upload, processing, and management with authentication and tier limits
"""
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.middleware.auth_middleware import get_current_user, get_current_workspace
from app.models.user import User
from app.models.workspace import Workspace
from app.models.document import Document
from app.services.document_processor import DocumentProcessor, DocumentProcessingError
from app.services.tier_manager import TierManager, TierLimitError
from app.services.file_storage import FileStorageService, FileStorageError


router = APIRouter(prefix="/api/documents", tags=["documents"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class DocumentResponse(BaseModel):
    """Response model for document information"""
    id: str
    name: str
    original_filename: str
    file_size: int
    content_type: str
    status: str
    error_message: Optional[str] = None
    chunk_count: Optional[int] = None
    created_at: str
    updated_at: str


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

@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(..., description="Document file (PDF or TXT, max 10MB)"),
    name: Optional[str] = Form(None, description="Custom document name"),
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Upload and process a document for the workspace
    
    Args:
        file: Uploaded file
        name: Optional custom name for the document
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Document information with processing status
    
    Raises:
        HTTPException: If upload fails or tier limits exceeded
    """
    try:
        # Check tier limits before upload
        tier_manager = TierManager(db)
        await tier_manager.check_document_limit(current_workspace.id)
        
        # Validate file
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )
        
        # Check file size (10MB limit)
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File size exceeds 10MB limit"
            )
        
        # Check file type
        allowed_types = ["application/pdf", "text/plain"]
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF and TXT files are supported"
            )
        
        # Process document
        processor = DocumentProcessor(db)
        document = await processor.upload_and_process_document(
            workspace_id=current_workspace.id,
            filename=name or file.filename,
            original_filename=file.filename,
            content=content,
            content_type=file.content_type,
            uploaded_by_user_id=current_user.id
        )
        
        return DocumentResponse(
            id=str(document.id),
            name=document.name,
            original_filename=document.original_filename,
            file_size=document.file_size,
            content_type=document.content_type,
            status=document.status,
            error_message=document.error_message,
            chunk_count=None,  # Will be populated after processing
            created_at=document.created_at.isoformat(),
            updated_at=document.updated_at.isoformat()
        )
        
    except TierLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=str(e)
        )
    except DocumentProcessingError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
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
    """
    List documents for the workspace
    
    Args:
        status_filter: Filter by status (pending, processing, completed, failed)
        limit: Maximum number of documents to return
        offset: Offset for pagination
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        List of documents with tier information
    """
    try:
        from sqlalchemy import select, func
        
        # Build query
        query = select(Document).where(Document.workspace_id == current_workspace.id)
        
        if status_filter:
            query = query.where(Document.status == status_filter)
        
        # Get total count
        count_query = select(func.count(Document.id)).where(Document.workspace_id == current_workspace.id)
        if status_filter:
            count_query = count_query.where(Document.status == status_filter)
        
        total_result = await db.execute(count_query)
        total_count = total_result.scalar()
        
        # Get documents
        query = query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        documents = result.scalars().all()
        
        # Get chunk counts for completed documents
        document_responses = []
        for doc in documents:
            chunk_count = None
            if doc.status == "completed":
                from app.models.document_chunk import DocumentChunk
                chunk_result = await db.execute(
                    select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc.id)
                )
                chunk_count = chunk_result.scalar()
            
            document_responses.append(DocumentResponse(
                id=str(doc.id),
                name=doc.name,
                original_filename=doc.original_filename,
                file_size=doc.file_size,
                content_type=doc.content_type,
                status=doc.status,
                error_message=doc.error_message,
                chunk_count=chunk_count,
                created_at=doc.created_at.isoformat(),
                updated_at=doc.updated_at.isoformat()
            ))
        
        # Get tier information
        tier_manager = TierManager(db)
        tier_info = await tier_manager.get_workspace_tier_info(current_workspace.id)
        
        return DocumentListResponse(
            documents=document_responses,
            total_count=total_count,
            tier_info={
                "current_tier": tier_info["tier"],
                "document_limit": tier_info["limits"]["documents"],
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
    """
    Get document by ID
    
    Args:
        document_id: Document ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Document information
    
    Raises:
        HTTPException: If document not found
    """
    try:
        from sqlalchemy import select, func
        
        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Get chunk count if completed
        chunk_count = None
        if document.status == "completed":
            from app.models.document_chunk import DocumentChunk
            chunk_result = await db.execute(
                select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document.id)
            )
            chunk_count = chunk_result.scalar()
        
        return DocumentResponse(
            id=str(document.id),
            name=document.name,
            original_filename=document.original_filename,
            file_size=document.file_size,
            content_type=document.content_type,
            status=document.status,
            error_message=document.error_message,
            chunk_count=chunk_count,
            created_at=document.created_at.isoformat(),
            updated_at=document.updated_at.isoformat()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}"
        )


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    current_workspace: Workspace = Depends(get_current_workspace),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a document and its chunks
    
    Args:
        document_id: Document ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If document not found
    """
    try:
        from sqlalchemy import select
        
        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Delete document and associated chunks
        processor = DocumentProcessor(db)
        await processor.delete_document(document.id)
        
        return {"message": "Document deleted successfully"}
        
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
    """
    Reprocess a failed document
    
    Args:
        document_id: Document ID
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If document not found or not in failed state
    """
    try:
        from sqlalchemy import select
        
        result = await db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == current_workspace.id)
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        if document.status not in ["failed", "completed"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document can only be reprocessed if failed or completed"
            )
        
        # Reprocess document
        processor = DocumentProcessor(db)
        await processor.reprocess_document(document.id)
        
        return {"message": "Document reprocessing started"}
        
    except HTTPException:
        raise
    except DocumentProcessingError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
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
    """
    Get document statistics for the workspace
    
    Args:
        current_user: Current authenticated user
        current_workspace: Current workspace
        db: Database session
    
    Returns:
        Document statistics
    """
    try:
        from sqlalchemy import select, func
        
        # Get document counts by status
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
            status_name = row.status
            count = row.count
            stats["total_documents"] += count
            
            if status_name in ["pending", "processing"]:
                stats["processing_documents"] += count
            elif status_name == "completed":
                stats["completed_documents"] += count
            elif status_name == "failed":
                stats["failed_documents"] += count
        
        # Get total chunk count
        from app.models.document_chunk import DocumentChunk
        chunk_result = await db.execute(
            select(func.count(DocumentChunk.id))
            .where(DocumentChunk.workspace_id == current_workspace.id)
        )
        total_chunks = chunk_result.scalar() or 0
        
        # Get tier information
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
                "document_limit": tier_info["limits"]["documents"],
                "documents_remaining": tier_info["remaining"]["documents"]
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document statistics: {str(e)}"
        )