#!/usr/bin/env python3
"""
Database Migration Manager
Advanced migration management for production deployments with safety checks and rollback capabilities.
"""
import asyncio
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import engine
from app.config import settings


class MigrationManager:
    """Advanced database migration management"""
    
    def __init__(self):
        self.alembic_dir = backend_dir / "alembic"
        self.versions_dir = self.alembic_dir / "versions"
        
    async def get_current_revision(self) -> Optional[str]:
        """Get current database revision"""
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            print(f"⚠️  Could not get current revision: {e}")
            return None
    
    def get_available_revisions(self) -> List[Dict[str, str]]:
        """Get list of available migration revisions"""
        revisions = []
        
        if not self.versions_dir.exists():
            return revisions
        
        for file_path in self.versions_dir.glob("*.py"):
            if file_path.name == "__init__.py":
                continue
            
            # Parse revision info from filename and content
            filename = file_path.name
            if "_" in filename:
                revision_id = filename.split("_")[0]
                
                # Read migration file to get description
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                        
                    # Extract docstring description
                    description = "No description"
                    if '"""' in content:
                        start = content.find('"""') + 3
                        end = content.find('"""', start)
                        if end > start:
                            description = content[start:end].strip().split('\n')[0]
                    
                    revisions.append({
                        "revision": revision_id,
                        "description": description,
                        "filename": filename,
                        "path": str(file_path)
                    })
                except Exception as e:
                    print(f"⚠️  Could not parse {filename}: {e}")
        
        # Sort by filename (which includes timestamp)
        revisions.sort(key=lambda x: x["filename"])
        return revisions
    
    async def check_database_connection(self) -> bool:
        """Check if database is accessible"""
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False
    
    async def create_migration_backup(self) -> Optional[str]:
        """Create a backup before running migrations"""
        print("📦 Creating pre-migration backup...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"pre_migration_backup_{timestamp}.sql"
        backup_path = backend_dir / "backups" / backup_file
        
        # Create backups directory
        backup_path.parent.mkdir(exist_ok=True)
        
        try:
            # Use pg_dump to create backup
            db_url = str(settings.DATABASE_URL)
            if "postgresql+asyncpg://" in db_url:
                db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
            
            result = subprocess.run([
                "pg_dump",
                db_url,
                "--format=custom",
                "--compress=9",
                f"--file={backup_path}"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Backup created: {backup_path}")
                return str(backup_path)
            else:
                print(f"❌ Backup failed: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Backup error: {e}")
            return None
    
    def run_alembic_command(self, command: List[str]) -> Tuple[bool, str, str]:
        """Run alembic command and return success, stdout, stderr"""
        try:
            result = subprocess.run(
                ["alembic"] + command,
                cwd=backend_dir,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            return result.returncode == 0, result.stdout, result.stderr
            
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out after 5 minutes"
        except Exception as e:
            return False, "", str(e)
    
    async def get_migration_history(self) -> List[Dict[str, str]]:
        """Get migration history from database"""
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("""
                    SELECT version_num 
                    FROM alembic_version 
                    ORDER BY version_num
                """))
                
                applied_revisions = [row[0] for row in result.fetchall()]
                
                # Get available revisions for context
                available_revisions = self.get_available_revisions()
                revision_map = {r["revision"]: r for r in available_revisions}
                
                history = []
                for revision in applied_revisions:
                    if revision in revision_map:
                        history.append(revision_map[revision])
                    else:
                        history.append({
                            "revision": revision,
                            "description": "Unknown migration",
                            "filename": f"{revision}_unknown.py",
                            "path": "Unknown"
                        })
                
                return history
                
        except Exception as e:
            print(f"⚠️  Could not get migration history: {e}")
            return []
    
    async def validate_migration_state(self) -> bool:
        """Validate current migration state"""
        print("🔍 Validating migration state...")
        
        # Check database connection
        if not await self.check_database_connection():
            return False
        
        # Get current revision
        current_revision = await self.get_current_revision()
        if not current_revision:
            print("⚠️  No current revision found - database may not be initialized")
            return False
        
        # Check if revision exists in available migrations
        available_revisions = self.get_available_revisions()
        revision_ids = [r["revision"] for r in available_revisions]
        
        if current_revision not in revision_ids:
            print(f"⚠️  Current revision {current_revision} not found in available migrations")
            return False
        
        print(f"✅ Migration state valid - current revision: {current_revision}")
        return True
    
    async def upgrade_database(self, target_revision: str = "head", create_backup: bool = True) -> bool:
        """Upgrade database to target revision"""
        print(f"🚀 Upgrading database to {target_revision}...")
        
        # Validate current state
        if not await self.validate_migration_state():
            print("❌ Migration state validation failed")
            return False
        
        # Create backup if requested
        backup_path = None
        if create_backup:
            backup_path = await self.create_migration_backup()
            if not backup_path:
                print("❌ Failed to create backup - aborting migration")
                return False
        
        # Run migration
        success, stdout, stderr = self.run_alembic_command(["upgrade", target_revision])
        
        if success:
            print("✅ Database upgrade completed successfully")
            print(f"Output: {stdout}")
            
            # Verify new revision
            new_revision = await self.get_current_revision()
            print(f"New revision: {new_revision}")
            
            return True
        else:
            print("❌ Database upgrade failed")
            print(f"Error: {stderr}")
            
            if backup_path:
                print(f"💡 Backup available for rollback: {backup_path}")
            
            return False
    
    async def downgrade_database(self, target_revision: str, create_backup: bool = True) -> bool:
        """Downgrade database to target revision"""
        print(f"⬇️  Downgrading database to {target_revision}...")
        
        # Validate current state
        if not await self.validate_migration_state():
            print("❌ Migration state validation failed")
            return False
        
        # Create backup if requested
        backup_path = None
        if create_backup:
            backup_path = await self.create_migration_backup()
            if not backup_path:
                print("❌ Failed to create backup - aborting downgrade")
                return False
        
        # Confirm downgrade
        current_revision = await self.get_current_revision()
        print(f"⚠️  This will downgrade from {current_revision} to {target_revision}")
        confirm = input("Are you sure you want to continue? (yes/no): ")
        
        if confirm.lower() != "yes":
            print("Downgrade cancelled")
            return False
        
        # Run downgrade
        success, stdout, stderr = self.run_alembic_command(["downgrade", target_revision])
        
        if success:
            print("✅ Database downgrade completed successfully")
            print(f"Output: {stdout}")
            
            # Verify new revision
            new_revision = await self.get_current_revision()
            print(f"New revision: {new_revision}")
            
            return True
        else:
            print("❌ Database downgrade failed")
            print(f"Error: {stderr}")
            
            if backup_path:
                print(f"💡 Backup available for recovery: {backup_path}")
            
            return False
    
    def generate_migration(self, message: str, auto_generate: bool = True) -> bool:
        """Generate new migration"""
        print(f"📝 Generating migration: {message}")
        
        command = ["revision"]
        if auto_generate:
            command.append("--autogenerate")
        command.extend(["-m", message])
        
        success, stdout, stderr = self.run_alembic_command(command)
        
        if success:
            print("✅ Migration generated successfully")
            print(f"Output: {stdout}")
            return True
        else:
            print("❌ Migration generation failed")
            print(f"Error: {stderr}")
            return False
    
    async def show_migration_status(self):
        """Show detailed migration status"""
        print("📊 Migration Status Report")
        print("=" * 50)
        
        # Current revision
        current_revision = await self.get_current_revision()
        print(f"Current revision: {current_revision or 'None'}")
        
        # Available revisions
        available_revisions = self.get_available_revisions()
        print(f"Available migrations: {len(available_revisions)}")
        
        # Migration history
        history = await self.get_migration_history()
        print(f"Applied migrations: {len(history)}")
        
        print("\nAvailable Migrations:")
        print("-" * 30)
        for revision in available_revisions:
            status = "✅ Applied" if revision["revision"] == current_revision else "⏳ Pending"
            print(f"{revision['revision'][:8]} - {revision['description']} ({status})")
        
        # Check for pending migrations
        if available_revisions:
            latest_available = available_revisions[-1]["revision"]
            if current_revision != latest_available:
                print(f"\n⚠️  Pending migrations detected!")
                print(f"Current: {current_revision}")
                print(f"Latest: {latest_available}")
            else:
                print(f"\n✅ Database is up to date")
    
    async def dry_run_migration(self, target_revision: str = "head") -> bool:
        """Perform dry run of migration"""
        print(f"🧪 Dry run migration to {target_revision}...")
        
        # Use alembic's SQL generation for dry run
        success, stdout, stderr = self.run_alembic_command([
            "upgrade", target_revision, "--sql"
        ])
        
        if success:
            print("✅ Dry run completed - SQL preview:")
            print("-" * 50)
            print(stdout)
            print("-" * 50)
            return True
        else:
            print("❌ Dry run failed")
            print(f"Error: {stderr}")
            return False


async def main():
    """Main migration management function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database Migration Manager")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--upgrade", type=str, nargs="?", const="head", help="Upgrade to revision (default: head)")
    parser.add_argument("--downgrade", type=str, help="Downgrade to revision")
    parser.add_argument("--generate", type=str, help="Generate new migration with message")
    parser.add_argument("--dry-run", type=str, nargs="?", const="head", help="Dry run migration")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup creation")
    parser.add_argument("--validate", action="store_true", help="Validate migration state")
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    manager = MigrationManager()
    
    print("🔧 ChatSaaS Database Migration Manager")
    print("=" * 50)
    
    try:
        if args.status:
            await manager.show_migration_status()
        
        elif args.validate:
            success = await manager.validate_migration_state()
            return success
        
        elif args.dry_run:
            success = await manager.dry_run_migration(args.dry_run)
            return success
        
        elif args.upgrade:
            success = await manager.upgrade_database(
                args.upgrade, 
                create_backup=not args.no_backup
            )
            return success
        
        elif args.downgrade:
            success = await manager.downgrade_database(
                args.downgrade,
                create_backup=not args.no_backup
            )
            return success
        
        elif args.generate:
            success = manager.generate_migration(args.generate)
            return success
        
        return True
        
    except Exception as e:
        print(f"❌ Migration management failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)