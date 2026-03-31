"""
Unit tests for environment configuration system
Tests environment variable loading, validation, and error handling scenarios
Requirements: 14.1, 14.3
"""
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock
from pydantic import ValidationError

from app.config import Settings, TIER_LIMITS


class TestEnvironmentConfiguration:
    """Test environment variable loading and validation"""
    
    def test_settings_with_valid_environment_variables(self):
        """Test Settings class loads valid environment variables correctly"""
        # Test with minimal required environment variables
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,  # 64 character hex string
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'DATABASE_URL': 'postgresql+asyncpg://test:test@localhost:5432/test',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            
            # Verify required fields are loaded correctly
            assert settings.JWT_SECRET_KEY == env_vars['JWT_SECRET_KEY']
            assert settings.ENCRYPTION_KEY == env_vars['ENCRYPTION_KEY']
            assert settings.PROCESS_SECRET == env_vars['PROCESS_SECRET']
            assert settings.DATABASE_URL == env_vars['DATABASE_URL']
            
            # Verify defaults are applied for optional fields
            assert settings.DEBUG is False
            assert settings.APP_URL == "http://localhost:8000"
            assert settings.JWT_ALGORITHM == "HS256"
            assert settings.JWT_EXPIRE_MINUTES == 10080
            assert settings.AI_PROVIDER == "google"
            assert settings.EMBEDDING_PROVIDER == "google"
    
    def test_settings_with_all_environment_variables(self):
        """Test Settings class with all environment variables provided"""
        env_vars = {
            # Required fields
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'b' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'DATABASE_URL': 'postgresql+asyncpg://prod:prod@prod:5432/prod',
            
            # Application settings
            'DEBUG': 'true',
            'APP_URL': 'https://api.example.com',
            'ALLOWED_ORIGINS': '["https://app.example.com", "https://admin.example.com"]',
            
            # JWT settings
            'JWT_ALGORITHM': 'HS512',
            'JWT_EXPIRE_MINUTES': '1440',
            
            # AI Provider settings
            'AI_PROVIDER': 'openai',
            'EMBEDDING_PROVIDER': 'openai',
            'GOOGLE_API_KEY': 'test_google_key',
            'OPENAI_API_KEY': 'test_openai_key',
            'GROQ_API_KEY': 'test_groq_key',
            
            # Channel secrets
            'TELEGRAM_SECRET_TOKEN': 'test_telegram_secret',
            'WHATSAPP_APP_SECRET': 'test_whatsapp_secret',
            'INSTAGRAM_APP_SECRET': 'test_instagram_secret',
            
            # Email service
            'RESEND_API_KEY': 'test_resend_key',
            'RESEND_FROM_EMAIL': 'noreply@example.com',
            
            # File storage
            'STORAGE_PATH': '/custom/storage/path',
            
            # Administration
            'SUPER_ADMIN_EMAIL': 'admin@example.com',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            
            # Verify all fields are loaded correctly
            assert settings.DEBUG is True
            assert settings.APP_URL == 'https://api.example.com'
            assert settings.JWT_ALGORITHM == 'HS512'
            assert settings.JWT_EXPIRE_MINUTES == 1440
            assert settings.AI_PROVIDER == 'openai'
            assert settings.EMBEDDING_PROVIDER == 'openai'
            assert settings.GOOGLE_API_KEY == 'test_google_key'
            assert settings.OPENAI_API_KEY == 'test_openai_key'
            assert settings.GROQ_API_KEY == 'test_groq_key'
            assert settings.TELEGRAM_SECRET_TOKEN == 'test_telegram_secret'
            assert settings.WHATSAPP_APP_SECRET == 'test_whatsapp_secret'
            assert settings.INSTAGRAM_APP_SECRET == 'test_instagram_secret'
            assert settings.RESEND_API_KEY == 'test_resend_key'
            assert settings.RESEND_FROM_EMAIL == 'noreply@example.com'
            assert settings.STORAGE_PATH == '/custom/storage/path'
            assert settings.SUPER_ADMIN_EMAIL == 'admin@example.com'


class TestConfigurationValidation:
    """Test configuration validation and error handling"""
    
    def test_jwt_secret_key_too_short(self):
        """Test JWT_SECRET_KEY validation fails with short key"""
        env_vars = {
            'JWT_SECRET_KEY': 'short_key',  # Less than 32 characters
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about JWT_SECRET_KEY length
            errors = exc_info.value.errors()
            jwt_error = next((e for e in errors if e['loc'] == ('JWT_SECRET_KEY',)), None)
            assert jwt_error is not None
            assert 'at least 32 characters' in str(jwt_error['msg'])
    
    def test_encryption_key_invalid_length(self):
        """Test ENCRYPTION_KEY validation fails with invalid length"""
        test_cases = [
            ('a' * 63, 'too short'),  # 63 characters
            ('a' * 65, 'too long'),   # 65 characters
            ('', 'empty'),            # empty string
        ]
        
        for key, description in test_cases:
            env_vars = {
                'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
                'ENCRYPTION_KEY': key,
                'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                with pytest.raises(ValidationError) as exc_info:
                    Settings()
                
                # Verify the error is about ENCRYPTION_KEY length
                errors = exc_info.value.errors()
                encryption_error = next((e for e in errors if e['loc'] == ('ENCRYPTION_KEY',)), None)
                assert encryption_error is not None, f"Expected validation error for {description} encryption key"
    
    def test_process_secret_too_short(self):
        """Test PROCESS_SECRET validation fails with short secret"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'short',  # Less than 32 characters
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about PROCESS_SECRET length
            errors = exc_info.value.errors()
            process_error = next((e for e in errors if e['loc'] == ('PROCESS_SECRET',)), None)
            assert process_error is not None
            assert 'at least 32 characters' in str(process_error['msg'])
    
    def test_invalid_ai_provider(self):
        """Test AI_PROVIDER validation fails with invalid provider"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'AI_PROVIDER': 'invalid_provider',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about AI_PROVIDER pattern
            errors = exc_info.value.errors()
            ai_error = next((e for e in errors if e['loc'] == ('AI_PROVIDER',)), None)
            assert ai_error is not None
            assert 'should match pattern' in str(ai_error['msg'])
    
    def test_invalid_embedding_provider(self):
        """Test EMBEDDING_PROVIDER validation fails with invalid provider"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'EMBEDDING_PROVIDER': 'invalid_embedding_provider',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about EMBEDDING_PROVIDER pattern
            errors = exc_info.value.errors()
            embedding_error = next((e for e in errors if e['loc'] == ('EMBEDDING_PROVIDER',)), None)
            assert embedding_error is not None
            assert 'should match pattern' in str(embedding_error['msg'])
    
    def test_missing_required_environment_variables(self):
        """Test Settings validation fails when required variables are missing"""
        # Test with completely empty environment
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify errors for required fields
            errors = exc_info.value.errors()
            error_fields = {error['loc'][0] for error in errors}
            
            # These fields should have validation errors when missing
            required_fields = {'JWT_SECRET_KEY', 'ENCRYPTION_KEY', 'PROCESS_SECRET'}
            assert required_fields.issubset(error_fields), f"Missing validation errors for required fields: {required_fields - error_fields}"


class TestConfigurationErrorHandling:
    """Test configuration error handling scenarios"""
    
    def test_database_url_with_invalid_format(self):
        """Test DATABASE_URL with invalid format still loads (validation happens at connection time)"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'DATABASE_URL': 'invalid_database_url',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            # Settings should load successfully (URL validation happens at connection time)
            settings = Settings()
            assert settings.DATABASE_URL == 'invalid_database_url'
    
    def test_boolean_environment_variable_parsing(self):
        """Test boolean environment variables are parsed correctly"""
        test_cases = [
            ('true', True),
            ('True', True),
            ('TRUE', True),
            ('1', True),
            ('yes', True),
            ('false', False),
            ('False', False),
            ('FALSE', False),
            ('0', False),
            ('no', False),
        ]
        
        for env_value, expected in test_cases:
            env_vars = {
                'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
                'ENCRYPTION_KEY': 'a' * 64,
                'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
                'DEBUG': env_value,
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                settings = Settings()
                assert settings.DEBUG == expected, f"Expected DEBUG={expected} for env value '{env_value}'"
    
    def test_boolean_environment_variable_empty_string(self):
        """Test empty string for boolean environment variable causes validation error"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'DEBUG': '',  # Empty string should cause validation error
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about boolean parsing
            errors = exc_info.value.errors()
            debug_error = next((e for e in errors if e['loc'] == ('DEBUG',)), None)
            assert debug_error is not None
            assert 'bool_parsing' in str(debug_error['type'])
    
    def test_integer_environment_variable_parsing(self):
        """Test integer environment variables are parsed correctly"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'JWT_EXPIRE_MINUTES': '1440',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.JWT_EXPIRE_MINUTES == 1440
            assert isinstance(settings.JWT_EXPIRE_MINUTES, int)
    
    def test_invalid_integer_environment_variable(self):
        """Test invalid integer environment variables cause validation error"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'JWT_EXPIRE_MINUTES': 'not_a_number',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about JWT_EXPIRE_MINUTES type
            errors = exc_info.value.errors()
            jwt_expire_error = next((e for e in errors if e['loc'] == ('JWT_EXPIRE_MINUTES',)), None)
            assert jwt_expire_error is not None
            assert 'int' in str(jwt_expire_error['type'])
    
    def test_env_file_loading(self):
        """Test .env file loading functionality"""
        # Create a temporary .env file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as temp_env:
            temp_env.write('JWT_SECRET_KEY=env_file_jwt_secret_minimum_32_chars\n')
            temp_env.write('ENCRYPTION_KEY=' + 'c' * 64 + '\n')
            temp_env.write('PROCESS_SECRET=env_file_process_secret_minimum_32\n')
            temp_env.write('DEBUG=true\n')
            temp_env.write('APP_URL=https://env-file.example.com\n')
            temp_env_path = temp_env.name
        
        try:
            # Clear environment and test with env_file parameter
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings(_env_file=temp_env_path)
                
                assert settings.JWT_SECRET_KEY == 'env_file_jwt_secret_minimum_32_chars'
                assert settings.ENCRYPTION_KEY == 'c' * 64
                assert settings.PROCESS_SECRET == 'env_file_process_secret_minimum_32'
                assert settings.DEBUG is True
                assert settings.APP_URL == 'https://env-file.example.com'
        finally:
            # Clean up temporary file
            os.unlink(temp_env_path)
    
    def test_environment_variable_precedence_over_env_file(self):
        """Test environment variables take precedence over .env file"""
        # Create a temporary .env file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as temp_env:
            temp_env.write('JWT_SECRET_KEY=env_file_jwt_secret_minimum_32_chars\n')
            temp_env.write('ENCRYPTION_KEY=' + 'd' * 64 + '\n')
            temp_env.write('PROCESS_SECRET=env_file_process_secret_minimum_32\n')
            temp_env.write('DEBUG=false\n')
            temp_env_path = temp_env.name
        
        try:
            # Set environment variable that should override .env file
            env_vars = {
                'DEBUG': 'true',  # This should override the false in .env file
                'APP_URL': 'https://env-override.example.com',
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                settings = Settings(_env_file=temp_env_path)
                
                # Values from .env file
                assert settings.JWT_SECRET_KEY == 'env_file_jwt_secret_minimum_32_chars'
                assert settings.ENCRYPTION_KEY == 'd' * 64
                assert settings.PROCESS_SECRET == 'env_file_process_secret_minimum_32'
                
                # Values overridden by environment variables
                assert settings.DEBUG is True  # Overridden from false to true
                assert settings.APP_URL == 'https://env-override.example.com'  # From env var
        finally:
            # Clean up temporary file
            os.unlink(temp_env_path)


class TestTierConfiguration:
    """Test tier configuration constants"""
    
    def test_tier_limits_structure(self):
        """Test TIER_LIMITS has correct structure and values"""
        expected_tiers = ['free', 'starter', 'growth', 'pro']
        expected_fields = ['channels', 'agents', 'documents_max', 'monthly_messages', 'price']
        
        # Verify all expected tiers exist
        assert set(TIER_LIMITS.keys()) == set(expected_tiers)
        
        # Verify each tier has all required fields
        for tier_name, tier_config in TIER_LIMITS.items():
            assert set(tier_config.keys()) == set(expected_fields), f"Tier {tier_name} missing fields"
            
            # Verify all values are non-negative integers
            for field, value in tier_config.items():
                assert isinstance(value, int), f"Tier {tier_name}.{field} should be integer"
                assert value >= 0, f"Tier {tier_name}.{field} should be non-negative"
    
    def test_tier_limits_requirements_compliance(self):
        """Test TIER_LIMITS comply with requirements 14.1, 14.3"""
        # Verify specific tier limits as per requirements
        assert TIER_LIMITS['free']['channels'] == 1
        assert TIER_LIMITS['free']['agents'] == 0
        assert TIER_LIMITS['free']['documents_max'] == 3
        assert TIER_LIMITS['free']['monthly_messages'] == 500
        
        assert TIER_LIMITS['starter']['channels'] == 2
        assert TIER_LIMITS['starter']['agents'] == 0
        assert TIER_LIMITS['starter']['documents_max'] == 10
        assert TIER_LIMITS['starter']['monthly_messages'] == 2000
        
        assert TIER_LIMITS['growth']['channels'] == 4
        assert TIER_LIMITS['growth']['agents'] == 0
        assert TIER_LIMITS['growth']['documents_max'] == 25
        assert TIER_LIMITS['growth']['monthly_messages'] == 10000
        
        assert TIER_LIMITS['pro']['channels'] == 4
        assert TIER_LIMITS['pro']['agents'] == 2
        assert TIER_LIMITS['pro']['documents_max'] == 100
        assert TIER_LIMITS['pro']['monthly_messages'] == 50000
    
    def test_tier_limits_progression(self):
        """Test tier limits show logical progression"""
        tiers = ['free', 'starter', 'growth', 'pro']
        
        # Verify channels increase or stay same
        for i in range(len(tiers) - 1):
            current_channels = TIER_LIMITS[tiers[i]]['channels']
            next_channels = TIER_LIMITS[tiers[i + 1]]['channels']
            assert next_channels >= current_channels, f"Channels should not decrease from {tiers[i]} to {tiers[i + 1]}"
        
        # Verify documents_max increases
        for i in range(len(tiers) - 1):
            current_docs = TIER_LIMITS[tiers[i]]['documents_max']
            next_docs = TIER_LIMITS[tiers[i + 1]]['documents_max']
            assert next_docs > current_docs, f"Documents should increase from {tiers[i]} to {tiers[i + 1]}"
        
        # Verify monthly_messages increases
        for i in range(len(tiers) - 1):
            current_messages = TIER_LIMITS[tiers[i]]['monthly_messages']
            next_messages = TIER_LIMITS[tiers[i + 1]]['monthly_messages']
            assert next_messages > current_messages, f"Monthly messages should increase from {tiers[i]} to {tiers[i + 1]}"


class TestConfigurationEdgeCases:
    """Test edge cases and additional error scenarios"""
    
    def test_list_environment_variable_parsing(self):
        """Test list environment variables are parsed correctly"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'ALLOWED_ORIGINS': '["https://app.example.com", "https://admin.example.com"]',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert isinstance(settings.ALLOWED_ORIGINS, list)
            assert len(settings.ALLOWED_ORIGINS) == 2
            assert "https://app.example.com" in settings.ALLOWED_ORIGINS
            assert "https://admin.example.com" in settings.ALLOWED_ORIGINS
    
    def test_invalid_list_environment_variable(self):
        """Test invalid list environment variables cause settings error"""
        from pydantic_settings.sources import SettingsError
        
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'ALLOWED_ORIGINS': 'not_a_valid_json_list',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(SettingsError) as exc_info:
                Settings()
            
            # Verify the error is about ALLOWED_ORIGINS parsing
            assert 'ALLOWED_ORIGINS' in str(exc_info.value)
            assert 'error parsing value' in str(exc_info.value)
    
    def test_ai_provider_case_sensitivity(self):
        """Test AI_PROVIDER is case sensitive"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'AI_PROVIDER': 'GOOGLE',  # Uppercase should fail
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about AI_PROVIDER pattern
            errors = exc_info.value.errors()
            ai_error = next((e for e in errors if e['loc'] == ('AI_PROVIDER',)), None)
            assert ai_error is not None
    
    def test_embedding_provider_case_sensitivity(self):
        """Test EMBEDDING_PROVIDER is case sensitive"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'EMBEDDING_PROVIDER': 'OPENAI',  # Uppercase should fail
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                Settings()
            
            # Verify the error is about EMBEDDING_PROVIDER pattern
            errors = exc_info.value.errors()
            embedding_error = next((e for e in errors if e['loc'] == ('EMBEDDING_PROVIDER',)), None)
            assert embedding_error is not None
    
    def test_valid_ai_provider_combinations(self):
        """Test all valid AI provider combinations work"""
        valid_combinations = [
            ('google', 'google'),
            ('openai', 'openai'),
            ('groq', 'google'),  # Groq doesn't have embeddings, so use Google
            ('groq', 'openai'),  # Groq doesn't have embeddings, so use OpenAI
        ]
        
        for ai_provider, embedding_provider in valid_combinations:
            env_vars = {
                'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
                'ENCRYPTION_KEY': 'a' * 64,
                'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
                'AI_PROVIDER': ai_provider,
                'EMBEDDING_PROVIDER': embedding_provider,
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                settings = Settings()
                assert settings.AI_PROVIDER == ai_provider
                assert settings.EMBEDDING_PROVIDER == embedding_provider
    
    def test_encryption_key_hex_validation(self):
        """Test encryption key accepts valid hex characters"""
        # Test with valid hex characters
        valid_hex_key = '0123456789abcdefABCDEF' + '0' * 42  # 64 characters total
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': valid_hex_key,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            assert settings.ENCRYPTION_KEY == valid_hex_key
    
    def test_default_values_when_optional_vars_missing(self):
        """Test default values are used when optional environment variables are missing"""
        # Only provide required variables
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'a' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            
            # Verify all defaults are applied
            assert settings.DEBUG is False
            assert settings.APP_URL == "http://localhost:8000"
            assert settings.ALLOWED_ORIGINS == [
                "http://localhost:3000",
                "http://localhost:5173",
                "http://localhost:8080",
                "https://chatsaas.vercel.app",
            ]
            assert settings.DATABASE_URL == "postgresql+asyncpg://postgres:password@localhost:5432/chatsaas"
            assert settings.JWT_ALGORITHM == "HS256"
            assert settings.JWT_EXPIRE_MINUTES == 10080
            assert settings.AI_PROVIDER == "google"
            assert settings.EMBEDDING_PROVIDER == "google"
            assert settings.GOOGLE_API_KEY == ""
            assert settings.OPENAI_API_KEY == ""
            assert settings.GROQ_API_KEY == ""
            assert settings.TELEGRAM_SECRET_TOKEN == ""
            assert settings.WHATSAPP_APP_SECRET == ""
            assert settings.INSTAGRAM_APP_SECRET == ""
            assert settings.RESEND_API_KEY == ""
            assert settings.RESEND_FROM_EMAIL == "alerts@yourdomain.com"
            assert settings.STORAGE_PATH == "/var/chatsaas/storage"
            assert settings.SUPER_ADMIN_EMAIL == "admin@yourdomain.com"


class TestConfigurationIntegration:
    """Test configuration integration with application components"""
    
    def test_settings_instance_creation(self):
        """Test global settings instance can be created successfully"""
        from app.config import settings
        
        # Verify settings instance exists and has expected attributes
        assert hasattr(settings, 'JWT_SECRET_KEY')
        assert hasattr(settings, 'DATABASE_URL')
        assert hasattr(settings, 'ENCRYPTION_KEY')
        assert hasattr(settings, 'AI_PROVIDER')
        assert hasattr(settings, 'EMBEDDING_PROVIDER')
    
    def test_settings_case_sensitivity(self):
        """Test environment variables are case sensitive"""
        env_vars = {
            'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
            'ENCRYPTION_KEY': 'e' * 64,
            'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
            'debug': 'true',  # lowercase should not be recognized
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            settings = Settings()
            
            # DEBUG should be default (False) since 'debug' (lowercase) is not recognized
            assert settings.DEBUG is False
    
    def test_settings_with_postgresql_database_requirement(self):
        """Test database URL validation supports PostgreSQL as required"""
        postgresql_urls = [
            'postgresql+asyncpg://user:pass@localhost:5432/db',
            'postgresql://user:pass@localhost:5432/db',
            'postgres://user:pass@localhost:5432/db',
        ]
        
        for db_url in postgresql_urls:
            env_vars = {
                'JWT_SECRET_KEY': 'test_jwt_secret_key_minimum_32_characters_long',
                'ENCRYPTION_KEY': 'f' * 64,
                'PROCESS_SECRET': 'test_process_secret_minimum_32_chars',
                'DATABASE_URL': db_url,
            }
            
            with patch.dict(os.environ, env_vars, clear=True):
                settings = Settings()
                assert settings.DATABASE_URL == db_url
                # Verify it contains postgresql (requirement 14.1)
                assert 'postgres' in settings.DATABASE_URL.lower()