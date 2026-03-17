"""
Unit tests for File Storage Service
Tests workspace isolation, unique filename generation, and concurrent access handling
"""
import os
import uuid
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Mock settings before importing the service
@pytest.fixture(autouse=True)
def mock_settings():
    """Mock settings for all tests"""
    with patch('app.services.file_storage.settings') as mock_settings:
        mock_settings.STORAGE_PATH = "/tmp/test_storage"
        yield mock_settings

from app.services.file_storage import (
    FileStorageService,
    FileStorageError,
    InvalidFileTypeError,
    DirectoryTraversalError,
    FileLockError,
    store_file,
    retrieve_file,
    delete_file
)


class TestFileStorageService:
    """Test cases for FileStorageService"""
    
    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directory for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def file_storage_service(self, temp_storage_path):
        """Create FileStorageService with temporary storage"""
        with patch('app.services.file_storage.settings') as mock_settings:
            mock_settings.STORAGE_PATH = temp_storage_path
            service = FileStorageService()
            yield service
    
    @pytest.fixture
    def sample_workspace_id(self):
        """Generate sample workspace ID"""
        return str(uuid.uuid4())
    
    @pytest.fixture
    def sample_pdf_content(self):
        """Sample PDF content for testing"""
        return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
    
    @pytest.fixture
    def sample_txt_content(self):
        """Sample text content for testing"""
        return b"This is a sample text file for testing."
    
    def test_store_file_success_pdf(self, file_storage_service, sample_workspace_id, sample_pdf_content):
        """Test successful PDF file storage"""
        result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.pdf",
            file_content=sample_pdf_content,
            content_type="application/pdf"
        )
        
        assert result['original_filename'] == "test.pdf"
        assert result['stored_filename'].endswith('.pdf')
        assert result['file_size'] == len(sample_pdf_content)
        assert result['workspace_id'] == sample_workspace_id
        assert 'file_path' in result
        assert 'relative_path' in result
        
        # Verify file exists
        file_path = Path(result['file_path'])
        assert file_path.exists()
        assert file_path.read_bytes() == sample_pdf_content
    
    def test_store_file_success_txt(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test successful TXT file storage"""
        result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content,
            content_type="text/plain"
        )
        
        assert result['original_filename'] == "test.txt"
        assert result['stored_filename'].endswith('.txt')
        assert result['file_size'] == len(sample_txt_content)
        
        # Verify file exists
        file_path = Path(result['file_path'])
        assert file_path.exists()
        assert file_path.read_bytes() == sample_txt_content
    
    def test_store_file_workspace_isolation(self, file_storage_service, sample_txt_content):
        """Test that files are isolated by workspace"""
        workspace1 = str(uuid.uuid4())
        workspace2 = str(uuid.uuid4())
        
        # Store same filename in different workspaces
        result1 = file_storage_service.store_file(
            workspace_id=workspace1,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        result2 = file_storage_service.store_file(
            workspace_id=workspace2,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Should have different paths
        assert result1['file_path'] != result2['file_path']
        assert workspace1 in result1['file_path']
        assert workspace2 in result2['file_path']
        
        # Both files should exist
        assert Path(result1['file_path']).exists()
        assert Path(result2['file_path']).exists()
    
    def test_store_file_unique_filenames(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test that unique filenames are generated to prevent conflicts"""
        # Store same filename twice
        result1 = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        result2 = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Should have different stored filenames
        assert result1['stored_filename'] != result2['stored_filename']
        assert result1['file_path'] != result2['file_path']
        
        # Both should end with .txt
        assert result1['stored_filename'].endswith('.txt')
        assert result2['stored_filename'].endswith('.txt')
        
        # Both files should exist
        assert Path(result1['file_path']).exists()
        assert Path(result2['file_path']).exists()
    
    def test_store_file_invalid_extension(self, file_storage_service, sample_workspace_id):
        """Test rejection of invalid file extensions"""
        with pytest.raises(InvalidFileTypeError) as exc_info:
            file_storage_service.store_file(
                workspace_id=sample_workspace_id,
                original_filename="test.exe",
                file_content=b"malicious content"
            )
        
        assert "not allowed" in str(exc_info.value)
        assert ".exe" in str(exc_info.value)
    
    def test_store_file_directory_traversal_protection(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test protection against directory traversal attacks"""
        malicious_filenames = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32\\config\\sam",
            "test/../../../secret.txt",
            "test\\..\\..\\secret.txt"
        ]
        
        for filename in malicious_filenames:
            with pytest.raises(DirectoryTraversalError) as exc_info:
                file_storage_service.store_file(
                    workspace_id=sample_workspace_id,
                    original_filename=filename,
                    file_content=sample_txt_content
                )
            
            assert "Directory traversal detected" in str(exc_info.value)
    
    def test_store_file_invalid_workspace_id(self, file_storage_service, sample_txt_content):
        """Test rejection of invalid workspace IDs"""
        invalid_workspace_ids = [
            "../malicious",
            "../../etc",
            "not-a-uuid",
            ""
        ]
        
        for workspace_id in invalid_workspace_ids:
            with pytest.raises(DirectoryTraversalError):
                file_storage_service.store_file(
                    workspace_id=workspace_id,
                    original_filename="test.txt",
                    file_content=sample_txt_content
                )
    
    def test_store_file_size_limit(self, file_storage_service, sample_workspace_id):
        """Test file size limit enforcement"""
        # Create content larger than 10MB
        large_content = b"x" * (11 * 1024 * 1024)
        
        with pytest.raises(FileStorageError) as exc_info:
            file_storage_service.store_file(
                workspace_id=sample_workspace_id,
                original_filename="large.txt",
                file_content=large_content
            )
        
        assert "exceeds maximum" in str(exc_info.value)
    
    def test_store_file_mime_type_validation(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test MIME type validation"""
        # Wrong MIME type for .txt file
        with pytest.raises(InvalidFileTypeError) as exc_info:
            file_storage_service.store_file(
                workspace_id=sample_workspace_id,
                original_filename="test.txt",
                file_content=sample_txt_content,
                content_type="application/pdf"
            )
        
        assert "doesn't match extension" in str(exc_info.value)
    
    def test_retrieve_file_success(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test successful file retrieval"""
        # Store file first
        store_result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Retrieve file
        content, metadata = file_storage_service.retrieve_file(
            workspace_id=sample_workspace_id,
            stored_filename=store_result['stored_filename']
        )
        
        assert content == sample_txt_content
        assert metadata['stored_filename'] == store_result['stored_filename']
        assert metadata['file_size'] == len(sample_txt_content)
        assert metadata['workspace_id'] == sample_workspace_id
    
    def test_retrieve_file_not_found(self, file_storage_service, sample_workspace_id):
        """Test retrieval of non-existent file"""
        with pytest.raises(FileNotFoundError):
            file_storage_service.retrieve_file(
                workspace_id=sample_workspace_id,
                stored_filename="nonexistent.txt"
            )
    
    def test_retrieve_file_workspace_isolation(self, file_storage_service, sample_txt_content):
        """Test that files can't be retrieved from wrong workspace"""
        workspace1 = str(uuid.uuid4())
        workspace2 = str(uuid.uuid4())
        
        # Store file in workspace1
        store_result = file_storage_service.store_file(
            workspace_id=workspace1,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Try to retrieve from workspace2
        with pytest.raises(FileNotFoundError):
            file_storage_service.retrieve_file(
                workspace_id=workspace2,
                stored_filename=store_result['stored_filename']
            )
    
    def test_delete_file_success(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test successful file deletion"""
        # Store file first
        store_result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Verify file exists
        assert Path(store_result['file_path']).exists()
        
        # Delete file
        result = file_storage_service.delete_file(
            workspace_id=sample_workspace_id,
            stored_filename=store_result['stored_filename']
        )
        
        assert result is True
        assert not Path(store_result['file_path']).exists()
    
    def test_delete_file_not_found(self, file_storage_service, sample_workspace_id):
        """Test deletion of non-existent file (should succeed)"""
        result = file_storage_service.delete_file(
            workspace_id=sample_workspace_id,
            stored_filename="nonexistent.txt"
        )
        
        assert result is True  # Should succeed even if file doesn't exist
    
    def test_file_exists(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test file existence checking"""
        # File doesn't exist initially
        assert not file_storage_service.file_exists(sample_workspace_id, "test.txt")
        
        # Store file
        store_result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # File should exist now
        assert file_storage_service.file_exists(
            sample_workspace_id,
            store_result['stored_filename']
        )
        
        # Delete file
        file_storage_service.delete_file(
            sample_workspace_id,
            store_result['stored_filename']
        )
        
        # File shouldn't exist anymore
        assert not file_storage_service.file_exists(
            sample_workspace_id,
            store_result['stored_filename']
        )
    
    def test_get_file_info(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test getting file information without reading content"""
        # Store file
        store_result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Get file info
        info = file_storage_service.get_file_info(
            workspace_id=sample_workspace_id,
            stored_filename=store_result['stored_filename']
        )
        
        assert info['stored_filename'] == store_result['stored_filename']
        assert info['file_size'] == len(sample_txt_content)
        assert info['workspace_id'] == sample_workspace_id
        assert 'created_time' in info
        assert 'modified_time' in info
    
    def test_list_workspace_files(self, file_storage_service, sample_workspace_id, sample_txt_content, sample_pdf_content):
        """Test listing all files in workspace"""
        # Initially empty
        files = file_storage_service.list_workspace_files(sample_workspace_id)
        assert len(files) == 0
        
        # Store multiple files
        store_result1 = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test1.txt",
            file_content=sample_txt_content
        )
        
        store_result2 = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test2.pdf",
            file_content=sample_pdf_content
        )
        
        # List files
        files = file_storage_service.list_workspace_files(sample_workspace_id)
        assert len(files) == 2
        
        stored_filenames = {f['stored_filename'] for f in files}
        assert store_result1['stored_filename'] in stored_filenames
        assert store_result2['stored_filename'] in stored_filenames
    
    def test_concurrent_access_protection(self, file_storage_service, sample_workspace_id, sample_txt_content):
        """Test concurrent access handling with file locking"""
        # Store file first
        store_result = file_storage_service.store_file(
            workspace_id=sample_workspace_id,
            original_filename="test.txt",
            file_content=sample_txt_content
        )
        
        results = []
        errors = []
        
        def read_file():
            try:
                content, metadata = file_storage_service.retrieve_file(
                    workspace_id=sample_workspace_id,
                    stored_filename=store_result['stored_filename']
                )
                results.append(content)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads to read simultaneously
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=read_file)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # All reads should succeed
        assert len(errors) == 0
        assert len(results) == 5
        assert all(content == sample_txt_content for content in results)


class TestConvenienceFunctions:
    """Test convenience functions"""
    
    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directory for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def sample_workspace_id(self):
        """Generate sample workspace ID"""
        return str(uuid.uuid4())
    
    @pytest.fixture
    def sample_txt_content(self):
        """Sample text content for testing"""
        return b"This is a sample text file for testing."
    
    def test_convenience_functions(self, temp_storage_path, sample_workspace_id, sample_txt_content):
        """Test convenience functions work correctly"""
        with patch('app.services.file_storage.settings') as mock_settings:
            mock_settings.STORAGE_PATH = temp_storage_path
            
            # Store file using convenience function
            store_result = store_file(
                workspace_id=sample_workspace_id,
                original_filename="test.txt",
                file_content=sample_txt_content,
                content_type="text/plain"
            )
            
            assert store_result['original_filename'] == "test.txt"
            assert store_result['stored_filename'].endswith('.txt')
            
            # Retrieve file using convenience function
            content, metadata = retrieve_file(
                workspace_id=sample_workspace_id,
                stored_filename=store_result['stored_filename']
            )
            
            assert content == sample_txt_content
            assert metadata['stored_filename'] == store_result['stored_filename']
            
            # Delete file using convenience function
            result = delete_file(
                workspace_id=sample_workspace_id,
                stored_filename=store_result['stored_filename']
            )
            
            assert result is True
            
            # File should no longer exist
            with pytest.raises(FileNotFoundError):
                retrieve_file(
                    workspace_id=sample_workspace_id,
                    stored_filename=store_result['stored_filename']
                )


class TestEdgeCases:
    """Test edge cases and error conditions"""
    
    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directory for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def file_storage_service(self, temp_storage_path):
        """Create FileStorageService with temporary storage"""
        with patch('app.services.file_storage.settings') as mock_settings:
            mock_settings.STORAGE_PATH = temp_storage_path
            service = FileStorageService()
            yield service
    
    def test_empty_file_content(self, file_storage_service):
        """Test handling of empty file content"""
        workspace_id = str(uuid.uuid4())
        
        result = file_storage_service.store_file(
            workspace_id=workspace_id,
            original_filename="empty.txt",
            file_content=b"",
            content_type="text/plain"
        )
        
        assert result['file_size'] == 0
        
        # Should be able to retrieve empty file
        content, metadata = file_storage_service.retrieve_file(
            workspace_id=workspace_id,
            stored_filename=result['stored_filename']
        )
        
        assert content == b""
        assert metadata['file_size'] == 0
    
    def test_filename_with_special_characters(self, file_storage_service):
        """Test handling of filenames with special characters"""
        workspace_id = str(uuid.uuid4())
        
        # These should be sanitized but still work
        special_filenames = [
            "test file with spaces.txt",
            "test-file_with-underscores.pdf",
            "test.file.with.dots.txt"
        ]
        
        for filename in special_filenames:
            result = file_storage_service.store_file(
                workspace_id=workspace_id,
                original_filename=filename,
                file_content=b"test content"
            )
            
            # Should generate unique filename with proper extension
            assert result['stored_filename'].endswith(Path(filename).suffix)
            assert result['original_filename'] == filename
    
    def test_case_insensitive_extensions(self, file_storage_service):
        """Test that file extensions are handled case-insensitively"""
        workspace_id = str(uuid.uuid4())
        
        # These should all be accepted
        case_variations = [
            "test.PDF",
            "test.Pdf",
            "test.TXT",
            "test.Txt"
        ]
        
        for filename in case_variations:
            result = file_storage_service.store_file(
                workspace_id=workspace_id,
                original_filename=filename,
                file_content=b"test content"
            )
            
            # Should normalize to lowercase extension
            expected_ext = Path(filename).suffix.lower()
            assert result['stored_filename'].endswith(expected_ext)