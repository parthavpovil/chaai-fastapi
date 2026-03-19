"""
Document Processing Pipeline
Handles document upload, validation, text extraction, and chunking
"""
import os
import uuid
import mimetypes
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import PyPDF2
from io import BytesIO

from app.config import settings
from app.services.file_storage import get_file_storage_service, FileStorageError


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
    Document processing pipeline for RAG system
    Handles validation, text extraction, and chunking using the file storage service
    """
    
    # Chunking parameters
    CHUNK_SIZE = 500  # tokens per chunk
    CHUNK_OVERLAP = 50  # token overlap between chunks
    
    def __init__(self):
        self.file_storage = get_file_storage_service()
    
    def validate_file(self, filename: str, file_size: int, content_type: Optional[str] = None) -> bool:
        """
        Validate file type and size using the file storage service
        
        Args:
            filename: Original filename
            file_size: File size in bytes
            content_type: MIME type from upload
        
        Returns:
            True if valid
        
        Raises:
            UnsupportedFileTypeError: If file type not supported
            FileSizeExceededError: If file too large
        """
        try:
            # Use file storage service validation
            self.file_storage._validate_filename(filename)
            self.file_storage._validate_mime_type(filename, content_type)
            
            # Check file size (file storage service checks this in store_file)
            if file_size > self.file_storage.MAX_FILE_SIZE:
                raise FileSizeExceededError(
                    f"File size {file_size} bytes exceeds maximum {self.file_storage.MAX_FILE_SIZE} bytes"
                )
            
            return True
        except Exception as e:
            # Convert file storage exceptions to document processor exceptions
            if "not allowed" in str(e) or "doesn't match extension" in str(e):
                raise UnsupportedFileTypeError(str(e))
            elif "exceeds maximum" in str(e):
                raise FileSizeExceededError(str(e))
            else:
                raise DocumentProcessingError(f"File validation failed: {str(e)}")
    
    def store_file(self, workspace_id: str, filename: str, file_content: bytes, content_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Store file using the file storage service
        
        Args:
            workspace_id: Workspace ID for isolation
            filename: Original filename
            file_content: File content as bytes
            content_type: MIME type for validation
            
        Returns:
            Storage information dictionary
        """
        try:
            return self.file_storage.store_file(workspace_id, filename, file_content, content_type)
        except Exception as e:
            raise DocumentProcessingError(f"Failed to store file: {str(e)}")
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        """
        Extract text from PDF file
        
        Args:
            file_path: Path to PDF file
        
        Returns:
            Extracted text content
        
        Raises:
            TextExtractionError: If extraction fails
        """
        try:
            text_content = []
            
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text.strip():
                            text_content.append(page_text)
                    except Exception as e:
                        # Log warning but continue with other pages
                        print(f"Warning: Failed to extract text from page {page_num + 1}: {e}")
                        continue
            
            if not text_content:
                raise TextExtractionError("No text content found in PDF")
            
            return '\n\n'.join(text_content)
            
        except Exception as e:
            if isinstance(e, TextExtractionError):
                raise
            raise TextExtractionError(f"PDF text extraction failed: {str(e)}")
    
    def extract_text_from_txt(self, file_path: str) -> str:
        """
        Extract text from TXT file
        
        Args:
            file_path: Path to TXT file
        
        Returns:
            Text content
        
        Raises:
            TextExtractionError: If extraction fails
        """
        try:
            # Try different encodings
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as file:
                        content = file.read()
                        if content.strip():
                            return content
                except UnicodeDecodeError:
                    continue
            
            raise TextExtractionError("Could not decode text file with any supported encoding")
            
        except Exception as e:
            if isinstance(e, TextExtractionError):
                raise
            raise TextExtractionError(f"TXT text extraction failed: {str(e)}")
    
    def extract_text(self, file_path: str, file_type: str) -> str:
        """
        Extract text from file based on type
        
        Args:
            file_path: Path to file
            file_type: File extension (.pdf, .txt)
        
        Returns:
            Extracted text content
        
        Raises:
            TextExtractionError: If extraction fails
        """
        if file_type == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_type == '.txt':
            return self.extract_text_from_txt(file_path)
        else:
            raise TextExtractionError(f"Unsupported file type for text extraction: {file_type}")
    
    def estimate_token_count(self, text: str) -> int:
        """
        Estimate token count for text (rough approximation)
        
        Args:
            text: Text content
        
        Returns:
            Estimated token count
        """
        # Rough estimation: 1 token ≈ 4 characters for English text
        return len(text) // 4
    
    def chunk_text(self, text: str, chunk_size: int = None, overlap: int = None) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks
        
        Args:
            text: Text content to chunk
            chunk_size: Target tokens per chunk (default: CHUNK_SIZE)
            overlap: Token overlap between chunks (default: CHUNK_OVERLAP)
        
        Returns:
            List of chunk dictionaries with text and metadata
        """
        if chunk_size is None:
            chunk_size = self.CHUNK_SIZE
        if overlap is None:
            overlap = self.CHUNK_OVERLAP
        
        # Convert token counts to approximate character counts
        chunk_chars = chunk_size * 4
        overlap_chars = overlap * 4
        
        chunks = []
        text_length = len(text)
        
        if text_length <= chunk_chars:
            # Text fits in single chunk
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
            
            # Try to break at sentence or word boundaries
            if end < text_length:
                # Look for sentence boundary within last 100 characters
                sentence_break = text.rfind('.', end - 100, end)
                if sentence_break > start:
                    end = sentence_break + 1
                else:
                    # Look for word boundary
                    word_break = text.rfind(' ', end - 50, end)
                    if word_break > start:
                        end = word_break
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({
                    'text': chunk_text,
                    'chunk_index': chunk_index,
                    'start_char': start,
                    'end_char': end,
                    'token_count': self.estimate_token_count(chunk_text)
                })
                chunk_index += 1
            
            # Move start position with overlap
            start = max(start + 1, end - overlap_chars)
            
            # Prevent infinite loop
            if start >= text_length:
                break
        
        return chunks
    
    async def process_document(
        self,
        workspace_id: str,
        filename: str,
        file_content: bytes,
        content_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete document processing pipeline with enhanced validation
        
        Args:
            workspace_id: Workspace ID
            filename: Original filename
            file_content: File content as bytes
            content_type: MIME type
        
        Returns:
            Dict with processing results
        
        Raises:
            DocumentProcessingError: If processing fails
        """
        from app.services.file_storage import get_file_storage_service
        
        storage_info = None
        
        try:
            # 1. Early validation to prevent resource exhaustion
            file_size = len(file_content)
            
            # Validate file size before any processing begins
            file_storage = get_file_storage_service()
            file_storage.validate_file_size_before_processing(file_size)
            
            # Validate file type and other constraints
            self.validate_file(filename, file_size, content_type)
            
            # 2. Store file using file storage service
            storage_info = self.store_file(workspace_id, filename, file_content, content_type)
            
            # 3. Extract text
            file_ext = Path(filename).suffix.lower()
            text_content = self.extract_text(storage_info['file_path'], file_ext)
            
            # 4. Create chunks
            chunks = self.chunk_text(text_content)
            
            return {
                'original_filename': storage_info['original_filename'],
                'stored_filename': storage_info['stored_filename'],
                'storage_path': storage_info['file_path'],
                'file_size': storage_info['file_size'],
                'file_type': file_ext,
                'text_content': text_content,
                'total_tokens': self.estimate_token_count(text_content),
                'chunks': chunks,
                'chunk_count': len(chunks)
            }
            
        except (UnsupportedFileTypeError, FileSizeExceededError, TextExtractionError):
            # Clean up stored file if text extraction or chunking fails
            if storage_info and storage_info.get('stored_filename'):
                try:
                    file_storage = get_file_storage_service()
                    file_storage.cleanup_partial_processing(workspace_id, storage_info['stored_filename'])
                except Exception as cleanup_error:
                    print(f"Warning: Failed to cleanup partial processing: {cleanup_error}")
            raise
        except Exception as e:
            # Clean up stored file for any other processing failures
            if storage_info and storage_info.get('stored_filename'):
                try:
                    file_storage = get_file_storage_service()
                    file_storage.cleanup_partial_processing(workspace_id, storage_info['stored_filename'])
                except Exception as cleanup_error:
                    print(f"Warning: Failed to cleanup partial processing: {cleanup_error}")
            raise DocumentProcessingError(f"Document processing failed: {str(e)}")


# ─── Convenience Functions ────────────────────────────────────────────────────

async def process_uploaded_document(
    workspace_id: str,
    filename: str,
    file_content: bytes,
    content_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to process an uploaded document
    
    Returns:
        Processing results with chunks and metadata
    
    Raises:
        DocumentProcessingError: If processing fails
    """
    processor = DocumentProcessor()
    return await processor.process_document(workspace_id, filename, file_content, content_type)


def validate_document_upload(filename: str, file_size: int, content_type: Optional[str] = None) -> bool:
    """
    Convenience function to validate document before upload
    
    Returns:
        True if valid
    
    Raises:
        DocumentProcessingError: If validation fails
    """
    processor = DocumentProcessor()
    return processor.validate_file(filename, file_size, content_type)