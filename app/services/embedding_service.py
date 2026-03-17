"""
Embedding Generation and Storage Service
Handles document chunk embedding generation and vector storage
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.ai_provider import embedding_provider, AIProviderError
from app.services.document_processor import DocumentProcessor


class EmbeddingError(Exception):
    """Base exception for embedding errors"""
    pass


class EmbeddingService:
    """
    Service for generating and storing document embeddings
    Integrates with AI providers for vector generation
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.document_processor = DocumentProcessor()
    
    async def generate_chunk_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text chunk
        
        Args:
            text: Text content to embed
        
        Returns:
            Embedding vector as list of floats
        
        Raises:
            EmbeddingError: If embedding generation fails
        """
        try:
            if not embedding_provider:
                raise EmbeddingError("Embedding provider not initialized")
            
            embedding = await embedding_provider.generate_embedding(text)
            return embedding
            
        except AIProviderError as e:
            raise EmbeddingError(f"AI provider error: {str(e)}")
        except Exception as e:
            raise EmbeddingError(f"Embedding generation failed: {str(e)}")
    
    async def create_document_record(
        self,
        workspace_id: str,
        filename: str,
        file_size: int,
        file_type: str,
        storage_path: str,
        total_tokens: int,
        processing_metadata: Dict[str, Any]
    ) -> Document:
        """
        Create document record in database
        
        Args:
            workspace_id: Workspace ID
            filename: Original filename
            file_size: File size in bytes
            file_type: File extension
            storage_path: Path to stored file
            total_tokens: Total token count
            processing_metadata: Additional processing metadata
        
        Returns:
            Created Document instance
        """
        document = Document(
            workspace_id=workspace_id,
            filename=filename,
            file_size=file_size,
            file_type=file_type,
            storage_path=storage_path,
            total_tokens=total_tokens,
            status="processing",
            metadata=processing_metadata
        )
        
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)
        
        return document
    
    async def create_document_chunks(
        self,
        document_id: str,
        chunks: List[Dict[str, Any]]
    ) -> List[DocumentChunk]:
        """
        Create document chunks with embeddings
        
        Args:
            document_id: Document ID
            chunks: List of chunk data from document processor
        
        Returns:
            List of created DocumentChunk instances
        
        Raises:
            EmbeddingError: If chunk processing fails
        """
        created_chunks = []
        
        for chunk_data in chunks:
            try:
                # Generate embedding for chunk text
                embedding = await self.generate_chunk_embedding(chunk_data['text'])
                
                # Create chunk record
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_data['chunk_index'],
                    content=chunk_data['text'],
                    token_count=chunk_data['token_count'],
                    start_char=chunk_data['start_char'],
                    end_char=chunk_data['end_char'],
                    embedding=embedding,
                    metadata={
                        'embedding_model': getattr(embedding_provider, 'embedding_model', 'unknown'),
                        'embedding_dimensions': len(embedding)
                    }
                )
                
                self.db.add(chunk)
                created_chunks.append(chunk)
                
            except Exception as e:
                # Log error but continue with other chunks
                print(f"Warning: Failed to process chunk {chunk_data['chunk_index']}: {e}")
                continue
        
        if not created_chunks:
            raise EmbeddingError("Failed to process any chunks")
        
        await self.db.commit()
        
        # Refresh all chunks
        for chunk in created_chunks:
            await self.db.refresh(chunk)
        
        return created_chunks
    
    async def update_document_status(
        self,
        document_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> Document:
        """
        Update document processing status
        
        Args:
            document_id: Document ID
            status: New status ("processing", "completed", "failed")
            error_message: Optional error message for failed status
        
        Returns:
            Updated Document instance
        """
        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one()
        
        document.status = status
        document.processed_at = datetime.now(timezone.utc)
        
        if error_message:
            metadata = document.metadata or {}
            metadata['error'] = error_message
            document.metadata = metadata
        
        await self.db.commit()
        await self.db.refresh(document)
        
        return document
    
    async def process_document_embeddings(
        self,
        workspace_id: str,
        processing_result: Dict[str, Any]
    ) -> Document:
        """
        Complete embedding processing pipeline with enhanced cleanup
        
        Args:
            workspace_id: Workspace ID
            processing_result: Result from document processor
        
        Returns:
            Completed Document instance with chunks
        
        Raises:
            EmbeddingError: If processing fails
        """
        from app.services.file_storage import get_file_storage_service
        
        document = None
        stored_filename = processing_result.get('stored_filename')
        
        try:
            # 1. Create document record
            document = await self.create_document_record(
                workspace_id=workspace_id,
                filename=processing_result['original_filename'],
                file_size=processing_result['file_size'],
                file_type=processing_result['file_type'],
                storage_path=processing_result['storage_path'],
                total_tokens=processing_result['total_tokens'],
                processing_metadata={
                    'stored_filename': processing_result['stored_filename'],
                    'chunk_count': processing_result['chunk_count']
                }
            )
            
            # 2. Process chunks and generate embeddings
            chunks = await self.create_document_chunks(
                document.id,
                processing_result['chunks']
            )
            
            # 3. Update document status to completed
            document = await self.update_document_status(document.id, "completed")
            
            return document
            
        except Exception as e:
            # Enhanced cleanup for partial processing failures
            try:
                # Update document status to failed if document was created
                if document:
                    await self.update_document_status(
                        document.id, 
                        "failed", 
                        str(e)
                    )
                    
                    # Clean up database records for failed processing
                    await self.cleanup_failed_document_processing(document.id)
                
                # Clean up physical file if processing failed
                if stored_filename:
                    file_storage = get_file_storage_service()
                    file_storage.cleanup_partial_processing(workspace_id, stored_filename)
                    
            except Exception as cleanup_error:
                print(f"Warning: Cleanup failed after processing error: {cleanup_error}")
            
            raise EmbeddingError(f"Document embedding processing failed: {str(e)}")
    
    async def cleanup_failed_document_processing(self, document_id: str) -> None:
        """
        Clean up database records for failed document processing
        
        Args:
            document_id: Document ID to clean up
        """
        try:
            # Delete any chunks that were created
            await self.db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            
            # Delete the document record
            await self.db.execute(
                delete(Document).where(Document.id == document_id)
            )
            
            await self.db.commit()
            
        except Exception as e:
            await self.db.rollback()
            print(f"Warning: Failed to cleanup failed document processing: {e}")
    
    async def get_document_with_chunks(
        self,
        document_id: str,
        workspace_id: str
    ) -> Optional[Document]:
        """
        Get document with all chunks loaded
        
        Args:
            document_id: Document ID
            workspace_id: Workspace ID for isolation
        
        Returns:
            Document with chunks or None if not found
        """
        result = await self.db.execute(
            select(Document)
            .where(Document.id == document_id)
            .where(Document.workspace_id == workspace_id)
            .options(selectinload(Document.chunks))
        )
        return result.scalar_one_or_none()
    
    async def delete_document_and_chunks(
        self,
        document_id: str,
        workspace_id: str
    ) -> bool:
        """
        Delete document and all associated chunks with enhanced cleanup
        
        Args:
            document_id: Document ID
            workspace_id: Workspace ID for isolation
        
        Returns:
            True if deleted, False if not found
        
        Raises:
            EmbeddingError: If deletion fails
        """
        from app.services.file_storage import get_file_storage_service
        
        # Get document to verify ownership and get storage info
        document = await self.get_document_with_chunks(document_id, workspace_id)
        if not document:
            return False
        
        # Extract stored filename from file_path for file storage service
        stored_filename = None
        if hasattr(document, 'file_path') and document.file_path:
            stored_filename = Path(document.file_path).name
        
        try:
            # Delete chunks first (due to foreign key constraint)
            await self.db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            
            # Delete document record
            await self.db.execute(
                delete(Document).where(Document.id == document_id)
            )
            
            await self.db.commit()
            
            # Delete physical file using file storage service
            if stored_filename:
                try:
                    file_storage = get_file_storage_service()
                    file_deleted = file_storage.delete_file(workspace_id, stored_filename)
                    if not file_deleted:
                        print(f"Warning: File {stored_filename} was not found during deletion")
                except Exception as e:
                    print(f"Warning: Failed to delete physical file {stored_filename}: {e}")
                    # Don't raise exception here - database cleanup was successful
            
            return True
            
        except Exception as e:
            await self.db.rollback()
            raise EmbeddingError(f"Failed to delete document: {str(e)}")
    
    async def get_workspace_documents(
        self,
        workspace_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Document]:
        """
        Get documents for a workspace
        
        Args:
            workspace_id: Workspace ID
            status: Optional status filter
            limit: Maximum number of documents
            offset: Offset for pagination
        
        Returns:
            List of documents
        """
        query = select(Document).where(
            Document.workspace_id == workspace_id
        ).order_by(Document.created_at.desc())
        
        if status:
            query = query.where(Document.status == status)
        
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def reprocess_failed_document(self, document_id: str, workspace_id: str) -> Document:
        """
        Reprocess a failed document
        
        Args:
            document_id: Document ID
            workspace_id: Workspace ID for isolation
        
        Returns:
            Updated Document instance
        
        Raises:
            EmbeddingError: If reprocessing fails
        """
        document = await self.get_document_with_chunks(document_id, workspace_id)
        if not document:
            raise EmbeddingError("Document not found")
        
        if document.status != "failed":
            raise EmbeddingError("Document is not in failed status")
        
        try:
            # Delete existing chunks
            await self.db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            
            # Reprocess the file
            processor = DocumentProcessor()
            
            # Read file content
            with open(document.storage_path, 'rb') as f:
                file_content = f.read()
            
            # Process document
            processing_result = await processor.process_document(
                workspace_id=workspace_id,
                filename=document.filename,
                file_content=file_content
            )
            
            # Update document status to processing
            await self.update_document_status(document_id, "processing")
            
            # Create new chunks
            await self.create_document_chunks(document_id, processing_result['chunks'])
            
            # Update status to completed
            return await self.update_document_status(document_id, "completed")
            
        except Exception as e:
            await self.update_document_status(document_id, "failed", str(e))
            raise EmbeddingError(f"Document reprocessing failed: {str(e)}")


# ─── Convenience Functions ────────────────────────────────────────────────────

async def process_document_with_embeddings(
    db: AsyncSession,
    workspace_id: str,
    filename: str,
    file_content: bytes,
    content_type: Optional[str] = None
) -> Document:
    """
    Complete document processing pipeline with embeddings
    
    Args:
        db: Database session
        workspace_id: Workspace ID
        filename: Original filename
        file_content: File content as bytes
        content_type: MIME type
    
    Returns:
        Processed Document with embeddings
    
    Raises:
        EmbeddingError: If processing fails
    """
    from app.services.document_processor import process_uploaded_document
    
    # Process document (validation, text extraction, chunking)
    processing_result = await process_uploaded_document(
        workspace_id, filename, file_content, content_type
    )
    
    # Generate embeddings and store
    embedding_service = EmbeddingService(db)
    return await embedding_service.process_document_embeddings(workspace_id, processing_result)


async def get_workspace_document_list(
    db: AsyncSession,
    workspace_id: str,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Document]:
    """
    Get documents for a workspace
    """
    embedding_service = EmbeddingService(db)
    return await embedding_service.get_workspace_documents(
        workspace_id, status, limit, offset
    )