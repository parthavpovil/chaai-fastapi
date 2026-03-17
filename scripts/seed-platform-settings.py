#!/usr/bin/env python3
"""
Enhanced Platform Settings Seeding Script
Seeds comprehensive platform settings for production deployment with validation and rollback capabilities.
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import get_async_session
from app.models.platform_setting import PlatformSetting
from app.config import settings


class PlatformSettingsSeeder:
    """Enhanced platform settings seeder with validation and rollback"""
    
    def __init__(self):
        self.seeded_settings = []
        self.backup_settings = {}
        
    def get_default_settings(self) -> Dict[str, Any]:
        """Get comprehensive default platform settings"""
        return {
            # Core System Settings
            "maintenance_mode": {
                "value": "false",
                "description": "Enable/disable maintenance mode",
                "type": "boolean",
                "required": True
            },
            "maintenance_message": {
                "value": "System is currently under maintenance. Please try again later.",
                "description": "Message shown during maintenance mode",
                "type": "string",
                "required": True
            },
            "system_version": {
                "value": "1.0.0",
                "description": "Current system version",
                "type": "string",
                "required": True
            },
            
            # File and Storage Settings
            "max_file_size_mb": {
                "value": "10",
                "description": "Maximum file upload size in MB",
                "type": "integer",
                "required": True
            },
            "max_documents_per_workspace": {
                "value": "100",
                "description": "Maximum documents per workspace (pro tier)",
                "type": "integer",
                "required": True
            },
            "storage_cleanup_enabled": {
                "value": "true",
                "description": "Enable automatic cleanup of orphaned files",
                "type": "boolean",
                "required": False
            },
            "storage_cleanup_days": {
                "value": "30",
                "description": "Days to keep orphaned files before cleanup",
                "type": "integer",
                "required": False
            },
            
            # Rate Limiting Settings
            "rate_limit_per_minute": {
                "value": "10",
                "description": "Rate limit for WebChat messages per minute",
                "type": "integer",
                "required": True
            },
            "rate_limit_burst": {
                "value": "20",
                "description": "Burst limit for rate limiting",
                "type": "integer",
                "required": False
            },
            "rate_limit_window_minutes": {
                "value": "1",
                "description": "Rate limit window in minutes",
                "type": "integer",
                "required": False
            },
            
            # Email and Notification Settings
            "email_notifications_enabled": {
                "value": "true",
                "description": "Enable email notifications system-wide",
                "type": "boolean",
                "required": True
            },
            "escalation_email_enabled": {
                "value": "true",
                "description": "Enable escalation email alerts",
                "type": "boolean",
                "required": True
            },
            "agent_invitation_email_enabled": {
                "value": "true",
                "description": "Enable agent invitation emails",
                "type": "boolean",
                "required": True
            },
            "email_retry_attempts": {
                "value": "3",
                "description": "Number of email delivery retry attempts",
                "type": "integer",
                "required": False
            },
            
            # WebSocket and Real-time Settings
            "websocket_max_connections": {
                "value": "1000",
                "description": "Maximum concurrent WebSocket connections",
                "type": "integer",
                "required": True
            },
            "websocket_heartbeat_interval": {
                "value": "30",
                "description": "WebSocket heartbeat interval in seconds",
                "type": "integer",
                "required": False
            },
            "websocket_timeout_seconds": {
                "value": "300",
                "description": "WebSocket connection timeout in seconds",
                "type": "integer",
                "required": False
            },
            
            # AI Provider Settings
            "ai_provider_timeout_seconds": {
                "value": "30",
                "description": "Timeout for AI provider API calls",
                "type": "integer",
                "required": False
            },
            "ai_provider_retry_attempts": {
                "value": "2",
                "description": "Number of retry attempts for AI provider failures",
                "type": "integer",
                "required": False
            },
            "ai_response_max_tokens": {
                "value": "1000",
                "description": "Maximum tokens for AI responses",
                "type": "integer",
                "required": False
            },
            "rag_similarity_threshold": {
                "value": "0.75",
                "description": "Similarity threshold for RAG document search",
                "type": "float",
                "required": False
            },
            "rag_max_chunks": {
                "value": "5",
                "description": "Maximum document chunks to use for RAG",
                "type": "integer",
                "required": False
            },
            
            # Security Settings
            "jwt_expiry_days": {
                "value": "7",
                "description": "JWT token expiry in days",
                "type": "integer",
                "required": False
            },
            "password_min_length": {
                "value": "8",
                "description": "Minimum password length",
                "type": "integer",
                "required": False
            },
            "session_timeout_minutes": {
                "value": "480",
                "description": "Session timeout in minutes (8 hours)",
                "type": "integer",
                "required": False
            },
            
            # Monitoring and Logging Settings
            "log_level": {
                "value": "INFO",
                "description": "Application log level",
                "type": "string",
                "required": False
            },
            "metrics_enabled": {
                "value": "true",
                "description": "Enable application metrics collection",
                "type": "boolean",
                "required": False
            },
            "health_check_enabled": {
                "value": "true",
                "description": "Enable health check endpoints",
                "type": "boolean",
                "required": True
            },
            
            # Backup and Maintenance Settings
            "backup_retention_days": {
                "value": "30",
                "description": "Database backup retention in days",
                "type": "integer",
                "required": False
            },
            "auto_vacuum_enabled": {
                "value": "true",
                "description": "Enable automatic database vacuum",
                "type": "boolean",
                "required": False
            },
            "maintenance_window_start": {
                "value": "02:00",
                "description": "Maintenance window start time (HH:MM)",
                "type": "string",
                "required": False
            },
            "maintenance_window_end": {
                "value": "04:00",
                "description": "Maintenance window end time (HH:MM)",
                "type": "string",
                "required": False
            },
            
            # Feature Flags
            "feature_agent_management": {
                "value": "true",
                "description": "Enable agent management features",
                "type": "boolean",
                "required": False
            },
            "feature_document_processing": {
                "value": "true",
                "description": "Enable document processing features",
                "type": "boolean",
                "required": False
            },
            "feature_analytics": {
                "value": "true",
                "description": "Enable analytics and reporting",
                "type": "boolean",
                "required": False
            },
            "feature_multi_channel": {
                "value": "true",
                "description": "Enable multi-channel support",
                "type": "boolean",
                "required": False
            }
        }
    
    async def backup_existing_settings(self):
        """Backup existing settings before seeding"""
        print("📦 Backing up existing platform settings...")
        
        async with get_async_session() as session:
            result = await session.execute(
                text("SELECT key, value FROM platform_settings")
            )
            existing_settings = result.fetchall()
            
            for key, value in existing_settings:
                self.backup_settings[key] = value
            
            print(f"✅ Backed up {len(self.backup_settings)} existing settings")
    
    def validate_setting_value(self, key: str, config: Dict[str, Any]) -> bool:
        """Validate setting value based on type"""
        value = config["value"]
        setting_type = config.get("type", "string")
        
        try:
            if setting_type == "boolean":
                return value.lower() in ["true", "false"]
            elif setting_type == "integer":
                int(value)
                return True
            elif setting_type == "float":
                float(value)
                return True
            elif setting_type == "string":
                return isinstance(value, str) and len(value) > 0
            else:
                return True
        except (ValueError, AttributeError):
            print(f"⚠️  Invalid value for {key}: {value} (expected {setting_type})")
            return False
    
    async def seed_settings(self, force_update: bool = False):
        """Seed platform settings with validation"""
        print("🌱 Seeding platform settings...")
        
        default_settings = self.get_default_settings()
        created_count = 0
        updated_count = 0
        skipped_count = 0
        
        async with get_async_session() as session:
            for key, config in default_settings.items():
                # Validate setting value
                if not self.validate_setting_value(key, config):
                    print(f"❌ Skipping invalid setting: {key}")
                    skipped_count += 1
                    continue
                
                # Check if setting already exists
                existing = await session.get(PlatformSetting, key)
                
                if existing:
                    if force_update:
                        old_value = existing.value
                        existing.value = config["value"]
                        print(f"  🔄 Updated: {key} = {config['value']} (was: {old_value})")
                        updated_count += 1
                        self.seeded_settings.append(key)
                    else:
                        print(f"  ⏭️  Exists: {key} = {existing.value}")
                        skipped_count += 1
                else:
                    setting = PlatformSetting(key=key, value=config["value"])
                    session.add(setting)
                    print(f"  ➕ Created: {key} = {config['value']}")
                    created_count += 1
                    self.seeded_settings.append(key)
            
            await session.commit()
        
        print(f"\n✅ Platform settings seeding completed:")
        print(f"   Created: {created_count}")
        print(f"   Updated: {updated_count}")
        print(f"   Skipped: {skipped_count}")
        
        return created_count + updated_count > 0
    
    async def validate_seeded_settings(self):
        """Validate that seeded settings are correctly stored"""
        print("🔍 Validating seeded settings...")
        
        validation_errors = []
        default_settings = self.get_default_settings()
        
        async with get_async_session() as session:
            for key in self.seeded_settings:
                setting = await session.get(PlatformSetting, key)
                if not setting:
                    validation_errors.append(f"Setting not found: {key}")
                    continue
                
                expected_value = default_settings[key]["value"]
                if setting.value != expected_value:
                    validation_errors.append(f"Value mismatch for {key}: got {setting.value}, expected {expected_value}")
        
        if validation_errors:
            print("❌ Validation errors found:")
            for error in validation_errors:
                print(f"   - {error}")
            return False
        else:
            print(f"✅ All {len(self.seeded_settings)} seeded settings validated successfully")
            return True
    
    async def rollback_settings(self):
        """Rollback settings to backup state"""
        print("🔄 Rolling back platform settings...")
        
        rollback_count = 0
        
        async with get_async_session() as session:
            # Remove newly created settings
            for key in self.seeded_settings:
                if key not in self.backup_settings:
                    setting = await session.get(PlatformSetting, key)
                    if setting:
                        await session.delete(setting)
                        print(f"  ➖ Removed: {key}")
                        rollback_count += 1
            
            # Restore backed up settings
            for key, value in self.backup_settings.items():
                setting = await session.get(PlatformSetting, key)
                if setting and setting.value != value:
                    setting.value = value
                    print(f"  🔄 Restored: {key} = {value}")
                    rollback_count += 1
            
            await session.commit()
        
        print(f"✅ Rollback completed: {rollback_count} settings affected")
    
    async def export_settings(self, file_path: str):
        """Export current settings to JSON file"""
        print(f"📤 Exporting settings to {file_path}...")
        
        async with get_async_session() as session:
            result = await session.execute(
                text("SELECT key, value, updated_at FROM platform_settings ORDER BY key")
            )
            settings_data = []
            
            for key, value, updated_at in result.fetchall():
                settings_data.append({
                    "key": key,
                    "value": value,
                    "updated_at": updated_at.isoformat() if updated_at else None
                })
        
        export_data = {
            "exported_at": datetime.now().isoformat(),
            "total_settings": len(settings_data),
            "settings": settings_data
        }
        
        with open(file_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✅ Exported {len(settings_data)} settings to {file_path}")
    
    async def import_settings(self, file_path: str, force_update: bool = False):
        """Import settings from JSON file"""
        print(f"📥 Importing settings from {file_path}...")
        
        try:
            with open(file_path, 'r') as f:
                import_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"❌ Failed to read import file: {e}")
            return False
        
        settings_data = import_data.get("settings", [])
        imported_count = 0
        
        async with get_async_session() as session:
            for setting_data in settings_data:
                key = setting_data["key"]
                value = setting_data["value"]
                
                existing = await session.get(PlatformSetting, key)
                
                if existing:
                    if force_update:
                        existing.value = value
                        print(f"  🔄 Updated: {key} = {value}")
                        imported_count += 1
                    else:
                        print(f"  ⏭️  Skipped existing: {key}")
                else:
                    setting = PlatformSetting(key=key, value=value)
                    session.add(setting)
                    print(f"  ➕ Created: {key} = {value}")
                    imported_count += 1
            
            await session.commit()
        
        print(f"✅ Imported {imported_count} settings from {file_path}")
        return imported_count > 0


async def main():
    """Main seeding function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Platform Settings Seeder")
    parser.add_argument("--force", action="store_true", help="Force update existing settings")
    parser.add_argument("--validate-only", action="store_true", help="Only validate existing settings")
    parser.add_argument("--export", type=str, help="Export settings to JSON file")
    parser.add_argument("--import", type=str, dest="import_file", help="Import settings from JSON file")
    parser.add_argument("--rollback", action="store_true", help="Rollback to backup (use with caution)")
    
    args = parser.parse_args()
    
    seeder = PlatformSettingsSeeder()
    
    print("=" * 70)
    print("ChatSaaS Backend - Enhanced Platform Settings Seeder")
    print("=" * 70)
    
    try:
        # Export settings
        if args.export:
            await seeder.export_settings(args.export)
            return
        
        # Import settings
        if args.import_file:
            await seeder.import_settings(args.import_file, args.force)
            return
        
        # Backup existing settings
        await seeder.backup_existing_settings()
        
        # Validate only mode
        if args.validate_only:
            default_settings = seeder.get_default_settings()
            print(f"🔍 Validating {len(default_settings)} default settings...")
            
            validation_errors = []
            for key, config in default_settings.items():
                if not seeder.validate_setting_value(key, config):
                    validation_errors.append(key)
            
            if validation_errors:
                print(f"❌ Found {len(validation_errors)} validation errors")
                return False
            else:
                print("✅ All default settings are valid")
                return True
        
        # Rollback mode
        if args.rollback:
            if not seeder.backup_settings:
                print("❌ No backup found for rollback")
                return False
            
            confirm = input("⚠️  This will rollback settings to backup state. Continue? (yes/no): ")
            if confirm.lower() != "yes":
                print("Rollback cancelled")
                return False
            
            await seeder.rollback_settings()
            return True
        
        # Normal seeding
        success = await seeder.seed_settings(args.force)
        
        if success:
            # Validate seeded settings
            if not await seeder.validate_seeded_settings():
                print("\n⚠️  Validation failed. Consider rolling back.")
                return False
        
        print("\n🎉 Platform settings seeding completed successfully!")
        print("\nSeeded settings include:")
        print("• System maintenance and version settings")
        print("• File storage and document limits")
        print("• Rate limiting and security settings")
        print("• Email and notification preferences")
        print("• WebSocket and real-time configuration")
        print("• AI provider and RAG settings")
        print("• Monitoring and logging configuration")
        print("• Feature flags and toggles")
        
        return True
        
    except Exception as e:
        print(f"❌ Seeding failed: {e}")
        
        # Attempt rollback on failure
        if seeder.backup_settings and seeder.seeded_settings:
            print("🔄 Attempting automatic rollback...")
            try:
                await seeder.rollback_settings()
                print("✅ Rollback completed")
            except Exception as rollback_error:
                print(f"❌ Rollback failed: {rollback_error}")
        
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)