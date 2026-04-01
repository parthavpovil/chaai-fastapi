"""
Embedding Generation and Storage Service
Handles document chunk embedding generation and vector storage
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
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
        storage_path: str,
        **kwargs,
    ) -> Document:
        """
        Create document record in database.

        Args:
            workspace_id: Workspace ID
            filename: Original filename (stored as Document.name)
            file_size: File size in bytes (informational only)
            storage_path: R2 URL (stored as Document.file_path)

        Returns:
            Created Document instance
        """
        document = Document(
            workspace_id=workspace_id,
            name=filename,           # model column is 'name'
            file_path=storage_path,  # model column is 'file_path'
            status="processing",
        )

        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)

        return document
    
    async def create_document_chunks(
        self,
        document_id: str,
        chunks: List[Dict[str, Any]],
        workspace_id: Optional[str] = None,
    ) -> List[DocumentChunk]:
        """
        Create document chunks with embeddings

        Args:
            document_id: Document ID
            chunks: List of chunk data from document processor
            workspace_id: Workspace ID (required for NOT NULL constraint)

        Returns:
            List of created DocumentChunk instances

        Raises:
            EmbeddingError: If chunk processing fails
        """
        if not chunks:
            raise EmbeddingError("No chunks to process")

        # Batch all texts into a single API call
        texts = [c['text'] for c in chunks]
        try:
            if hasattr(embedding_provider, 'generate_batch_embeddings'):
                embeddings = await embedding_provider.generate_batch_embeddings(texts)
            else:
                # Fallback for providers without batch support
                embeddings = [await embedding_provider.generate_embedding(t) for t in texts]
        except AIProviderError as e:
            raise EmbeddingError(f"Batch embedding failed: {e}")

        embedding_model = getattr(embedding_provider, 'embedding_model', 'unknown')
        created_chunks = []

        for chunk_data, embedding in zip(chunks, embeddings):
            chunk = DocumentChunk(
                document_id=document_id,
                workspace_id=workspace_id,
                chunk_index=chunk_data['chunk_index'],
                content=chunk_data['text'],
                token_count=chunk_data.get('token_count'),
                start_char=chunk_data.get('start_char'),
                end_char=chunk_data.get('end_char'),
                embedding=embedding,
                chunk_metadata={
                    'embedding_model': embedding_model,
                    'embedding_dimensions': len(embedding)
                }
            )
            self.db.add(chunk)
            created_chunks.append(chunk)

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

        if error_message:
            document.error_message = error_message
        
        await self.db.commit()
        await self.db.refresh(document)
        
        return document
    
    async def process_document_embeddings(
        self,
        workspace_id: str,
        processing_result: Dict[str, Any]
    ) -> Document:
        """
        Complete embedding processing pipeline.

        Args:
            workspace_id: Workspace ID
            processing_result: Result from DocumentProcessor.process_document()

        Returns:
            Completed Document instance with chunks

        Raises:
            EmbeddingError: If processing fails
        """
        document = None
        r2_url = processing_result.get('storage_path')

        try:
            # 1. Create document record
            document = await self.create_document_record(
                workspace_id=workspace_id,
                filename=processing_result['original_filename'],
                file_size=processing_result['file_size'],
                storage_path=processing_result['storage_path'],
            )

            # 2. Process chunks and generate embeddings
            chunks = await self.create_document_chunks(
                document.id,
                processing_result['chunks'],
                workspace_id=workspace_id,
            )

            # 3. Update chunks_count and status
            document.chunks_count = len(chunks)
            await self.db.commit()
            document = await self.update_document_status(document.id, "completed")

            return document

        except Exception as e:
            try:
                if document:
                    await self.update_document_status(document.id, "failed", str(e))
                    await self.cleanup_failed_document_processing(document.id)

                # Delete R2 object if upload succeeded but embedding failed
                if r2_url:
                    try:
                        from app.services.r2_storage import delete_r2_object
                        delete_r2_object(r2_url)
                    except Exception:
                        pass

            except Exception as cleanup_error:
                logger.warning(f"Cleanup failed after processing error: {cleanup_error}")

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
            logger.warning(f"Failed to cleanup failed document processing: {e}")
    
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
        Delete document and all associated chunks, then delete R2 object.

        Returns:
            True if deleted, False if not found
        """
        document = await self.get_document_with_chunks(document_id, workspace_id)
        if not document:
            return False

        file_url = document.file_path if document.file_path else None

        try:
            # Delete chunks first (foreign key constraint)
            await self.db.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )

            # Delete document record
            await self.db.execute(
                delete(Document).where(Document.id == document_id)
            )

            await self.db.commit()

            # Delete R2 object best-effort (after DB commit succeeds)
            if file_url:
                try:
                    from app.services.r2_storage import delete_r2_object
                    delete_r2_object(file_url)
                except Exception as e:
                    logger.warning(f"Failed to delete R2 object {file_url}: {e}")

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
        Reprocess a failed document by downloading from R2 and regenerating embeddings.

        Returns:
            Updated Document instance

        Raises:
            EmbeddingError: If reprocessing fails
        """
        import httpx

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

            # Download file bytes from R2
            async with httpx.AsyncClient() as client:
                resp = await client.get(document.file_path)
                resp.raise_for_status()
                file_content = resp.content

            # Process document (re-extract + re-chunk, no new R2 upload)
            processor = DocumentProcessor()
            processing_result = await processor.process_document(
                workspace_id=workspace_id,
                filename=document.name,  # model field is 'name'
                file_content=file_content,
            )

            # Update document status to processing
            await self.update_document_status(document_id, "processing")

            # Create new chunks
            await self.create_document_chunks(document_id, processing_result['chunks'], workspace_id=workspace_id)

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