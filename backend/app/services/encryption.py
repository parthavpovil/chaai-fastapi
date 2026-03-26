"""
Encryption Service
AES-256-CBC encryption for channel credentials and sensitive data
"""
import os
import base64
import logging
from typing import Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding, hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

from app.config import settings


class EncryptionError(Exception):
    """Base exception for encryption errors"""
    pass


class EncryptionService:
    """
    AES-256-CBC encryption service for channel credentials
    Uses PBKDF2 key derivation with secure salt generation
    """
    
    def __init__(self):
        self.key_size = 32  # 256 bits
        self.iv_size = 16   # 128 bits for AES block size
        self.salt_size = 16 # 128 bits for PBKDF2 salt
        self.iterations = 100000  # PBKDF2 iterations
        
        # Get encryption key from environment
        if not settings.ENCRYPTION_KEY:
            raise EncryptionError("ENCRYPTION_KEY environment variable not set")
        
        self.master_key = settings.ENCRYPTION_KEY.encode('utf-8')
    
    def _derive_key(self, salt: bytes) -> bytes:
        """Derive encryption key using PBKDF2"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.key_size,
            salt=salt,
            iterations=self.iterations,
            backend=default_backend()
        )
        return kdf.derive(self.master_key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-CBC
        
        Returns base64-encoded string containing: salt + iv + ciphertext
        """
        try:
            # Generate random salt and IV
            salt = os.urandom(self.salt_size)
            iv = os.urandom(self.iv_size)
            
            # Derive key from master key and salt
            key = self._derive_key(salt)
            
            # Pad plaintext to block size
            padder = padding.PKCS7(128).padder()
            padded_data = padder.update(plaintext.encode('utf-8'))
            padded_data += padder.finalize()
            
            # Encrypt with AES-256-CBC
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            ciphertext = encryptor.update(padded_data) + encryptor.finalize()
            
            # Combine salt + iv + ciphertext and encode as base64
            encrypted_data = salt + iv + ciphertext
            return base64.b64encode(encrypted_data).decode('utf-8')
            
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {str(e)}")
    
    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt base64-encoded encrypted data
        
        Expects format: salt + iv + ciphertext
        """
        try:
            # Decode from base64
            data = base64.b64decode(encrypted_data.encode('utf-8'))
            
            # Extract salt, IV, and ciphertext
            salt = data[:self.salt_size]
            iv = data[self.salt_size:self.salt_size + self.iv_size]
            ciphertext = data[self.salt_size + self.iv_size:]
            
            # Derive key from master key and salt
            key = self._derive_key(salt)
            
            # Decrypt with AES-256-CBC
            cipher = Cipher(
                algorithms.AES(key),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Remove padding
            unpadder = padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_plaintext)
            plaintext += unpadder.finalize()
            
            return plaintext.decode('utf-8')
            
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {str(e)}")


# ─── Singleton Instance ───────────────────────────────────────────────────────

try:
    encryption_service = EncryptionService()
except Exception as e:
    # Log error but don't crash on startup
    logger.warning(f"Failed to initialize encryption service: {e}")
    encryption_service = None


# ─── Convenience Functions ────────────────────────────────────────────────────

def encrypt_credential(credential: str) -> str:
    """Encrypt a channel credential string"""
    if not encryption_service:
        raise EncryptionError("Encryption service not initialized")
    return encryption_service.encrypt(credential)


def decrypt_credential(encrypted_credential: str) -> str:
    """Decrypt a channel credential string"""
    if not encryption_service:
        raise EncryptionError("Encryption service not initialized")
    return encryption_service.decrypt(encrypted_credential)