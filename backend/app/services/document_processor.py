"""
Document Processing Pipeline
Handles document upload, validation, text extraction, and chunking.
All files are stored in Cloudflare R2 — no local filesystem writes.
"""
import io
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import PyPDF2

logger = logging.getLogger(__name__)


class DocumentProcessingError(Exception):
    """Base exception for document processing errors"""
    pass


class UnsupportedFileTypeError(DocumentProcessingError):
    """Raised when file type is not supported"""
    pass


class FileSizeExceededError(DocumentProcessingError):
    """Raised when file size exceeds limits"""
    pass


class TextExtractionError(DocumentProcessingError):
    """Raised when text extraction fails"""
    pass


class DocumentProcessor:
    """
    Document processing pipeline for RAG system.
    Validates, extracts text in-memory, chunks, and uploads to Cloudflare R2.
    """

    CHUNK_SIZE = 200      # tokens per chunk (~800 chars, ≈1 paragraph)
    CHUNK_OVERLAP = 30    # token overlap between chunks (~15% overlap)

    ALLOWED_EXTENSIONS = {'.pdf', '.txt'}
    ALLOWED_MIME_TYPES = {'application/pdf', 'text/plain'}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self, db=None):
        self.db = db

    def validate_file(self, filename: str, file_size: int, content_type: Optional[str] = None) -> bool:
        """
        Validate file type and size.

        Raises:
            UnsupportedFileTypeError: If file type not supported
            FileSizeExceededError: If file too large
        """
        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise UnsupportedFileTypeError(
                f"Extension '{ext}' not allowed. Supported: {sorted(self.ALLOWED_EXTENSIONS)}"
            )
        if content_type and content_type not in self.ALLOWED_MIME_TYPES:
            raise UnsupportedFileTypeError(f"MIME type '{content_type}' is not supported")
        if file_size > self.MAX_FILE_SIZE:
            raise FileSizeExceededError(
                f"File size {file_size} bytes exceeds maximum {self.MAX_FILE_SIZE} bytes"
            )
        return True

    def extract_text_from_pdf(self, file_bytes: bytes) -> str:
        """Extract text from PDF bytes in memory."""
        try:
            text_content = []
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page_num, page in enumerate(pdf_reader.pages):
                try:
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        text_content.append(page_text)
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num + 1}: {e}")
                    continue
            if not text_content:
                raise TextExtractionError("No text content found in PDF")
            return '\n\n'.join(text_content)
        except TextExtractionError:
            raise
        except Exception as e:
            raise TextExtractionError(f"PDF text extraction failed: {str(e)}")

    def extract_text_from_txt(self, file_bytes: bytes) -> str:
        """Extract text from TXT bytes in memory, trying multiple encodings."""
        encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
        for encoding in encodings:
            try:
                content = file_bytes.decode(encoding)
                if content.strip():
                    return content
            except UnicodeDecodeError:
                continue
        raise TextExtractionError("Could not decode text file with any supported encoding")

    def extract_text(self, file_bytes: bytes, file_type: str) -> str:
        """Dispatch text extraction based on file type."""
        if file_type == '.pdf':
            return self.extract_text_from_pdf(file_bytes)
        elif file_type == '.txt':
            return self.extract_text_from_txt(file_bytes)
        else:
            raise TextExtractionError(f"Unsupported file type for text extraction: {file_type}")

    def estimate_token_count(self, text: str) -> int:
        """Estimate token count (rough approximation: 1 token ≈ 4 characters)."""
        return len(text) // 4

    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[Dict[str, Any]]:
        """Split text into overlapping chunks."""
        if chunk_size is None:
            chunk_size = self.CHUNK_SIZE
        if overlap is None:
            overlap = self.CHUNK_OVERLAP

        chunk_chars = chunk_size * 4
        overlap_chars = overlap * 4

        chunks = []
        text_length = len(text)

        if text_length <= chunk_chars:
            chunks.append({
                'text': text,
                'chunk_index': 0,
                'start_char': 0,
                'end_char': text_length,
                'token_count': self.estimate_token_count(text)
            })
            return chunks

        start = 0
        chunk_index = 0

        while start < text_length:
            end = min(start + chunk_chars, text_length)

            if end < text_length:
                sentence_break = text.rfind('.', end - 100, end)
                if sentence_break > start:
                    end = sentence_break + 1
                else:
                    word_break = text.rfind(' ', end - 50, end)
                    if word_break > start:
                        end = word_break

            chunk_text_content = text[start:end].strip()
            if chunk_text_content:
                chunks.append({
                    'text': chunk_text_content,
                    'chunk_index': chunk_index,
                    'start_char': start,
                    'end_char': end,
                    'token_count': self.estimate_token_count(chunk_text_content)
                })
                chunk_index += 1

            if end >= text_length:
                break
            start = max(start + 1, end - overlap_chars)

        return chunks

    async def process_document(
        self,
        workspace_id: str,
        filename: str,
        file_content: bytes,
        content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate, extract text in-memory, chunk, then upload to R2.
        Text extraction runs BEFORE upload so corrupt files fail fast
        without consuming R2 write capacity.

        Returns:
            Dict with processing results including R2 URL as 'storage_path'
        """
        from app.services.r2_storage import upload_rag_document

        file_size = len(file_content)
        if file_size == 0:
            raise DocumentProcessingError("File content is empty")

        self.validate_file(filename, file_size, content_type)

        file_ext = Path(filename).suffix.lower()
        text_content = self.extract_text(file_content, file_ext)
        chunks = self.chunk_text(text_content)

        mime = content_type or ('application/pdf' if file_ext == '.pdf' else 'text/plain')
        r2_result = await upload_rag_document(file_content, mime, str(workspace_id), filename)

        return {
            'original_filename': filename,
            'storage_path': r2_result['url'],  # R2 URL — stored in Document.file_path
            'file_size': file_size,
            'file_type': file_ext,
            'text_content': text_content,
            'total_tokens': self.estimate_token_count(text_content),
            'chunks': chunks,
            'chunk_count': len(chunks),
        }

    async def upload_and_process_document(
        self,
        workspace_id,
        filename: str,
        original_filename: str,
        content: bytes,
        content_type: str,
        uploaded_by_user_id=None,
    ):
        """
        Full pipeline: process document and persist to DB with embeddings.
        Called by the documents router on upload.
        Returns the created Document ORM instance.
        """
        from app.services.embedding_service import EmbeddingService

        processing_result = await self.process_document(
            workspace_id=str(workspace_id),
            filename=original_filename,
            file_content=content,
            content_type=content_type,
        )

        embedding_service = EmbeddingService(self.db)
        document = await embedding_service.process_document_embeddings(
            str(workspace_id), processing_result
        )

        # Apply custom name if caller provided one different from original filename
        if filename != original_filename:
            document.name = filename
            await self.db.commit()
            await self.db.refresh(document)

        return document

    async def delete_document(self, document_id):
        """
        Delete document DB records and the corresponding R2 object.
        Called by the documents router on delete.
        """
        from sqlalchemy import select
        from app.models.document import Document
        from app.services.embedding_service import EmbeddingService
        from app.services.r2_storage import delete_r2_object

        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return False

        file_url = doc.file_path

        embedding_service = EmbeddingService(self.db)
        await embedding_service.delete_document_and_chunks(
            str(document_id), str(doc.workspace_id)
        )

        # Delete R2 object best-effort (after successful DB cleanup)
        if file_url:
            try:
                delete_r2_object(file_url)
            except Exception as e:
                logger.warning(f"Failed to delete R2 object {file_url}: {e}")

        return True

    async def reprocess_document(self, document_id):
        """
        Re-download file from R2, re-extract text, regenerate embeddings.
        Does NOT re-upload to R2 — same file URL is preserved.
        Called by the documents router on reprocess.
        """
        import httpx
        from sqlalchemy import select, delete as sa_delete
        from app.models.document import Document
        from app.models.document_chunk import DocumentChunk
        from app.services.embedding_service import EmbeddingService

        result = await self.db.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise DocumentProcessingError("Document not found")

        # Download bytes from R2
        async with httpx.AsyncClient() as client:
            resp = await client.get(doc.file_path)
            resp.raise_for_status()
            file_bytes = resp.content

        # Re-extract and re-chunk in memory
        file_ext = Path(doc.name).suffix.lower()
        text_content = self.extract_text(file_bytes, file_ext)
        chunks = self.chunk_text(text_content)

        # Delete old chunks and regenerate
        await self.db.execute(
            sa_delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        doc.status = "processing"
        doc.error_message = None
        await self.db.commit()

        embedding_service = EmbeddingService(self.db)
        await embedding_service.create_document_chunks(str(document_id), chunks, workspace_id=str(doc.workspace_id))

        doc.chunks_count = len(chunks)
        await self.db.commit()

        return await embedding_service.update_document_status(str(document_id), "completed")


# ─── Convenience Functions ────────────────────────────────────────────────────

async def process_uploaded_document(
    workspace_id: str,
    filename: str,
    file_content: bytes,
    content_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function: validate, extract text, chunk, upload to R2.
    Returns processing results dict (no DB writes).
    """
    processor = DocumentProcessor()
    return await processor.process_document(workspace_id, filename, file_content, content_type)


def validate_document_upload(filename: str, file_size: int, content_type: Optional[str] = None) -> bool:
    """Convenience function to validate document before upload."""
    processor = DocumentProcessor()
    return processor.validate_file(filename, file_size, content_type)
