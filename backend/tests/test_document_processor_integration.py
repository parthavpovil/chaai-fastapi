"""
Integration tests for Document Processor with File Storage Service
Tests that document processor correctly uses the file storage service
"""
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest

from app.services.document_processor import (
    DocumentProcessor,
    DocumentProcessingError,
    UnsupportedFileTypeError,
    FileSizeExceededError,
    process_uploaded_document
)


class TestDocumentProcessorIntegration:
    """Test document processor integration with file storage service"""
    
    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directory for testing"""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir
    
    @pytest.fixture
    def document_processor(self, temp_storage_path):
        """Create DocumentProcessor with temporary storage"""
        with patch('app.services.file_storage.settings') as mock_settings:
            mock_settings.STORAGE_PATH = temp_storage_path
            processor = DocumentProcessor()
            yield processor
    
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
        return b"This is a sample text file for testing document processing."
    
    def test_document_processor_uses_file_storage(self, document_processor, sample_workspace_id, sample_txt_content):
        """Test that document processor uses file storage service"""
        result = document_processor.store_file(
            workspace_id=sample_workspace_id,
            filename="test.txt",
            file_content=sample_txt_content,
            content_type="text/plain"
        )
        
        # Should return file storage service result format
        assert result['original_filename'] == "test.txt"
        assert result['stored_filename'].endswith('.txt')
        assert result['file_size'] == len(sample_txt_content)
        assert result['workspace_id'] == sample_workspace_id
        assert 'file_path' in result
        
        # File should exist at the specified path
        file_path = Path(result['file_path'])
        assert file_path.exists()
        assert file_path.read_bytes() == sample_txt_content
    
    def test_document_processor_validation_integration(self, document_processor, sample_workspace_id):
        """Test that document processor validation uses file storage service"""
        # Valid file should pass
        assert document_processor.validate_file("test.txt", 1000, "text/plain") is True
        
        # Invalid extension should fail
        with pytest.raises(UnsupportedFileTypeError):
            document_processor.validate_file("test.exe", 1000, "application/octet-stream")
        
        # File too large should fail
        with pytest.raises(FileSizeExceededError):
            document_processor.validate_file("test.txt", 20 * 1024 * 1024, "text/plain")  # 20MB
    
    def test_document_processor_workspace_isolation(self, document_processor, sample_txt_content):
        """Test that document processor maintains workspace isolation"""
        workspace1 = str(uuid.uuid4())
        workspace2 = str(uuid.uuid4())
        
        # Store same filename in different workspaces
        result1 = document_processor.store_file(
            workspace_id=workspace1,
            filename="test.txt",
            file_content=sample_txt_content
        )
        
        result2 = document_processor.store_file(
            workspace_id=workspace2,
            filename="test.txt",
            file_content=sample_txt_content
        )
        
        # Should have different paths
        assert result1['file_path'] != result2['file_path']
        assert workspace1 in result1['file_path']
        assert workspace2 in result2['file_path']
        
        # Both files should exist
        assert Path(result1['file_path']).exists()
        assert Path(result2['file_path']).exists()
    
    @pytest.mark.asyncio
    async def test_process_document_integration(self, document_processor, sample_workspace_id, sample_txt_content):
        """Test complete document processing pipeline with file storage"""
        result = await document_processor.process_document(
            workspace_id=sample_workspace_id,
            filename="test.txt",
            file_content=sample_txt_content,
            content_type="text/plain"
        )
        
        # Should have all expected fields
        assert result['original_filename'] == "test.txt"
        assert result['stored_filename'].endswith('.txt')
        assert result['file_size'] == len(sample_txt_content)
        assert result['file_type'] == '.txt'
        assert 'text_content' in result
        assert 'chunks' in result
        assert 'chunk_count' in result
        
        # File should exist at storage path
        storage_path = Path(result['storage_path'])
        assert storage_path.exists()
        assert storage_path.read_bytes() == sample_txt_content
        
        # Text content should be extracted
        assert result['text_content'] == sample_txt_content.decode('utf-8')
        
        # Should have chunks
        assert result['chunk_count'] > 0
        assert len(result['chunks']) == result['chunk_count']
    
    @pytest.mark.asyncio
    async def test_convenience_function_integration(self, temp_storage_path, sample_workspace_id, sample_txt_content):
        """Test convenience function works with file storage integration"""
        with patch('app.services.file_storage.settings') as mock_settings:
            mock_settings.STORAGE_PATH = temp_storage_path
            
            result = await process_uploaded_document(
                workspace_id=sample_workspace_id,
                filename="test.txt",
                file_content=sample_txt_content,
                content_type="text/plain"
            )
            
            # Should have all expected fields
            assert result['original_filename'] == "test.txt"
            assert result['stored_filename'].endswith('.txt')
            assert result['file_size'] == len(sample_txt_content)
            
            # File should exist
            storage_path = Path(result['storage_path'])
            assert storage_path.exists()
            assert storage_path.read_bytes() == sample_txt_content