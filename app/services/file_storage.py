"""
File Storage Service
Provides secure, workspace-isolated file storage with concurrent access handling
"""
import os
import uuid
import fcntl
import mimetypes
from typing import Optional, Tuple, BinaryIO, Dict, Any
from pathlib import Path
from contextlib import contextmanager
import tempfile
import shutil

from app.config import settings


class FileStorageError(Exception):
    """Base exception for file storage errors"""
    pass


class InvalidFileTypeError(FileStorageError):
    """Raised when file type is not allowed"""
    pass


class DirectoryTraversalError(FileStorageError):
    """Raised when directory traversal attack is detected"""
    pass


class FileLockError(FileStorageError):
    """Raised when file locking fails"""
    pass


class FileStorageService:
    """
    Secure file storage service with workspace isolation
    
    Features:
    - Workspace-specific directory structure
    - Unique filename generation to prevent conflicts
    - File type and MIME type validation
    - Directory traversal protection
    - Concurrent access handling with file locking
    """
    
    # Allowed file extensions and their MIME types
    ALLOWED_EXTENSIONS = {
        '.pdf': ['application/pdf', 'application/x-pdf'],
        '.txt': ['text/plain', 'text/x-plain'],
    }
    
    # Maximum file size (10MB as per requirements)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    
    def __init__(self):
        """Initialize file storage service"""
        self.base_storage_path = Path(settings.STORAGE_PATH)
        self.documents_path = self.base_storage_path / "documents"
        
        # Ensure base directories exist
        self.documents_path.mkdir(parents=True, exist_ok=True)
    
    def _validate_filename(self, filename: str) -> str:
        """
        Validate filename and prevent directory traversal attacks
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename
            
        Raises:
            DirectoryTraversalError: If directory traversal detected
            InvalidFileTypeError: If file extension not allowed
        """
        # Check for directory traversal attempts
        if '..' in filename or '/' in filename or '\\' in filename:
            raise DirectoryTraversalError(f"Directory traversal detected in filename: {filename}")
        
        # Get file extension
        file_ext = Path(filename).suffix.lower()
        
        # Validate extension
        if file_ext not in self.ALLOWED_EXTENSIONS:
            raise InvalidFileTypeError(
                f"File extension '{file_ext}' not allowed. "
                f"Allowed extensions: {list(self.ALLOWED_EXTENSIONS.keys())}"
            )
        
        # Return sanitized filename (just the basename to be extra safe)
        return Path(filename).name
    
    def _validate_mime_type(self, filename: str, content_type: Optional[str]) -> bool:
        """
        Validate MIME type against file extension
        
        Args:
            filename: Filename with extension
            content_type: MIME type from upload
            
        Returns:
            True if valid
            
        Raises:
            InvalidFileTypeError: If MIME type doesn't match extension
        """
        if not content_type:
            return True  # Skip validation if no content type provided
        
        file_ext = Path(filename).suffix.lower()
        allowed_mimes = self.ALLOWED_EXTENSIONS.get(file_ext, [])
        
        if content_type not in allowed_mimes:
            raise InvalidFileTypeError(
                f"MIME type '{content_type}' doesn't match extension '{file_ext}'. "
                f"Expected one of: {allowed_mimes}"
            )
        
        return True
    
    def _generate_unique_filename(self, original_filename: str) -> str:
        """
        Generate unique filename while preserving extension
        
        Args:
            original_filename: Original filename
            
        Returns:
            Unique filename with UUID prefix
        """
        file_ext = Path(original_filename).suffix.lower()
        unique_id = str(uuid.uuid4())
        return f"{unique_id}{file_ext}"
    
    def _get_workspace_path(self, workspace_id: str) -> Path:
        """
        Get workspace-specific storage path
        
        Args:
            workspace_id: Workspace UUID
            
        Returns:
            Path to workspace directory
        """
        # Validate workspace_id to prevent directory traversal
        try:
            uuid.UUID(workspace_id)  # Validate it's a proper UUID
        except ValueError:
            raise DirectoryTraversalError(f"Invalid workspace_id format: {workspace_id}")
        
        workspace_path = self.documents_path / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=True)
        return workspace_path
    
    @contextmanager
    def _file_lock(self, file_path: Path, mode: str = 'r'):
        """
        Context manager for file locking to handle concurrent access
        
        Args:
            file_path: Path to file
            mode: File open mode
            
        Yields:
            File handle with exclusive lock
            
        Raises:
            FileLockError: If locking fails
        """
        try:
            with open(file_path, mode) as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    yield f
                finally:
                    # Release lock (automatically released when file closes)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except (OSError, IOError) as e:
            raise FileLockError(f"Failed to acquire file lock: {str(e)}")
    
    def store_file(
        self,
        workspace_id: str,
        original_filename: str,
        file_content: bytes,
        content_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Store file with workspace isolation and unique naming
        
        Args:
            workspace_id: Workspace UUID
            original_filename: Original filename
            file_content: File content as bytes
            content_type: MIME type for validation
            
        Returns:
            Dict with storage information
            
        Raises:
            FileStorageError: If storage fails
            InvalidFileTypeError: If file type not allowed
            DirectoryTraversalError: If security violation detected
        """
        try:
            # Validate file size
            if len(file_content) > self.MAX_FILE_SIZE:
                raise FileStorageError(
                    f"File size {len(file_content)} bytes exceeds maximum {self.MAX_FILE_SIZE} bytes"
                )
            
            # Validate and sanitize filename
            sanitized_filename = self._validate_filename(original_filename)
            
            # Validate MIME type
            self._validate_mime_type(sanitized_filename, content_type)
            
            # Generate unique filename
            unique_filename = self._generate_unique_filename(sanitized_filename)
            
            # Get workspace path
            workspace_path = self._get_workspace_path(workspace_id)
            
            # Full file path
            file_path = workspace_path / unique_filename
            
            # Use atomic write with temporary file to prevent corruption
            temp_path = None
            try:
                # Create temporary file in same directory for atomic move
                with tempfile.NamedTemporaryFile(
                    dir=workspace_path,
                    delete=False,
                    suffix='.tmp'
                ) as temp_file:
                    temp_path = Path(temp_file.name)
                    temp_file.write(file_content)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())  # Force write to disk
                
                # Atomic move to final location
                shutil.move(str(temp_path), str(file_path))
                temp_path = None  # Successfully moved
                
                # Verify file was written correctly
                if not file_path.exists() or file_path.stat().st_size != len(file_content):
                    raise FileStorageError("File verification failed after storage")
                
                return {
                    'original_filename': original_filename,
                    'stored_filename': unique_filename,
                    'file_path': str(file_path),
                    'relative_path': f"documents/{workspace_id}/{unique_filename}",
                    'file_size': len(file_content),
                    'workspace_id': workspace_id,
                    'content_type': content_type
                }
                
            finally:
                # Clean up temporary file if it still exists
                if temp_path and temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass  # Best effort cleanup
                        
        except (InvalidFileTypeError, DirectoryTraversalError):
            raise
        except Exception as e:
            raise FileStorageError(f"Failed to store file: {str(e)}")
    
    def retrieve_file(self, workspace_id: str, stored_filename: str) -> Tuple[bytes, Dict[str, Any]]:
        """
        Retrieve file with concurrent access protection
        
        Args:
            workspace_id: Workspace UUID
            stored_filename: Stored filename (unique)
            
        Returns:
            Tuple of (file_content, metadata)
            
        Raises:
            FileStorageError: If retrieval fails
            FileNotFoundError: If file doesn't exist
        """
        try:
            # Validate inputs
            self._validate_filename(stored_filename)  # Basic validation
            workspace_path = self._get_workspace_path(workspace_id)
            file_path = workspace_path / stored_filename
            
            # Check if file exists
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {stored_filename}")
            
            # Read file with lock protection
            with self._file_lock(file_path, 'rb') as f:
                file_content = f.read()
            
            # Get file metadata
            stat = file_path.stat()
            metadata = {
                'stored_filename': stored_filename,
                'file_path': str(file_path),
                'file_size': stat.st_size,
                'modified_time': stat.st_mtime,
                'workspace_id': workspace_id
            }
            
            return file_content, metadata
            
        except FileNotFoundError:
            raise
        except Exception as e:
            raise FileStorageError(f"Failed to retrieve file: {str(e)}")
    
    def delete_file(self, workspace_id: str, stored_filename: str) -> bool:
        """
        Delete file with enhanced validation and error handling
        
        Args:
            workspace_id: Workspace UUID
            stored_filename: Stored filename (unique)
            
        Returns:
            True if deleted successfully
            
        Raises:
            FileStorageError: If deletion fails
        """
        try:
            # Validate inputs
            self._validate_filename(stored_filename)
            workspace_path = self._get_workspace_path(workspace_id)
            file_path = workspace_path / stored_filename
            
            # Check if file exists
            if not file_path.exists():
                return True  # Already deleted, consider success
            
            # Verify we can delete the file before attempting
            if not os.access(file_path, os.W_OK):
                raise FileStorageError(f"No write permission to delete file: {stored_filename}")
            
            # Delete file (no need for locking since we're removing it)
            file_path.unlink()
            
            # Verify deletion was successful
            if file_path.exists():
                raise FileStorageError(f"File still exists after deletion attempt: {stored_filename}")
            
            return True
            
        except FileStorageError:
            raise
        except Exception as e:
            raise FileStorageError(f"Failed to delete file: {str(e)}")
    
    def validate_file_size_before_processing(self, file_size: int) -> None:
        """
        Validate file size before processing to prevent resource exhaustion
        
        Args:
            file_size: Size of file in bytes
            
        Raises:
            FileStorageError: If file size exceeds limits
        """
        if file_size <= 0:
            raise FileStorageError("File size must be greater than 0")
        
        if file_size > self.MAX_FILE_SIZE:
            raise FileStorageError(
                f"File size {file_size} bytes exceeds maximum {self.MAX_FILE_SIZE} bytes "
                f"({self.MAX_FILE_SIZE / (1024 * 1024):.1f}MB)"
            )
    
    def cleanup_partial_processing(self, workspace_id: str, stored_filename: str) -> bool:
        """
        Clean up partially processed files and resources
        
        Args:
            workspace_id: Workspace ID
            stored_filename: Stored filename to clean up
            
        Returns:
            True if cleanup was successful
        """
        try:
            # Delete the file if it exists
            file_deleted = self.delete_file(workspace_id, stored_filename)
            
            # Log cleanup action
            print(f"Cleaned up partial file: {stored_filename} (deleted: {file_deleted})")
            
            return True
            
        except Exception as e:
            print(f"Warning: Failed to cleanup partial file {stored_filename}: {e}")
            return False
    
    def file_exists(self, workspace_id: str, stored_filename: str) -> bool:
        """
        Check if file exists
        
        Args:
            workspace_id: Workspace UUID
            stored_filename: Stored filename (unique)
            
        Returns:
            True if file exists
        """
        try:
            workspace_path = self._get_workspace_path(workspace_id)
            file_path = workspace_path / stored_filename
            return file_path.exists()
        except Exception:
            return False
    
    def get_file_info(self, workspace_id: str, stored_filename: str) -> Dict[str, Any]:
        """
        Get file information without reading content
        
        Args:
            workspace_id: Workspace UUID
            stored_filename: Stored filename (unique)
            
        Returns:
            File metadata
            
        Raises:
            FileNotFoundError: If file doesn't exist
            FileStorageError: If operation fails
        """
        try:
            workspace_path = self._get_workspace_path(workspace_id)
            file_path = workspace_path / stored_filename
            
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {stored_filename}")
            
            stat = file_path.stat()
            return {
                'stored_filename': stored_filename,
                'file_path': str(file_path),
                'file_size': stat.st_size,
                'created_time': stat.st_ctime,
                'modified_time': stat.st_mtime,
                'workspace_id': workspace_id
            }
            
        except FileNotFoundError:
            raise
        except Exception as e:
            raise FileStorageError(f"Failed to get file info: {str(e)}")
    
    def list_workspace_files(self, workspace_id: str) -> list[Dict[str, Any]]:
        """
        List all files in workspace
        
        Args:
            workspace_id: Workspace UUID
            
        Returns:
            List of file metadata dictionaries
        """
        try:
            workspace_path = self._get_workspace_path(workspace_id)
            files = []
            
            for file_path in workspace_path.iterdir():
                if file_path.is_file() and not file_path.name.startswith('.'):
                    try:
                        stat = file_path.stat()
                        files.append({
                            'stored_filename': file_path.name,
                            'file_path': str(file_path),
                            'file_size': stat.st_size,
                            'created_time': stat.st_ctime,
                            'modified_time': stat.st_mtime,
                            'workspace_id': workspace_id
                        })
                    except OSError:
                        # Skip files we can't stat
                        continue
            
            return files
            
        except Exception as e:
            raise FileStorageError(f"Failed to list workspace files: {str(e)}")


# ─── Convenience Functions ────────────────────────────────────────────────────

# Global service instance
_file_storage_service = None


def get_file_storage_service() -> FileStorageService:
    """Get global file storage service instance"""
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service


def store_file(
    workspace_id: str,
    original_filename: str,
    file_content: bytes,
    content_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to store a file
    
    Args:
        workspace_id: Workspace UUID
        original_filename: Original filename
        file_content: File content as bytes
        content_type: MIME type for validation
        
    Returns:
        Storage information dictionary
    """
    service = get_file_storage_service()
    return service.store_file(workspace_id, original_filename, file_content, content_type)


def retrieve_file(workspace_id: str, stored_filename: str) -> Tuple[bytes, Dict[str, Any]]:
    """
    Convenience function to retrieve a file
    
    Args:
        workspace_id: Workspace UUID
        stored_filename: Stored filename (unique)
        
    Returns:
        Tuple of (file_content, metadata)
    """
    service = get_file_storage_service()
    return service.retrieve_file(workspace_id, stored_filename)


def delete_file(workspace_id: str, stored_filename: str) -> bool:
    """
    Convenience function to delete a file
    
    Args:
        workspace_id: Workspace UUID
        stored_filename: Stored filename (unique)
        
    Returns:
        True if deleted successfully
    """
    service = get_file_storage_service()
    return service.delete_file(workspace_id, stored_filename)