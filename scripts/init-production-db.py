#!/usr/bin/env python3
"""
Enhanced Production Database Initialization Script
Comprehensive database setup with extensions, migrations, seeding, and validation.
"""
import asyncio
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import get_async_session, engine
from app.models.platform_setting import PlatformSetting
from app.config import settings


class ProductionDatabaseInitializer:
    """Enhanced production database initialization with comprehensive setup"""
    
    def __init__(self):
        self.initialization_log = []
        self.errors = []
        
    def log_step(self, message: str, success: bool = True):
        """Log initialization step"""
        timestamp = datetime.now().isoformat()
        status = "✅" if success else "❌"
        log_entry = f"{status} {timestamp}: {message}"
        print(log_entry)
        self.initialization_log.append({
            "timestamp": timestamp,
            "message": message,
            "success": success
        })
        
        if not success:
            self.errors.append(message)
    
    async def check_database_connection(self) -> bool:
        """Check database connectivity"""
        self.log_step("Checking database connection...")
        
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT version()"))
                version = result.scalar()
                self.log_step(f"Connected to PostgreSQL: {version}")
                return True
        except Exception as e:
            self.log_step(f"Database connection failed: {e}", False)
            return False
    
    async def check_database_permissions(self) -> bool:
        """Check database permissions"""
        self.log_step("Checking database permissions...")
        
        try:
            async with engine.begin() as conn:
                # Test table creation
                await conn.execute(text("CREATE TABLE IF NOT EXISTS _permission_test (id INTEGER)"))
                await conn.execute(text("DROP TABLE _permission_test"))
                
                # Test extension creation
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                
                self.log_step("Database permissions verified")
                return True
        except Exception as e:
            self.log_step(f"Insufficient database permissions: {e}", False)
            return False
    
    async def initialize_extensions(self) -> bool:
        """Initialize required PostgreSQL extensions"""
        self.log_step("Initializing PostgreSQL extensions...")
        
        extensions = [
            ("vector", "pgvector for vector similarity search"),
            ("uuid-ossp", "UUID generation functions"),
            ("pg_trgm", "Trigram matching for text search")
        ]
        
        try:
            async with engine.begin() as conn:
                for ext_name, description in extensions:
                    try:
                        await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS \"{ext_name}\""))
                        self.log_step(f"Extension '{ext_name}' initialized: {description}")
                    except Exception as e:
                        # Some extensions might not be available, log but continue
                        self.log_step(f"Extension '{ext_name}' failed (optional): {e}", False)
                
                # Verify critical extensions
                result = await conn.execute(text("""
                    SELECT extname FROM pg_extension 
                    WHERE extname IN ('vector', 'uuid-ossp')
                """))
                installed_extensions = [row[0] for row in result.fetchall()]
                
                if 'vector' not in installed_extensions:
                    self.log_step("Critical extension 'vector' not available", False)
                    return False
                
                self.log_step(f"Extensions initialized: {', '.join(installed_extensions)}")
                return True
                
        except Exception as e:
            self.log_step(f"Extension initialization failed: {e}", False)
            return False
    
    async def run_database_migrations(self) -> bool:
        """Run Alembic database migrations"""
        self.log_step("Running database migrations...")
        
        try:
            # Check if alembic is available
            result = subprocess.run(
                ["alembic", "--version"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                self.log_step("Alembic not available", False)
                return False
            
            # Run migrations
            result = subprocess.run(
                ["alembic", "upgrade", "head"],
                cwd=backend_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                self.log_step("Database migrations completed successfully")
                self.log_step(f"Migration output: {result.stdout}")
                return True
            else:
                self.log_step(f"Migration failed: {result.stderr}", False)
                return False
                
        except subprocess.TimeoutExpired:
            self.log_step("Migration timed out after 5 minutes", False)
            return False
        except Exception as e:
            self.log_step(f"Migration error: {e}", False)
            return False
    
    async def verify_database_schema(self) -> bool:
        """Verify database schema is correctly created"""
        self.log_step("Verifying database schema...")
        
        expected_tables = [
            "users", "workspaces", "channels", "contacts", "agents",
            "conversations", "messages", "documents", "document_chunks",
            "usage_counters", "platform_settings", "tier_changes", "rate_limits"
        ]
        
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """))
                
                existing_tables = [row[0] for row in result.fetchall()]
                missing_tables = set(expected_tables) - set(existing_tables)
                
                if missing_tables:
                    self.log_step(f"Missing tables: {', '.join(missing_tables)}", False)
                    return False
                
                self.log_step(f"Schema verified: {len(existing_tables)} tables found")
                
                # Verify critical indexes
                result = await conn.execute(text("""
                    SELECT indexname 
                    FROM pg_indexes 
                    WHERE schemaname = 'public' 
                    AND indexname LIKE '%embedding%'
                """))
                
                embedding_indexes = [row[0] for row in result.fetchall()]
                if not embedding_indexes:
                    self.log_step("Warning: No embedding indexes found", False)
                else:
                    self.log_step(f"Vector indexes found: {', '.join(embedding_indexes)}")
                
                return True
                
        except Exception as e:
            self.log_step(f"Schema verification failed: {e}", False)
            return False
    
    async def seed_platform_settings(self) -> bool:
        """Seed comprehensive platform settings"""
        self.log_step("Seeding platform settings...")
        
        try:
            # Use the enhanced seeder
            from seed_platform_settings import PlatformSettingsSeeder
            
            seeder = PlatformSettingsSeeder()
            await seeder.backup_existing_settings()
            success = await seeder.seed_settings(force_update=False)
            
            if success:
                # Validate seeded settings
                if await seeder.validate_seeded_settings():
                    self.log_step("Platform settings seeded and validated successfully")
                    return True
                else:
                    self.log_step("Platform settings validation failed", False)
                    return False
            else:
                self.log_step("No new platform settings were seeded")
                return True
                
        except ImportError:
            # Fallback to basic seeding if enhanced seeder not available
            self.log_step("Using basic platform settings seeding...")
            return await self._basic_seed_settings()
        except Exception as e:
            self.log_step(f"Platform settings seeding failed: {e}", False)
            return False
    
    async def _basic_seed_settings(self) -> bool:
        """Basic platform settings seeding fallback"""
        default_settings = {
            "maintenance_mode": "false",
            "maintenance_message": "System is currently under maintenance. Please try again later.",
            "max_file_size_mb": "10",
            "max_documents_per_workspace": "100",
            "rate_limit_per_minute": "10",
            "system_version": "1.0.0",
            "email_notifications_enabled": "true",
            "websocket_max_connections": "1000"
        }
        
        try:
            async with get_async_session() as session:
                seeded_count = 0
                for key, value in default_settings.items():
                    existing = await session.get(PlatformSetting, key)
                    if not existing:
                        setting = PlatformSetting(key=key, value=value)
                        session.add(setting)
                        seeded_count += 1
                
                await session.commit()
                self.log_step(f"Basic platform settings seeded: {seeded_count} new settings")
                return True
                
        except Exception as e:
            self.log_step(f"Basic settings seeding failed: {e}", False)
            return False
    
    async def create_initial_indexes(self) -> bool:
        """Create additional performance indexes"""
        self.log_step("Creating performance indexes...")
        
        indexes = [
            ("idx_messages_created_at", "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)"),
            ("idx_conversations_updated_at", "CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at)"),
            ("idx_documents_workspace_status", "CREATE INDEX IF NOT EXISTS idx_documents_workspace_status ON documents(workspace_id, status)"),
            ("idx_usage_counters_month", "CREATE INDEX IF NOT EXISTS idx_usage_counters_month ON usage_counters(month)")
        ]
        
        try:
            async with engine.begin() as conn:
                for index_name, index_sql in indexes:
                    try:
                        await conn.execute(text(index_sql))
                        self.log_step(f"Index created: {index_name}")
                    except Exception as e:
                        self.log_step(f"Index creation failed for {index_name}: {e}", False)
                
                return True
                
        except Exception as e:
            self.log_step(f"Index creation failed: {e}", False)
            return False
    
    async def validate_configuration(self) -> bool:
        """Validate production configuration"""
        self.log_step("Validating production configuration...")
        
        validation_errors = []
        
        # Check required environment variables
        required_vars = [
            "DATABASE_URL", "JWT_SECRET_KEY", "ENCRYPTION_KEY",
            "RESEND_API_KEY", "SUPER_ADMIN_EMAIL"
        ]
        
        for var in required_vars:
            if not getattr(settings, var, None):
                validation_errors.append(f"Missing required environment variable: {var}")
        
        # Check AI provider configuration
        ai_providers = ["GOOGLE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"]
        if not any(getattr(settings, var, None) for var in ai_providers):
            validation_errors.append("At least one AI provider API key must be configured")
        
        if validation_errors:
            for error in validation_errors:
                self.log_step(error, False)
            return False
        
        self.log_step("Production configuration validated")
        return True
    
    async def run_health_checks(self) -> bool:
        """Run post-initialization health checks"""
        self.log_step("Running health checks...")
        
        try:
            # Test database queries
            async with get_async_session() as session:
                # Test platform settings
                result = await session.execute(text("SELECT COUNT(*) FROM platform_settings"))
                settings_count = result.scalar()
                self.log_step(f"Platform settings count: {settings_count}")
                
                # Test vector extension
                result = await session.execute(text("SELECT vector_dims(ARRAY[1,2,3]::vector)"))
                vector_test = result.scalar()
                if vector_test == 3:
                    self.log_step("Vector extension working correctly")
                else:
                    self.log_step("Vector extension test failed", False)
                    return False
                
                return True
                
        except Exception as e:
            self.log_step(f"Health checks failed: {e}", False)
            return False
    
    def save_initialization_log(self):
        """Save initialization log to file"""
        log_file = backend_dir / "logs" / f"db_init_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        log_file.parent.mkdir(exist_ok=True)
        
        log_data = {
            "initialization_time": datetime.now().isoformat(),
            "success": len(self.errors) == 0,
            "total_steps": len(self.initialization_log),
            "errors": self.errors,
            "log": self.initialization_log
        }
        
        try:
            with open(log_file, 'w') as f:
                json.dump(log_data, f, indent=2)
            print(f"📝 Initialization log saved: {log_file}")
        except Exception as e:
            print(f"⚠️  Could not save log: {e}")
    
    async def initialize(self) -> bool:
        """Run complete database initialization"""
        print("=" * 70)
        print("ChatSaaS Backend - Enhanced Production Database Initialization")
        print("=" * 70)
        
        steps = [
            ("Database Connection", self.check_database_connection),
            ("Database Permissions", self.check_database_permissions),
            ("PostgreSQL Extensions", self.initialize_extensions),
            ("Database Migrations", self.run_database_migrations),
            ("Schema Verification", self.verify_database_schema),
            ("Platform Settings", self.seed_platform_settings),
            ("Performance Indexes", self.create_initial_indexes),
            ("Configuration Validation", self.validate_configuration),
            ("Health Checks", self.run_health_checks)
        ]
        
        for step_name, step_func in steps:
            self.log_step(f"Starting: {step_name}")
            
            try:
                success = await step_func()
                if not success:
                    self.log_step(f"Failed: {step_name}", False)
                    break
            except Exception as e:
                self.log_step(f"Exception in {step_name}: {e}", False)
                break
        
        # Save initialization log
        self.save_initialization_log()
        
        # Summary
        if self.errors:
            print(f"\n❌ Initialization completed with {len(self.errors)} errors:")
            for error in self.errors:
                print(f"   • {error}")
            return False
        else:
            print("\n🎉 Production database initialization completed successfully!")
            print("\nInitialized components:")
            print("• PostgreSQL extensions (pgvector, uuid-ossp)")
            print("• Database schema with all tables and indexes")
            print("• Comprehensive platform settings")
            print("• Performance optimization indexes")
            print("• Configuration validation")
            print("• Health check verification")
            print("\nNext steps:")
            print("1. Start the application server")
            print("2. Run application health checks")
            print("3. Configure monitoring and alerting")
            print("4. Set up backup procedures")
            return True


async def main():
    """Main initialization function"""
    initializer = ProductionDatabaseInitializer()
    
    try:
        success = await initializer.initialize()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⚠️  Initialization interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error during initialization: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())