"""
Property-Based Test for Credential Encryption Round Trip
Tests Property 5 from the design document.
"""

import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.strategies import composite
import json
from typing import Dict, Any

from app.services.encryption import EncryptionService, EncryptionError


@composite
def channel_credentials(draw):
    """Generate various channel credential formats"""
    credential_type = draw(st.sampled_from([
        'telegram',
        'whatsapp',
        'instagram',
        'webchat'
    ]))
    
    if credential_type == 'telegram':
        return json.dumps({
            "bot_token": draw(st.text(min_size=20, max_size=100, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters=':-_'))),
            "secret_token": draw(st.text(min_size=20, max_size=50, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
        })
    elif credential_type == 'whatsapp':
        return json.dumps({
            "phone_number_id": draw(st.text(min_size=10, max_size=30, alphabet=st.characters(whitelist_categories=('Nd',)))),
            "access_token": draw(st.text(min_size=50, max_size=200, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-'))),
            "app_secret": draw(st.text(min_size=32, max_size=64, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
        })
    elif credential_type == 'instagram':
        return json.dumps({
            "page_id": draw(st.text(min_size=10, max_size=30, alphabet=st.characters(whitelist_categories=('Nd',)))),
            "page_access_token": draw(st.text(min_size=50, max_size=200, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'), whitelist_characters='_-'))),
            "app_secret": draw(st.text(min_size=32, max_size=64, alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd'))))
        })
    else:  # webchat
        return json.dumps({
            "widget_id": draw(st.uuids()).hex,
            "primary_color": draw(st.text(min_size=6, max_size=7, alphabet='0123456789abcdef')),
            "welcome_message": draw(st.text(min_size=10, max_size=200))
        })


@composite
def simple_credentials(draw):
    """Generate simple credential strings"""
    return draw(st.text(min_size=1, max_size=500))


@composite
def special_character_credentials(draw):
    """Generate credentials with special characters"""
    return draw(st.text(
        min_size=10,
        max_size=200,
        alphabet=st.characters(
            whitelist_categories=('Lu', 'Ll', 'Nd', 'P'),
            whitelist_characters=' \t\n'
        )
    ))


@composite
def unicode_credentials(draw):
    """Generate credentials with unicode characters"""
    return draw(st.text(min_size=5, max_size=100))


class TestCredentialEncryptionProperties:
    """Property tests for credential encryption round trip"""
    
    @given(credential=channel_credentials())
    @settings(max_examples=5, deadline=5000)
    def test_property_5_channel_credential_encryption_round_trip(self, credential):
        """
        Property 5: Credential Encryption Round Trip
        
        For any channel credentials, encrypting with AES-256-CBC then decrypting 
        should produce the original credentials, and stored credentials should 
        never be readable in plaintext from the database.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        # Initialize encryption service
        encryption_service = EncryptionService()
        
        # Test 1: Encrypt the credential
        encrypted = encryption_service.encrypt(credential)
        
        # Verify encrypted data is not empty
        assert encrypted is not None
        assert len(encrypted) > 0
        assert isinstance(encrypted, str)
        
        # Test 2: Verify encrypted data is different from plaintext
        assert encrypted != credential, \
            "Encrypted credential should not match plaintext"
        
        # Test 3: Verify encrypted data is base64-encoded
        import base64
        try:
            decoded = base64.b64decode(encrypted.encode('utf-8'))
            assert len(decoded) > 0
        except Exception:
            pytest.fail("Encrypted data should be valid base64")
        
        # Test 4: Verify encrypted data contains salt + iv + ciphertext
        # Salt (16 bytes) + IV (16 bytes) + ciphertext (variable)
        assert len(decoded) >= 32, \
            "Encrypted data should contain at least salt (16) + IV (16) bytes"
        
        # Test 5: Decrypt the credential
        decrypted = encryption_service.decrypt(encrypted)
        
        # Test 6: Verify round trip produces original credential
        assert decrypted == credential, \
            "Decrypted credential should match original plaintext"
        
        # Test 7: Verify data integrity - parse JSON if it's JSON
        try:
            original_data = json.loads(credential)
            decrypted_data = json.loads(decrypted)
            assert original_data == decrypted_data, \
                "JSON structure should be preserved through encryption/decryption"
        except json.JSONDecodeError:
            # Not JSON, that's fine - already verified string equality
            pass
        
        # Test 8: Verify plaintext is not visible in encrypted data
        # Check that no part of the plaintext appears in the encrypted data
        if len(credential) > 10:
            # Check for substrings of plaintext in encrypted data
            for i in range(0, len(credential) - 10, 5):
                substring = credential[i:i+10]
                assert substring not in encrypted, \
                    f"Plaintext substring '{substring}' should not appear in encrypted data"
    
    @given(credential=simple_credentials())
    @settings(max_examples=3, deadline=5000)
    def test_property_5_simple_credential_encryption_round_trip(self, credential):
        """
        Property 5: Credential Encryption Round Trip (Simple Strings)
        
        For any simple credential string, encryption and decryption should 
        maintain data integrity without loss.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Encrypt and decrypt
        encrypted = encryption_service.encrypt(credential)
        decrypted = encryption_service.decrypt(encrypted)
        
        # Verify round trip
        assert decrypted == credential, \
            "Simple credential should survive encryption/decryption round trip"
        
        # Verify encrypted is different from plaintext
        assert encrypted != credential, \
            "Encrypted credential should differ from plaintext"
    
    @given(credential=special_character_credentials())
    @settings(max_examples=3, deadline=5000)
    def test_property_5_special_characters_encryption_round_trip(self, credential):
        """
        Property 5: Credential Encryption Round Trip (Special Characters)
        
        For any credential containing special characters, punctuation, or whitespace,
        encryption and decryption should preserve all characters exactly.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Encrypt and decrypt
        encrypted = encryption_service.encrypt(credential)
        decrypted = encryption_service.decrypt(encrypted)
        
        # Verify exact match including special characters
        assert decrypted == credential, \
            "Special characters should be preserved through encryption/decryption"
        
        # Verify byte-level equality
        assert decrypted.encode('utf-8') == credential.encode('utf-8'), \
            "Byte representation should match exactly"
    
    @given(credential=unicode_credentials())
    @settings(max_examples=3, deadline=5000)
    def test_property_5_unicode_encryption_round_trip(self, credential):
        """
        Property 5: Credential Encryption Round Trip (Unicode)
        
        For any credential containing unicode characters, encryption and 
        decryption should preserve all unicode data correctly.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Encrypt and decrypt
        encrypted = encryption_service.encrypt(credential)
        decrypted = encryption_service.decrypt(encrypted)
        
        # Verify unicode preservation
        assert decrypted == credential, \
            "Unicode characters should be preserved through encryption/decryption"
    
    @given(
        credential=st.text(min_size=1, max_size=100),
        iterations=st.integers(min_value=2, max_value=5)
    )
    @settings(max_examples=3, deadline=5000)
    def test_property_5_multiple_encryption_cycles(self, credential, iterations):
        """
        Property 5: Credential Encryption Round Trip (Multiple Cycles)
        
        For any credential, multiple encryption/decryption cycles should 
        maintain data integrity without degradation.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        current = credential
        
        # Perform multiple encryption/decryption cycles
        for i in range(iterations):
            encrypted = encryption_service.encrypt(current)
            decrypted = encryption_service.decrypt(encrypted)
            
            # Verify each cycle preserves data
            assert decrypted == current, \
                f"Data should be preserved after cycle {i+1}"
            
            current = decrypted
        
        # Verify final result matches original
        assert current == credential, \
            f"After {iterations} cycles, credential should match original"
    
    @given(credential=st.text(min_size=10, max_size=100))
    @settings(max_examples=3, deadline=5000)
    def test_property_5_encryption_produces_different_ciphertexts(self, credential):
        """
        Property 5: Credential Encryption Round Trip (Unique Ciphertexts)
        
        For any credential, encrypting the same plaintext multiple times should 
        produce different ciphertexts (due to random IV and salt), but all should 
        decrypt to the same plaintext.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Encrypt the same credential multiple times
        encrypted_1 = encryption_service.encrypt(credential)
        encrypted_2 = encryption_service.encrypt(credential)
        encrypted_3 = encryption_service.encrypt(credential)
        
        # Verify ciphertexts are different (due to random IV and salt)
        assert encrypted_1 != encrypted_2, \
            "Multiple encryptions should produce different ciphertexts"
        assert encrypted_2 != encrypted_3, \
            "Multiple encryptions should produce different ciphertexts"
        assert encrypted_1 != encrypted_3, \
            "Multiple encryptions should produce different ciphertexts"
        
        # Verify all decrypt to the same plaintext
        decrypted_1 = encryption_service.decrypt(encrypted_1)
        decrypted_2 = encryption_service.decrypt(encrypted_2)
        decrypted_3 = encryption_service.decrypt(encrypted_3)
        
        assert decrypted_1 == credential, \
            "First encryption should decrypt to original"
        assert decrypted_2 == credential, \
            "Second encryption should decrypt to original"
        assert decrypted_3 == credential, \
            "Third encryption should decrypt to original"
    
    @given(credential=st.text(min_size=1, max_size=100))
    @settings(max_examples=3, deadline=5000)
    def test_property_5_invalid_encrypted_data_raises_error(self, credential):
        """
        Property 5: Credential Encryption Round Trip (Error Handling)
        
        For any invalid encrypted data, decryption should raise an appropriate 
        error rather than returning corrupted data.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Test 1: Decrypting plaintext should fail
        with pytest.raises(EncryptionError):
            encryption_service.decrypt(credential)
        
        # Test 2: Decrypting corrupted base64 should fail
        encrypted = encryption_service.encrypt(credential)
        
        # Corrupt the encrypted data
        if len(encrypted) > 10:
            corrupted = encrypted[:10] + "XXXXX" + encrypted[15:]
            
            with pytest.raises(EncryptionError):
                encryption_service.decrypt(corrupted)
        
        # Test 3: Decrypting truncated data should fail
        if len(encrypted) > 20:
            truncated = encrypted[:len(encrypted)//2]
            
            with pytest.raises(EncryptionError):
                encryption_service.decrypt(truncated)
    
    @given(
        credential=st.text(min_size=1, max_size=1000),
        size_category=st.sampled_from(['tiny', 'small', 'medium', 'large'])
    )
    @settings(max_examples=3, deadline=5000)
    def test_property_5_encryption_handles_various_sizes(self, credential, size_category):
        """
        Property 5: Credential Encryption Round Trip (Size Handling)
        
        For any credential size, encryption and decryption should work correctly
        and maintain data integrity.
        
        Validates: Requirements 2.5, 12.3
        
        Feature: chatsaas-backend, Property 5: Credential Encryption Round Trip
        """
        encryption_service = EncryptionService()
        
        # Adjust credential size based on category
        if size_category == 'tiny':
            test_credential = credential[:10] if len(credential) > 10 else credential
        elif size_category == 'small':
            test_credential = credential[:50] if len(credential) > 50 else credential
        elif size_category == 'medium':
            test_credential = credential[:200] if len(credential) > 200 else credential
        else:  # large
            test_credential = credential
        
        # Skip empty credentials
        if not test_credential:
            test_credential = "a"
        
        # Encrypt and decrypt
        encrypted = encryption_service.encrypt(test_credential)
        decrypted = encryption_service.decrypt(encrypted)
        
        # Verify round trip
        assert decrypted == test_credential, \
            f"Credential of size {len(test_credential)} should survive round trip"
        
        # Verify encrypted size is reasonable (should be larger due to salt+iv+padding)
        import base64
        encrypted_bytes = base64.b64decode(encrypted.encode('utf-8'))
        
        # Encrypted size should be at least: salt(16) + iv(16) + padded_plaintext
        assert len(encrypted_bytes) >= 32, \
            "Encrypted data should contain salt and IV"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
