"""
Manual test for file storage service to verify it works with actual configuration
"""
import uuid
import tempfile
from pathlib import Path

# Set up environment variables for testing BEFORE importing anything
import os
os.environ['JWT_SECRET_KEY'] = 'test_jwt_secret_key_that_is_long_enough_for_validation_requirements'
os.environ['ENCRYPTION_KEY'] = '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
os.environ['PROCESS_SECRET'] = 'test_process_secret_that_is_long_enough'

# Create temporary directory and set it before importing
temp_dir = tempfile.mkdtemp()
os.environ['STORAGE_PATH'] = temp_dir

# Now import the service
from unittest.mock import patch, MagicMock
from app.services.file_storage import FileStorageService


def test_file_storage_manual():
    """Manual test of file storage service"""

    # Replace the module-level 'settings' name in file_storage so that
    # FileStorageService.__init__ picks up temp_dir regardless of whether
    # the settings singleton was already initialised before this test ran.
    mock_settings = MagicMock()
    mock_settings.STORAGE_PATH = temp_dir

    with patch('app.services.file_storage.settings', mock_settings):
        try:
            # Create service instance
            service = FileStorageService()

            # Test data
            workspace_id = str(uuid.uuid4())
            filename = "test_document.txt"
            content = b"This is a test document for manual verification."

            print(f"Testing file storage with workspace: {workspace_id}")
            print(f"Storage path: {temp_dir}")

            # Store file
            result = service.store_file(
                workspace_id=workspace_id,
                original_filename=filename,
                file_content=content,
                content_type="text/plain"
            )

            print(f"Stored file: {result}")

            # Verify file exists
            file_path = Path(result['file_path'])
            assert file_path.exists(), f"File should exist at {file_path}"

            # Verify content
            stored_content = file_path.read_bytes()
            assert stored_content == content, "Stored content should match original"

            # Verify workspace isolation
            workspace_path = Path(temp_dir) / "documents" / workspace_id
            assert workspace_path.exists(), f"Workspace directory should exist at {workspace_path}"

            # Retrieve file
            retrieved_content, metadata = service.retrieve_file(workspace_id, result['stored_filename'])
            assert retrieved_content == content, "Retrieved content should match original"

            print(f"Retrieved metadata: {metadata}")

            # Test file listing
            files = service.list_workspace_files(workspace_id)
            assert len(files) == 1, "Should have one file in workspace"
            assert files[0]['stored_filename'] == result['stored_filename']

            print(f"Workspace files: {files}")

            # Test file deletion
            deleted = service.delete_file(workspace_id, result['stored_filename'])
            assert deleted, "File deletion should succeed"
            assert not file_path.exists(), "File should no longer exist after deletion"

            print("All file storage tests passed!")

        finally:
            # Clean up temporary directory
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    test_file_storage_manual()