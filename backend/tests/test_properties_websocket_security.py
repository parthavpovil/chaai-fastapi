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
from sqlalchemy.ext.asyncio import AsyncSession

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
        user_id_1=st.uuids(),
        user_id_2=st.uuids(),
        event_type=st.sampled_from(['escalation', 'agent_claim', 'new_message'])
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_property_18_websocket_event_broadcasting(self, workspace_id, user_id_1, user_id_2, event_type):
        """
        Property 18: WebSocket Event Broadcasting
        For any workspace event (conversation escalation, agent claim, new message),
        the WebSocket manager should broadcast the event to all authenticated connections
        in that workspace while maintaining isolation between different workspaces.
        
        Feature: chatsaas-backend, Property 18: WebSocket Event Broadcasting
        
        Validates: Requirements 7.1, 7.2, 7.3, 7.5
        """
        # Create fresh WebSocket manager for this test
        ws_manager = WebSocketManager()
        
        # Create mock WebSocket connections for target workspace
        mock_ws1 = AsyncMock(spec=WebSocket)
        mock_ws1.send_text = AsyncMock()
        mock_ws2 = AsyncMock(spec=WebSocket)
        mock_ws2.send_text = AsyncMock()
        
        # Create mock WebSocket connection for different workspace (should not receive events)
        other_workspace_id = uuid4()
        mock_ws_other = AsyncMock(spec=WebSocket)
        mock_ws_other.send_text = AsyncMock()
        
        # Manually add connections to the manager (simulating established connections)
        from app.services.websocket_manager import WebSocketConnection
        
        # Add connections to target workspace
        conn_id_1 = ws_manager.generate_connection_id(str(workspace_id), str(user_id_1))
        conn_1 = WebSocketConnection(
            websocket=mock_ws1,
            connection_id=conn_id_1,
            workspace_id=str(workspace_id),
            user_id=str(user_id_1),
            user_email=f"user1@test.com",
            user_role="owner"
        )
        
        conn_id_2 = ws_manager.generate_connection_id(str(workspace_id), str(user_id_2))
        conn_2 = WebSocketConnection(
            websocket=mock_ws2,
            connection_id=conn_id_2,
            workspace_id=str(workspace_id),
            user_id=str(user_id_2),
            user_email=f"user2@test.com",
            user_role="agent"
        )
        
        # Add connection to different workspace
        other_user_id = uuid4()
        conn_id_other = ws_manager.generate_connection_id(str(other_workspace_id), str(other_user_id))
        conn_other = WebSocketConnection(
            websocket=mock_ws_other,
            connection_id=conn_id_other,
            workspace_id=str(other_workspace_id),
            user_id=str(other_user_id),
            user_email=f"other@test.com",
            user_role="owner"
        )
        
        # Add to manager's connection pools
        ws_manager.workspace_connections[str(workspace_id)] = {
            conn_id_1: conn_1,
            conn_id_2: conn_2
        }
        ws_manager.workspace_connections[str(other_workspace_id)] = {
            conn_id_other: conn_other
        }
        ws_manager.connections[conn_id_1] = conn_1
        ws_manager.connections[conn_id_2] = conn_2
        ws_manager.connections[conn_id_other] = conn_other
        
        # Create event data based on event type
        conversation_id = str(uuid4())
        
        if event_type == 'escalation':
            event_data = {
                "type": "escalation",
                "conversation_id": conversation_id,
                "reason": "explicit",
                "confidence": 0.95,
                "timestamp": datetime.now().isoformat()
            }
        elif event_type == 'agent_claim':
            event_data = {
                "type": "agent_claim",
                "conversation_id": conversation_id,
                "agent_id": str(user_id_2),
                "agent_name": "Test Agent",
                "timestamp": datetime.now().isoformat()
            }
        else:  # new_message
            event_data = {
                "type": "new_message",
                "conversation_id": conversation_id,
                "sender_type": "customer",
                "content": "Test message",
                "timestamp": datetime.now().isoformat()
            }
        
        # Broadcast event to target workspace
        sent_count = await ws_manager.broadcast_to_workspace(str(workspace_id), event_data)
        
        # Property 1: All connections in target workspace should receive the event
        assert sent_count == 2, f"Should broadcast to 2 connections in workspace, got {sent_count}"
        
        # Verify both connections in target workspace received the event
        assert mock_ws1.send_text.called, "First connection should receive event"
        assert mock_ws2.send_text.called, "Second connection should receive event"
        
        # Verify the event data was sent correctly
        call_args_1 = mock_ws1.send_text.call_args[0][0]
        call_args_2 = mock_ws2.send_text.call_args[0][0]
        
        # Parse JSON to verify content
        sent_data_1 = json.loads(call_args_1)
        sent_data_2 = json.loads(call_args_2)
        
        assert sent_data_1["type"] == event_type, "Event type should match"
        assert sent_data_2["type"] == event_type, "Event type should match"
        assert sent_data_1["conversation_id"] == conversation_id, "Conversation ID should match"
        assert sent_data_2["conversation_id"] == conversation_id, "Conversation ID should match"
        
        # Property 2: Workspace isolation - other workspace should NOT receive the event
        assert not mock_ws_other.send_text.called, \
            "Connection in different workspace should NOT receive event (workspace isolation)"
        
        # Property 3: Test broadcast with exclusion (e.g., don't send to sender)
        mock_ws1.send_text.reset_mock()
        mock_ws2.send_text.reset_mock()
        
        sent_count_excluded = await ws_manager.broadcast_to_workspace(
            str(workspace_id), 
            event_data,
            exclude_connection_id=conn_id_1
        )
        
        # Should only send to one connection (excluding conn_id_1)
        assert sent_count_excluded == 1, "Should broadcast to 1 connection when excluding one"
        assert not mock_ws1.send_text.called, "Excluded connection should not receive event"
        assert mock_ws2.send_text.called, "Non-excluded connection should receive event"
        
        # Property 4: Broadcasting to non-existent workspace should return 0
        non_existent_workspace = uuid4()
        sent_count_none = await ws_manager.broadcast_to_workspace(str(non_existent_workspace), event_data)
        assert sent_count_none == 0, "Broadcasting to non-existent workspace should return 0"

    @given(
        workspace_id=st.uuids(),
        user_id=st.uuids(),
        user_email=st.emails()
    )
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_property_19_websocket_connection_management(self, workspace_id, user_id, user_email):
        """
        Property 19: WebSocket Connection Management
        For any WebSocket connection attempt, the system should authenticate using
        JWT tokens in query parameters, validate tokens before accepting connections,
        and automatically clean up connection references when connections drop.
        
        Feature: chatsaas-backend, Property 19: WebSocket Connection Management
        
        Validates: Requirements 7.4, 7.6
        """
        # Create fresh WebSocket manager for this test
        ws_manager = WebSocketManager()
        
        # Create mock WebSocket
        mock_websocket = AsyncMock(spec=WebSocket)
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()
        mock_websocket.close = AsyncMock()
        
        # Create mock database session
        mock_db = AsyncMock(spec=AsyncSession)
        
        # Create valid JWT token
        valid_token = AuthService.create_access_token(
            user_id=user_id,
            email=user_email,
            role="owner",
            workspace_id=workspace_id
        )
        
        # Mock the authenticate_connection method to return auth info
        async def mock_authenticate(token, db):
            payload = AuthService.decode_access_token(token)
            if not payload:
                return None
            return {
                "user_id": payload.get("sub"),
                "workspace_id": payload.get("workspace_id"),
                "user_email": payload.get("email"),
                "user_role": payload.get("role", "owner")
            }
        
        # Patch authenticate_connection
        with patch.object(ws_manager, 'authenticate_connection', side_effect=mock_authenticate):
            # Test 1: Valid JWT token should establish connection
            connection = await ws_manager.connect(mock_websocket, valid_token, mock_db)
            
            # Verify connection was established
            assert connection is not None, "Connection should be established with valid token"
            assert connection.workspace_id == str(workspace_id), "Workspace ID should match"
            assert connection.user_id == str(user_id), "User ID should match"
            assert connection.user_email == user_email, "User email should match"
            
            # Verify WebSocket was accepted
            mock_websocket.accept.assert_called_once()
            
            # Verify connection was added to manager
            assert connection.connection_id in ws_manager.connections, "Connection should be in global pool"
            assert str(workspace_id) in ws_manager.workspace_connections, "Workspace pool should exist"
            assert connection.connection_id in ws_manager.workspace_connections[str(workspace_id)], \
                "Connection should be in workspace pool"
            
            # Verify connection confirmation was sent
            assert mock_websocket.send_text.called, "Connection confirmation should be sent"
            
            # Test 2: Connection cleanup on disconnect
            connection_id = connection.connection_id
            disconnect_result = await ws_manager.disconnect(connection_id)
            
            # Verify disconnect was successful
            assert disconnect_result is True, "Disconnect should return True"
            
            # Verify connection was removed from all pools
            assert connection_id not in ws_manager.connections, "Connection should be removed from global pool"
            
            # Verify workspace pool cleanup
            if str(workspace_id) in ws_manager.workspace_connections:
                assert connection_id not in ws_manager.workspace_connections[str(workspace_id)], \
                    "Connection should be removed from workspace pool"
            
            # Verify WebSocket was closed
            mock_websocket.close.assert_called()
            
            # Test 3: Invalid token should reject connection
            mock_websocket_invalid = AsyncMock(spec=WebSocket)
            mock_websocket_invalid.accept = AsyncMock()
            mock_websocket_invalid.close = AsyncMock()
            
            invalid_token = "invalid_token_string"
            
            connection_invalid = await ws_manager.connect(mock_websocket_invalid, invalid_token, mock_db)
            
            # Verify connection was rejected
            assert connection_invalid is None, "Connection should be rejected with invalid token"
            mock_websocket_invalid.close.assert_called_once(), "WebSocket should be closed on auth failure"
            
            # Test 4: Automatic cleanup on connection drop
            # Create a new connection
            mock_websocket3 = AsyncMock(spec=WebSocket)
            mock_websocket3.accept = AsyncMock()
            mock_websocket3.send_text = AsyncMock()
            mock_websocket3.close = AsyncMock()
            
            user_id_3 = uuid4()
            valid_token_3 = AuthService.create_access_token(
                user_id=user_id_3,
                email="user3@test.com",
                role="owner",
                workspace_id=workspace_id
            )
            
            connection3 = await ws_manager.connect(mock_websocket3, valid_token_3, mock_db)
            
            # Verify connection exists
            assert connection3 is not None, "Third connection should be established"
            assert connection3.connection_id in ws_manager.connections, "Connection should be in pool"
            
            # Simulate automatic cleanup (connection drop)
            await ws_manager.disconnect(connection3.connection_id)
            
            # Verify cleanup was successful
            assert connection3.connection_id not in ws_manager.connections, \
                "Connection should be automatically removed on disconnect"

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