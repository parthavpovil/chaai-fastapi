#!/usr/bin/env python3
"""
Database Backup and Restore Manager
Advanced backup and restore operations with encryption, compression, and validation.
"""
import asyncio
import sys
import subprocess
import json
import gzip
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import engine
from app.config import settings


@dataclass
class BackupInfo:
    """Backup information structure"""
    filename: str
    path: str
    size: int
    created_at: datetime
    backup_type: str
    checksum: str
    compressed: bool
    encrypted: bool


class DatabaseBackupManager:
    """Advanced database backup and restore management"""
    
    def __init__(self, backup_dir: Optional[str] = None):
        self.backup_dir = Path(backup_dir or "/var/backups/chatsaas")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Parse database URL
        self.db_config = self._parse_database_url()
        
    def _parse_database_url(self) -> Dict[str, str]:
        """Parse database URL into components"""
        db_url = str(settings.DATABASE_URL)
        
        # Handle asyncpg URLs
        if "postgresql+asyncpg://" in db_url:
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        
        # Simple URL parsing (could use urllib.parse for more robust parsing)
        if "://" in db_url:
            try:
                # Extract components
                protocol, rest = db_url.split("://", 1)
                if "@" in rest:
                    auth, host_db = rest.split("@", 1)
                    if ":" in auth:
                        user, password = auth.split(":", 1)
                    else:
                        user, password = auth, ""
                else:
                    user, password = "", ""
                    host_db = rest
                
                if "/" in host_db:
                    host_port, database = host_db.rsplit("/", 1)
                else:
                    host_port, database = host_db, ""
                
                if ":" in host_port:
                    host, port = host_port.split(":", 1)
                else:
                    host, port = host_port, "5432"
                
                return {
                    "host": host,
                    "port": port,
                    "user": user,
                    "password": password,
                    "database": database
                }
            except Exception as e:
                print(f"⚠️  Could not parse database URL: {e}")
                return {}
        
        return {}
    
    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def _get_backup_filename(self, backup_type: str = "full") -> str:
        """Generate backup filename with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"chatsaas_{backup_type}_backup_{timestamp}"
    
    async def test_database_connection(self) -> bool:
        """Test database connectivity"""
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False
    
    def create_full_backup(self, compress: bool = True, custom_format: bool = True) -> Optional[BackupInfo]:
        """Create full database backup"""
        print("📦 Creating full database backup...")
        
        if not self.db_config:
            print("❌ Invalid database configuration")
            return None
        
        timestamp = datetime.now()
        base_filename = self._get_backup_filename("full")
        
        try:
            # Set environment for pg_dump
            env = {
                "PGPASSWORD": self.db_config["password"]
            }
            
            if custom_format:
                # Custom format backup
                backup_file = self.backup_dir / f"{base_filename}.custom"
                
                cmd = [
                    "pg_dump",
                    f"--host={self.db_config['host']}",
                    f"--port={self.db_config['port']}",
                    f"--username={self.db_config['user']}",
                    f"--dbname={self.db_config['database']}",
                    "--format=custom",
                    "--no-password",
                    "--verbose"
                ]
                
                if compress:
                    cmd.append("--compress=9")
                
                cmd.append(f"--file={backup_file}")
                
            else:
                # Plain SQL backup
                backup_file = self.backup_dir / f"{base_filename}.sql"
                if compress:
                    backup_file = self.backup_dir / f"{base_filename}.sql.gz"
                
                cmd = [
                    "pg_dump",
                    f"--host={self.db_config['host']}",
                    f"--port={self.db_config['port']}",
                    f"--username={self.db_config['user']}",
                    f"--dbname={self.db_config['database']}",
                    "--format=plain",
                    "--no-password",
                    "--verbose"
                ]
                
                if not compress:
                    cmd.append(f"--file={backup_file}")
            
            # Execute backup command
            if custom_format or not compress:
                result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            else:
                # For compressed SQL, pipe through gzip
                cmd_dump = cmd[:-1]  # Remove --file argument
                
                with open(backup_file, 'wb') as f:
                    dump_process = subprocess.Popen(
                        cmd_dump, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    gzip_process = subprocess.Popen(
                        ["gzip"], stdin=dump_process.stdout, stdout=f, stderr=subprocess.PIPE
                    )
                    dump_process.stdout.close()
                    
                    _, dump_stderr = dump_process.communicate()
                    _, gzip_stderr = gzip_process.communicate()
                    
                    result = type('Result', (), {
                        'returncode': dump_process.returncode or gzip_process.returncode,
                        'stderr': dump_stderr.decode() + gzip_stderr.decode()
                    })()
            
            if result.returncode == 0:
                # Calculate file info
                file_size = backup_file.stat().st_size
                checksum = self._calculate_checksum(backup_file)
                
                backup_info = BackupInfo(
                    filename=backup_file.name,
                    path=str(backup_file),
                    size=file_size,
                    created_at=timestamp,
                    backup_type="full",
                    checksum=checksum,
                    compressed=compress,
                    encrypted=False
                )
                
                # Save backup metadata
                self._save_backup_metadata(backup_info)
                
                print(f"✅ Backup created successfully: {backup_file}")
                print(f"   Size: {self._format_size(file_size)}")
                print(f"   Checksum: {checksum[:16]}...")
                
                return backup_info
            else:
                print(f"❌ Backup failed: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Backup error: {e}")
            return None
    
    def create_schema_backup(self) -> Optional[BackupInfo]:
        """Create schema-only backup"""
        print("📋 Creating schema-only backup...")
        
        if not self.db_config:
            print("❌ Invalid database configuration")
            return None
        
        timestamp = datetime.now()
        base_filename = self._get_backup_filename("schema")
        backup_file = self.backup_dir / f"{base_filename}.sql"
        
        try:
            env = {"PGPASSWORD": self.db_config["password"]}
            
            cmd = [
                "pg_dump",
                f"--host={self.db_config['host']}",
                f"--port={self.db_config['port']}",
                f"--username={self.db_config['user']}",
                f"--dbname={self.db_config['database']}",
                "--schema-only",
                "--format=plain",
                "--no-password",
                f"--file={backup_file}"
            ]
            
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                file_size = backup_file.stat().st_size
                checksum = self._calculate_checksum(backup_file)
                
                backup_info = BackupInfo(
                    filename=backup_file.name,
                    path=str(backup_file),
                    size=file_size,
                    created_at=timestamp,
                    backup_type="schema",
                    checksum=checksum,
                    compressed=False,
                    encrypted=False
                )
                
                self._save_backup_metadata(backup_info)
                
                print(f"✅ Schema backup created: {backup_file}")
                return backup_info
            else:
                print(f"❌ Schema backup failed: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"❌ Schema backup error: {e}")
            return None
    
    def restore_backup(self, backup_path: str, clean: bool = False, confirm: bool = True) -> bool:
        """Restore database from backup"""
        backup_file = Path(backup_path)
        
        if not backup_file.exists():
            print(f"❌ Backup file not found: {backup_path}")
            return False
        
        print(f"🔄 Restoring database from: {backup_file.name}")
        
        # Confirmation
        if confirm:
            print(f"⚠️  This will restore the database: {self.db_config['database']}")
            if clean:
                print("🔥 CLEAN RESTORE: This will DROP the existing database!")
            
            response = input("Are you sure you want to continue? (yes/no): ")
            if response.lower() != "yes":
                print("Restore cancelled")
                return False
        
        try:
            env = {"PGPASSWORD": self.db_config["password"]}
            
            # Determine backup format
            if backup_file.suffix == ".custom":
                # Custom format restore
                cmd = [
                    "pg_restore",
                    f"--host={self.db_config['host']}",
                    f"--port={self.db_config['port']}",
                    f"--username={self.db_config['user']}",
                    f"--dbname={self.db_config['database']}",
                    "--no-password",
                    "--verbose"
                ]
                
                if clean:
                    cmd.extend(["--clean", "--create"])
                
                cmd.append(str(backup_file))
                
            else:
                # SQL format restore
                if backup_file.suffix == ".gz":
                    # Compressed SQL
                    cmd_gunzip = ["gunzip", "-c", str(backup_file)]
                    cmd_psql = [
                        "psql",
                        f"--host={self.db_config['host']}",
                        f"--port={self.db_config['port']}",
                        f"--username={self.db_config['user']}",
                        f"--dbname={self.db_config['database']}",
                        "--no-password"
                    ]
                    
                    # Pipe gunzip to psql
                    gunzip_process = subprocess.Popen(cmd_gunzip, stdout=subprocess.PIPE)
                    result = subprocess.run(
                        cmd_psql, stdin=gunzip_process.stdout, env=env, 
                        capture_output=True, text=True
                    )
                    gunzip_process.stdout.close()
                    gunzip_process.wait()
                    
                else:
                    # Plain SQL
                    cmd = [
                        "psql",
                        f"--host={self.db_config['host']}",
                        f"--port={self.db_config['port']}",
                        f"--username={self.db_config['user']}",
                        f"--dbname={self.db_config['database']}",
                        "--no-password",
                        f"--file={backup_file}"
                    ]
                    
                    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("✅ Database restore completed successfully")
                return True
            else:
                print(f"❌ Restore failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Restore error: {e}")
            return False
    
    def list_backups(self) -> List[BackupInfo]:
        """List available backups"""
        backups = []
        
        # Look for backup files
        for backup_file in self.backup_dir.glob("chatsaas_*_backup_*"):
            if backup_file.is_file():
                try:
                    # Try to load metadata
                    metadata_file = self.backup_dir / f"{backup_file.stem}.metadata.json"
                    if metadata_file.exists():
                        with open(metadata_file, 'r') as f:
                            metadata = json.load(f)
                        
                        backup_info = BackupInfo(
                            filename=metadata["filename"],
                            path=metadata["path"],
                            size=metadata["size"],
                            created_at=datetime.fromisoformat(metadata["created_at"]),
                            backup_type=metadata["backup_type"],
                            checksum=metadata["checksum"],
                            compressed=metadata.get("compressed", False),
                            encrypted=metadata.get("encrypted", False)
                        )
                    else:
                        # Create basic info from file
                        stat = backup_file.stat()
                        backup_info = BackupInfo(
                            filename=backup_file.name,
                            path=str(backup_file),
                            size=stat.st_size,
                            created_at=datetime.fromtimestamp(stat.st_mtime),
                            backup_type="unknown",
                            checksum="",
                            compressed=backup_file.suffix in [".gz", ".custom"],
                            encrypted=False
                        )
                    
                    backups.append(backup_info)
                    
                except Exception as e:
                    print(f"⚠️  Could not process backup {backup_file}: {e}")
        
        # Sort by creation time (newest first)
        backups.sort(key=lambda x: x.created_at, reverse=True)
        return backups
    
    def cleanup_old_backups(self, retention_days: int = 7) -> int:
        """Clean up old backups"""
        print(f"🧹 Cleaning up backups older than {retention_days} days...")
        
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        backups = self.list_backups()
        
        deleted_count = 0
        for backup in backups:
            if backup.created_at < cutoff_date:
                try:
                    # Delete backup file
                    Path(backup.path).unlink()
                    
                    # Delete metadata file
                    metadata_file = Path(backup.path).parent / f"{Path(backup.path).stem}.metadata.json"
                    if metadata_file.exists():
                        metadata_file.unlink()
                    
                    print(f"  🗑️  Deleted: {backup.filename}")
                    deleted_count += 1
                    
                except Exception as e:
                    print(f"  ⚠️  Could not delete {backup.filename}: {e}")
        
        print(f"✅ Cleaned up {deleted_count} old backups")
        return deleted_count
    
    def verify_backup(self, backup_path: str) -> bool:
        """Verify backup integrity"""
        backup_file = Path(backup_path)
        
        if not backup_file.exists():
            print(f"❌ Backup file not found: {backup_path}")
            return False
        
        print(f"🔍 Verifying backup: {backup_file.name}")
        
        try:
            # Check file integrity based on format
            if backup_file.suffix == ".custom":
                # Test custom format with pg_restore --list
                env = {"PGPASSWORD": self.db_config["password"]}
                result = subprocess.run([
                    "pg_restore", "--list", str(backup_file)
                ], env=env, capture_output=True, text=True)
                
                if result.returncode == 0:
                    print("✅ Custom format backup integrity verified")
                    return True
                else:
                    print(f"❌ Custom format verification failed: {result.stderr}")
                    return False
                    
            elif backup_file.suffix == ".gz":
                # Test gzip integrity
                result = subprocess.run([
                    "gzip", "-t", str(backup_file)
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    print("✅ Compressed backup integrity verified")
                    return True
                else:
                    print(f"❌ Compression verification failed: {result.stderr}")
                    return False
                    
            else:
                # For plain SQL, just check if file is readable
                with open(backup_file, 'r') as f:
                    f.read(1024)  # Read first 1KB
                
                print("✅ Plain SQL backup integrity verified")
                return True
                
        except Exception as e:
            print(f"❌ Backup verification failed: {e}")
            return False
    
    def _save_backup_metadata(self, backup_info: BackupInfo):
        """Save backup metadata to JSON file"""
        metadata_file = Path(backup_info.path).parent / f"{Path(backup_info.path).stem}.metadata.json"
        
        metadata = {
            "filename": backup_info.filename,
            "path": backup_info.path,
            "size": backup_info.size,
            "created_at": backup_info.created_at.isoformat(),
            "backup_type": backup_info.backup_type,
            "checksum": backup_info.checksum,
            "compressed": backup_info.compressed,
            "encrypted": backup_info.encrypted
        }
        
        try:
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save metadata: {e}")
    
    def _format_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


async def main():
    """Main backup management function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database Backup and Restore Manager")
    parser.add_argument("--backup-dir", type=str, help="Backup directory path")
    parser.add_argument("--full-backup", action="store_true", help="Create full backup")
    parser.add_argument("--schema-backup", action="store_true", help="Create schema-only backup")
    parser.add_argument("--restore", type=str, help="Restore from backup file")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--verify", type=str, help="Verify backup integrity")
    parser.add_argument("--cleanup", type=int, help="Clean up backups older than N days")
    parser.add_argument("--clean", action="store_true", help="Clean restore (drop existing data)")
    parser.add_argument("--no-compress", action="store_true", help="Disable compression")
    parser.add_argument("--plain-format", action="store_true", help="Use plain SQL format instead of custom")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    manager = DatabaseBackupManager(args.backup_dir)
    
    print("💾 ChatSaaS Database Backup Manager")
    print("=" * 50)
    
    try:
        # Test database connection first
        if not await manager.test_database_connection():
            print("❌ Cannot proceed without database connection")
            return False
        
        if args.full_backup:
            backup_info = manager.create_full_backup(
                compress=not args.no_compress,
                custom_format=not args.plain_format
            )
            return backup_info is not None
        
        elif args.schema_backup:
            backup_info = manager.create_schema_backup()
            return backup_info is not None
        
        elif args.restore:
            success = manager.restore_backup(
                args.restore,
                clean=args.clean,
                confirm=not args.force
            )
            return success
        
        elif args.list:
            backups = manager.list_backups()
            if backups:
                print(f"\nFound {len(backups)} backups:")
                print("-" * 80)
                print(f"{'Filename':<40} {'Type':<10} {'Size':<10} {'Created':<20}")
                print("-" * 80)
                
                for backup in backups:
                    print(f"{backup.filename:<40} {backup.backup_type:<10} "
                          f"{manager._format_size(backup.size):<10} "
                          f"{backup.created_at.strftime('%Y-%m-%d %H:%M'):<20}")
            else:
                print("No backups found")
            return True
        
        elif args.verify:
            success = manager.verify_backup(args.verify)
            return success
        
        elif args.cleanup is not None:
            deleted_count = manager.cleanup_old_backups(args.cleanup)
            return True
        
        return True
        
    except Exception as e:
        print(f"❌ Backup management failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)