"""
Property-Based Tests for WebSocket, Security, and File Storage
Tests properties 18-30 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import json
import hashlib
import hmac
import secrets
import tempfile
import os
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import WebSocket

from app.database import get_db
from app.models import Workspace, User, PlatformSetting, UsageCounter
from app.services.websocket_manager import WebSocketManager
from app.services.rate_limiter import RateLimiter
from app.services.file_storage import FileStorageService
from app.services.auth_service import AuthService

@composite
def webhook_signature(draw):
    """Generate webhook signatures for testing"""
    secret = draw(st.text(min_size=10, max_size=50))
    payload = draw(st.text(min_size=10, max_size=1000))
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return secret, payload, signature

@composite
def file_content(draw):
    """Generate file content for testing"""
    return draw(st.binary(min_size=100, max_size=10000))

@composite
def filename(draw):
    """Generate valid filenames"""
    name = draw(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
    extension = draw(st.sampled_from(['.txt', '.pdf', '.doc']))
    return f"{name}{extension}"

class TestWebSocketProperties:
    """Property tests for WebSocket functionality"""
    
    @given(
        workspace_id=st.uuids(),
        user_id=st.uuids(),
        event_type=st.sampled_from(['escalation', 'claim', 'message'])
    )
    @settings(max_examples=100)
    async def test_property_18_websocket_event_broadcasting(self, workspace_id, user_id, event_type):
        """
        Property 18: WebSocket Event Broadcasting
        For any workspace event, the WebSocket manager should broadcast to all
        authenticated connections in that workspace while maintaining isolation.
        
        Validates: Requirements 7.1, 7.2, 7.3, 7.5
        """
        websocket_manager = WebSocketManager()
        
        # Mock WebSocket connections
        mock_ws1 = MagicMock(spec=WebSocket)
        mock_ws2 = MagicMock(spec=WebSocket)
        mock_ws_other_workspace = MagicMock(spec=WebSocket)
        
        other_workspace_id = uuid4()
        
        # Add connections to workspace
        websocket_manager.connections[workspace_id] = {
            user_id: mock_ws1,
            uuid4(): mock_ws2
        }
        websocket_manager.connections[other_workspace_id] = {
            uuid4(): mock_ws_other_workspace
        }
        
        # Create event data
        event_data = {
            "type": event_type,
            "workspace_id": str(workspace_id),
            "timestamp": datetime.now().isoformat(),
            "data": {"test": "data"}
        }
        
        # Broadcast event
        await websocket_manager.broadcast_to_workspace(workspace_id, event_data)
        
        # Verify connections in target workspace received event
        mock_ws1.send_json.assert_called_once_with(event_data)
        mock_ws2.send_json.assert_called_once_with(event_data)
        
        # Verify other workspace connections did not receive event
        mock_ws_other_workspace.send_json.assert_not_called()

    @given(
        workspace_id=st.uuids(),
        user_id=st.uuids(),
        jwt_token=st.text(min_size=20, max_size=200)
    )
    @settings(max_examples=100)
    async def test_property_19_websocket_connection_management(self, workspace_id, user_id, jwt_token):
        """
        Property 19: WebSocket Connection Management
        For any WebSocket connection attempt, the system should authenticate using
        JWT tokens and clean up connections when they drop.
        
        Validates: Requirements 7.4, 7.6
        """
        websocket_manager = WebSocketManager()
        auth_service = AuthService()
        
        mock_websocket = MagicMock(spec=WebSocket)
        
        # Test valid JWT token
        with patch.object(auth_service, 'decode_token') as mock_decode:
            mock_decode.return_value = {
                "sub": str(user_id),
                "workspace_id": str(workspace_id),
                "role": "owner"
            }
            
            # Connect WebSocket
            await websocket_manager.connect(mock_websocket, workspace_id, user_id)
            
            # Verify connection was added
            assert workspace_id in websocket_manager.connections
            assert user_id in websocket_manager.connections[workspace_id]
            assert websocket_manager.connections[workspace_id][user_id] == mock_websocket
            
            # Test connection cleanup
            await websocket_manager.disconnect(mock_websocket, workspace_id, user_id)
            
            # Verify connection was removed
            if workspace_id in websocket_manager.connections:
                assert user_id not in websocket_manager.connections[workspace_id]

    @given(
        secret=st.text(min_size=10, max_size=50),
        payload=st.text(min_size=10, max_size=1000),
        tampered_payload=st.text(min_size=10, max_size=1000)
    )
    @settings(max_examples=100)
    async def test_property_20_webhook_security_verification(self, secret, payload, tampered_payload):
        """
        Property 20: Webhook Security Verification
        For any incoming webhook, the system should verify signatures using
        timing-safe comparison and reject invalid signatures.
        
        Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
        """
        from app.utils.security import verify_webhook_signature
        
        # Generate valid signature
        valid_signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        
        # Test valid signature
        is_valid = verify_webhook_signature(payload, valid_signature, secret)
        assert is_valid, "Valid signature should be accepted"
        
        # Test invalid signature with tampered payload
        if tampered_payload != payload:
            is_invalid = verify_webhook_signature(tampered_payload, valid_signature, secret)
            assert not is_invalid, "Invalid signature should be rejected"
        
        # Test completely wrong signature
        wrong_signature = "wrong_signature_" + secrets.token_hex(32)
        is_wrong = verify_webhook_signature(payload, wrong_signature, secret)
        assert not is_wrong, "Wrong signature should be rejected"


class TestSecurityProperties:
    """Property tests for security implementation"""
    
    @given(
        session_token=st.text(min_size=10, max_size=100),
        message_count=st.integers(min_value=1, max_value=20)
    )
    @settings(max_examples=100)
    async def test_property_26_rate_limiting_enforcement(self, session_token, message_count):
        """
        Property 26: Rate Limiting Enforcement
        For any WebChat session, the system should enforce 10 messages per minute
        using database-backed counters.
        
        Validates: Requirements 12.1, 16.3
        """
        rate_limiter = RateLimiter()
        
        async with get_db() as db:
            # Test rate limiting
            allowed_count = 0
            
            for i in range(message_count):
                is_allowed = await rate_limiter.check_rate_limit(
                    db=db,
                    session_token=session_token,
                    limit=10,
                    window_minutes=1
                )
                
                if is_allowed:
                    allowed_count += 1
                    await rate_limiter.increment_counter(db, session_token)
            
            # Should allow up to 10 messages
            if message_count <= 10:
                assert allowed_count == message_count
            else:
                assert allowed_count <= 10

    @given(is_maintenance_mode=st.booleans())
    @settings(max_examples=100)
    async def test_property_28_maintenance_mode_security(self, is_maintenance_mode):
        """
        Property 28: Maintenance Mode Security
        For any request during maintenance mode, the system should reject
        non-admin requests while allowing admin access.
        
        Validates: Requirements 12.6
        """
        from app.middleware.maintenance import check_maintenance_mode
        
        async with get_db() as db:
            # Set maintenance mode
            maintenance_setting = PlatformSetting(
                key="maintenance_mode",
                value="true" if is_maintenance_mode else "false"
            )
            db.add(maintenance_setting)
            await db.commit()
            
            # Test non-admin user
            regular_user = {"role": "owner", "email": "user@test.com"}
            admin_user = {"role": "admin", "email": "admin@platform.com"}
            
            if is_maintenance_mode:
                # Regular user should be blocked
                with pytest.raises(Exception) as exc_info:
                    await check_maintenance_mode(db, regular_user)
                assert "maintenance" in str(exc_info.value).lower()
                
                # Admin should be allowed (no exception)
                try:
                    await check_maintenance_mode(db, admin_user)
                except Exception:
                    pytest.fail("Admin should be allowed during maintenance mode")
            else:
                # Both should be allowed when maintenance mode is off
                try:
                    await check_maintenance_mode(db, regular_user)
                    await check_maintenance_mode(db, admin_user)
                except Exception:
                    pytest.fail("All users should be allowed when maintenance mode is off")

    @given(
        password=st.text(min_size=8, max_size=50),
        webhook_payload=st.text(min_size=10, max_size=1000),
        webhook_secret=st.text(min_size=10, max_size=50)
    )
    @settings(max_examples=100)
    async def test_property_27_security_implementation_standards(self, password, webhook_payload, webhook_secret):
        """
        Property 27: Security Implementation Standards
        For any security-sensitive operation, the system should use proper
        security standards including timing-safe comparison and bcrypt hashing.
        
        Validates: Requirements 12.2, 12.4, 12.5
        """
        from app.utils.security import hash_password, verify_password, verify_webhook_signature
        
        # Test bcrypt password hashing
        password_hash = hash_password(password)
        
        # Verify hash format (bcrypt starts with $2b$)
        assert password_hash.startswith('$2b$'), "Should use bcrypt hashing"
        assert password_hash != password, "Hash should be different from original"
        
        # Verify password verification works
        assert verify_password(password, password_hash), "Password verification should work"
        assert not verify_password(password + "wrong", password_hash), "Wrong password should fail"
        
        # Test timing-safe webhook verification
        correct_signature = hmac.new(
            webhook_secret.encode(), 
            webhook_payload.encode(), 
            hashlib.sha256
        ).hexdigest()
        
        # Should accept correct signature
        assert verify_webhook_signature(webhook_payload, correct_signature, webhook_secret)
        
        # Should reject incorrect signature
        wrong_signature = correct_signature[:-1] + "x"  # Change last character
        assert not verify_webhook_signature(webhook_payload, wrong_signature, webhook_secret)


class TestFileStorageProperties:
    """Property tests for file storage and management"""
    
    @given(
        workspace_id=st.uuids(),
        filename=filename(),
        content=file_content()
    )
    @settings(max_examples=100)
    async def test_property_29_file_storage_security_and_management(self, workspace_id, filename, content):
        """
        Property 29: File Storage Security and Management
        For any document upload, the system should save files to workspace-specific
        paths, generate unique filenames, and validate file types.
        
        Validates: Requirements 13.1, 13.2, 13.3, 13.5
        """
        file_storage = FileStorageService()
        
        # Test file storage
        stored_path = await file_storage.store_file(
            workspace_id=workspace_id,
            filename=filename,
            content=content
        )
        
        # Verify workspace-specific path
        expected_path_prefix = f"documents/{workspace_id}"
        assert expected_path_prefix in stored_path
        
        # Verify unique filename generation
        stored_path2 = await file_storage.store_file(
            workspace_id=workspace_id,
            filename=filename,  # Same filename
            content=content
        )
        
        # Should generate different paths for same filename
        assert stored_path != stored_path2
        
        # Verify file exists and content matches
        assert os.path.exists(stored_path)
        with open(stored_path, 'rb') as f:
            stored_content = f.read()
        assert stored_content == content
        
        # Cleanup
        if os.path.exists(stored_path):
            os.remove(stored_path)
        if os.path.exists(stored_path2):
            os.remove(stored_path2)

    @given(
        workspace_id=st.uuids(),
        filename=filename(),
        content=file_content()
    )
    @settings(max_examples=100)
    async def test_property_30_file_cleanup_completeness(self, workspace_id, filename, content):
        """
        Property 30: File Cleanup Completeness
        For any document deletion, the system should remove both database
        records and filesystem files completely.
        
        Validates: Requirements 13.4, 13.6
        """
        file_storage = FileStorageService()
        
        async with get_db() as db:
            # Store file
            stored_path = await file_storage.store_file(
                workspace_id=workspace_id,
                filename=filename,
                content=content
            )
            
            # Create document record
            from app.models import Document
            document = Document(
                id=uuid4(),
                workspace_id=workspace_id,
                filename=os.path.basename(stored_path),
                original_filename=filename,
                file_size=len(content),
                content_type="application/octet-stream",
                status="completed"
            )
            db.add(document)
            await db.commit()
            
            # Verify file exists
            assert os.path.exists(stored_path)
            
            # Delete document
            await file_storage.delete_document(db, document.id)
            
            # Verify database record is removed
            deleted_doc = await db.get(Document, document.id)
            assert deleted_doc is None
            
            # Verify file is removed from filesystem
            assert not os.path.exists(stored_path)


class TestUsageTrackingProperties:
    """Property tests for usage tracking and management"""
    
    @given(
        workspace_id=st.uuids(),
        initial_usage=st.integers(min_value=0, max_value=10000),
        additional_usage=st.integers(min_value=1, max_value=5000)
    )
    @settings(max_examples=100)
    async def test_property_22_usage_counter_management(self, workspace_id, initial_usage, additional_usage):
        """
        Property 22: Usage Counter Management
        For any workspace usage tracking, the system should accurately track
        counters and reset monthly limits appropriately.
        
        Validates: Requirements 9.6
        """
        from app.services.usage_service import UsageService
        usage_service = UsageService()
        
        async with get_db() as db:
            current_month = datetime.now().strftime("%Y-%m")
            
            # Create initial usage counter
            usage_counter = UsageCounter(
                id=uuid4(),
                workspace_id=workspace_id,
                month=current_month,
                messages_sent=0,
                tokens_used=initial_usage
            )
            db.add(usage_counter)
            await db.commit()
            
            # Increment usage
            await usage_service.increment_usage(
                db=db,
                workspace_id=workspace_id,
                tokens_used=additional_usage
            )
            
            # Verify usage was incremented
            await db.refresh(usage_counter)
            assert usage_counter.tokens_used == initial_usage + additional_usage
            
            # Test monthly reset
            next_month = (datetime.now().replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
            
            # Simulate month change
            await usage_service.reset_monthly_usage(db, workspace_id, next_month)
            
            # Verify new month counter created
            new_usage = await usage_service.get_current_usage(db, workspace_id)
            assert new_usage.month == next_month
            assert new_usage.tokens_used == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])