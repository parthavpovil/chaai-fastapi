# ChatSaaS Backend Database Scripts

This directory contains comprehensive database management scripts for production deployment, maintenance, and operations.

## Scripts Overview

### Production Initialization

#### `init-production-db.py`
Enhanced production database initialization with comprehensive setup and validation.

```bash
# Run complete database initialization
python scripts/init-production-db.py
```

**Features:**
- Database connection and permission validation
- PostgreSQL extensions initialization (pgvector, uuid-ossp, pg_trgm)
- Alembic migrations execution with timeout handling
- Database schema verification
- Comprehensive platform settings seeding
- Performance index creation
- Configuration validation
- Health checks and integrity verification
- Detailed logging and error reporting

#### `seed-platform-settings.py`
Enhanced platform settings seeder with validation, backup, and rollback capabilities.

```bash
# Seed all platform settings
python scripts/seed-platform-settings.py

# Force update existing settings
python scripts/seed-platform-settings.py --force

# Validate settings only
python scripts/seed-platform-settings.py --validate-only

# Export settings to JSON
python scripts/seed-platform-settings.py --export settings_backup.json

# Import settings from JSON
python scripts/seed-platform-settings.py --import settings_backup.json

# Rollback to backup state
python scripts/seed-platform-settings.py --rollback
```

**Features:**
- 40+ comprehensive platform settings
- Setting validation by type (boolean, integer, float, string)
- Automatic backup before changes
- Rollback capabilities
- Import/export functionality
- Detailed logging and error handling

#### `manage-platform-settings.py`
Command-line tool for managing platform-wide settings.

```bash
# List all settings
python scripts/manage-platform-settings.py list

# Get a specific setting
python scripts/manage-platform-settings.py get maintenance_mode

# Set a setting
python scripts/manage-platform-settings.py set max_file_size_mb 20

# Toggle maintenance mode
python scripts/manage-platform-settings.py maintenance

# Delete a setting
python scripts/manage-platform-settings.py delete old_setting
```

### Migration Management

#### `migration-manager.py`
Advanced migration management with safety checks and rollback capabilities.

```bash
# Show migration status
python scripts/migration-manager.py --status

# Upgrade to latest
python scripts/migration-manager.py --upgrade

# Upgrade to specific revision
python scripts/migration-manager.py --upgrade abc123

# Downgrade to revision
python scripts/migration-manager.py --downgrade def456

# Generate new migration
python scripts/migration-manager.py --generate "Add new feature"

# Dry run migration
python scripts/migration-manager.py --dry-run

# Validate migration state
python scripts/migration-manager.py --validate

# Skip backup creation
python scripts/migration-manager.py --upgrade --no-backup
```

**Features:**
- Pre-migration backup creation
- Migration state validation
- Dry run capabilities
- Detailed migration history
- Automatic rollback on failure
- SQL preview generation

### Backup and Restore

#### `backup-database.sh`
Creates compressed database backups with automatic cleanup.

```bash
# Basic backup
./scripts/backup-database.sh

# Custom backup directory and retention
BACKUP_DIR=/custom/backup/path RETENTION_DAYS=14 ./scripts/backup-database.sh
```

**Features:**
- Creates both custom and SQL format backups
- Automatic compression
- Integrity verification
- Automatic cleanup of old backups
- Configurable retention period

#### `restore-database.sh`
Restores database from backup files with safety checks.

```bash
# Restore from backup (with confirmation)
./scripts/restore-database.sh /path/to/backup.sql.gz

# Force restore without confirmation
./scripts/restore-database.sh --force backup.sql.gz

# Clean restore (drops existing database)
./scripts/restore-database.sh --clean --force backup.custom
```

**Features:**
- Supports both SQL and custom format backups
- Safety confirmations
- Clean restore option
- Integrity verification
- Connection testing

#### `database-backup-manager.py`
Advanced Python-based backup and restore manager with enhanced features.

```bash
# Create full backup
python scripts/database-backup-manager.py --full-backup

# Create schema-only backup
python scripts/database-backup-manager.py --schema-backup

# List available backups
python scripts/database-backup-manager.py --list

# Restore from backup
python scripts/database-backup-manager.py --restore /path/to/backup.custom

# Verify backup integrity
python scripts/database-backup-manager.py --verify /path/to/backup.sql.gz

# Clean up old backups
python scripts/database-backup-manager.py --cleanup 7

# Force operations without confirmation
python scripts/database-backup-manager.py --restore backup.sql.gz --force

# Clean restore (drop existing data)
python scripts/database-backup-manager.py --restore backup.custom --clean
```

**Features:**
- Multiple backup formats (custom, SQL, compressed)
- Backup metadata tracking with checksums
- Integrity verification
- Automatic cleanup with configurable retention
- Detailed backup information and statistics
- Safe restore operations with confirmations

### Database Maintenance

#### `database-maintenance.py`
Performs routine database maintenance tasks.

```bash
# Show database statistics
python scripts/database-maintenance.py --stats

# Vacuum and analyze all tables
python scripts/database-maintenance.py --vacuum

# Full vacuum (locks tables - use during maintenance windows)
python scripts/database-maintenance.py --vacuum-full

# Reindex all indexes
python scripts/database-maintenance.py --reindex

# Check for table bloat
python scripts/database-maintenance.py --bloat

# Show database size information
python scripts/database-maintenance.py --size

# Run all maintenance tasks
python scripts/database-maintenance.py --all
```

**Features:**
- Table vacuuming and analysis
- Index maintenance
- Bloat detection
- Size reporting
- Statistics gathering

#### `database-utils.py`
Comprehensive database utilities for analysis and health monitoring.

```bash
# Show database information
python scripts/database-utils.py --info

# Show table statistics
python scripts/database-utils.py --tables

# Show index statistics
python scripts/database-utils.py --indexes

# Check data integrity
python scripts/database-utils.py --integrity

# Analyze workspace usage
python scripts/database-utils.py --workspaces

# Show performance metrics
python scripts/database-utils.py --performance

# Generate comprehensive health report
python scripts/database-utils.py --health-report

# Save health report to specific file
python scripts/database-utils.py --health-report --save-report health_report.json

# Show all information
python scripts/database-utils.py --all
```

**Features:**
- Comprehensive database information gathering
- Table and index usage statistics
- Data integrity checking (orphaned records, constraint violations)
- Workspace usage analysis
- Performance metrics collection
- Health report generation with JSON export
- Summary statistics and recommendations

## Environment Variables

All scripts respect these environment variables:

- `DATABASE_URL` - Database connection string
- `BACKUP_DIR` - Backup directory (default: `/var/backups/chatsaas`)
- `RETENTION_DAYS` - Backup retention period (default: 7 days)

## Usage Examples

### Complete Production Setup

```bash
# 1. Initialize production database
python scripts/init-production-db.py

# 2. Verify setup with health check
python scripts/database-utils.py --health-report

# 3. Create initial backup
python scripts/database-backup-manager.py --full-backup

# 4. Set up maintenance mode if needed
python scripts/manage-platform-settings.py maintenance
```

### Daily Operations

```bash
# Check system health
python scripts/database-utils.py --info --workspaces

# Create backup
python scripts/database-backup-manager.py --full-backup

# Clean old backups (keep 7 days)
python scripts/database-backup-manager.py --cleanup 7

# Check for maintenance needs
python scripts/database-maintenance.py --stats --bloat
```

### Migration Operations

```bash
# Check migration status
python scripts/migration-manager.py --status

# Dry run before upgrade
python scripts/migration-manager.py --dry-run

# Upgrade with backup
python scripts/migration-manager.py --upgrade

# Generate new migration
python scripts/migration-manager.py --generate "Add new feature"
```

### Emergency Procedures

```bash
# Emergency backup before maintenance
python scripts/database-backup-manager.py --full-backup

# Enable maintenance mode
python scripts/manage-platform-settings.py maintenance

# Restore from backup if needed
python scripts/database-backup-manager.py --restore /path/to/backup.custom --clean

# Disable maintenance mode
python scripts/manage-platform-settings.py maintenance
```

## Security Considerations

1. **File Permissions**: Ensure scripts have appropriate execute permissions
2. **Database Credentials**: Use environment variables or secure credential storage
3. **Backup Security**: Store backups in secure locations with proper access controls
4. **Network Security**: Ensure database connections use SSL/TLS in production

## Monitoring Integration

Scripts provide structured output suitable for monitoring systems:

- Exit codes: 0 (success), 1 (error), 2 (warning)
- Structured logging with timestamps
- JSON output available for some operations
- Integration with system logs

## Troubleshooting

### Common Issues

1. **Permission Denied**
   ```bash
   chmod +x scripts/*.sh
   ```

2. **Database Connection Failed**
   ```bash
   # Check DATABASE_URL format
   echo $DATABASE_URL
   
   # Test connection manually
   psql $DATABASE_URL -c "SELECT 1;"
   ```

3. **Backup Directory Not Writable**
   ```bash
   sudo mkdir -p /var/backups/chatsaas
   sudo chown chatsaas:chatsaas /var/backups/chatsaas
   ```

4. **Python Path Issues**
   ```bash
   # Run from backend directory
   cd /opt/chatsaas/backend
   python scripts/script-name.py
   ```

### Log Files

Check these locations for script logs:
- `/var/log/chatsaas/backup.log`
- `/var/log/chatsaas/maintenance.log`
- System journal: `journalctl -u chatsaas-backend`

## Best Practices

1. **Test Restores**: Regularly test backup restoration procedures
2. **Monitor Disk Space**: Ensure adequate space for backups and maintenance
3. **Schedule Maintenance**: Run maintenance during low-traffic periods
4. **Version Control**: Keep scripts under version control
5. **Documentation**: Update this README when adding new scripts

## Support

For issues with database scripts:
1. Check script logs and error messages
2. Verify environment variables and permissions
3. Test database connectivity
4. Review PostgreSQL logs
5. Consult the main application documentation

### Automated Scheduling

#### Daily Backup Cron Job

```bash
# Add to crontab (crontab -e)
0 2 * * * cd /opt/chatsaas/backend && python scripts/database-backup-manager.py --full-backup >> /var/log/chatsaas/backup.log 2>&1
```

#### Weekly Maintenance

```bash
# Add to crontab for weekly maintenance
0 3 * * 0 cd /opt/chatsaas/backend && python scripts/database-maintenance.py --all >> /var/log/chatsaas/maintenance.log 2>&1
```

#### Monthly Health Reports

```bash
# Add to crontab for monthly health reports
0 1 1 * * cd /opt/chatsaas/backend && python scripts/database-utils.py --health-report --save-report monthly_health_$(date +\%Y\%m).json >> /var/log/chatsaas/health.log 2>&1
```

#### Backup Cleanup

```bash
# Add to crontab for weekly backup cleanup (keep 30 days)
0 4 * * 1 cd /opt/chatsaas/backend && python scripts/database-backup-manager.py --cleanup 30 >> /var/log/chatsaas/cleanup.log 2>&1
```

## Advanced Features

### Platform Settings Management

The enhanced platform settings system includes 40+ comprehensive settings:

**Core System Settings:**
- `maintenance_mode` - Enable/disable maintenance mode
- `maintenance_message` - Custom maintenance message
- `system_version` - Current system version

**File and Storage Settings:**
- `max_file_size_mb` - Maximum file upload size
- `max_documents_per_workspace` - Document limits per workspace
- `storage_cleanup_enabled` - Automatic file cleanup
- `storage_cleanup_days` - Cleanup retention period

**Rate Limiting Settings:**
- `rate_limit_per_minute` - WebChat message rate limit
- `rate_limit_burst` - Burst limit for rate limiting
- `rate_limit_window_minutes` - Rate limit window

**Email and Notification Settings:**
- `email_notifications_enabled` - System-wide email notifications
- `escalation_email_enabled` - Escalation email alerts
- `agent_invitation_email_enabled` - Agent invitation emails
- `email_retry_attempts` - Email delivery retry attempts

**WebSocket and Real-time Settings:**
- `websocket_max_connections` - Maximum concurrent connections
- `websocket_heartbeat_interval` - Heartbeat interval
- `websocket_timeout_seconds` - Connection timeout

**AI Provider Settings:**
- `ai_provider_timeout_seconds` - API call timeout
- `ai_provider_retry_attempts` - Retry attempts for failures
- `ai_response_max_tokens` - Maximum response tokens
- `rag_similarity_threshold` - Document similarity threshold
- `rag_max_chunks` - Maximum chunks for RAG

**Security Settings:**
- `jwt_expiry_days` - JWT token expiry
- `password_min_length` - Minimum password length
- `session_timeout_minutes` - Session timeout

**Feature Flags:**
- `feature_agent_management` - Enable agent features
- `feature_document_processing` - Enable document processing
- `feature_analytics` - Enable analytics
- `feature_multi_channel` - Enable multi-channel support

### Migration Management Features

The migration manager provides:

- **Pre-migration Backups:** Automatic backup creation before migrations
- **State Validation:** Comprehensive migration state checking
- **Dry Run Capabilities:** Preview migration SQL without execution
- **Rollback Support:** Automatic rollback on migration failures
- **Migration History:** Detailed tracking of applied migrations
- **Safety Checks:** Connection testing and validation before operations

### Backup and Restore Features

The backup system includes:

- **Multiple Formats:** Custom PostgreSQL format and compressed SQL
- **Integrity Verification:** Checksum validation and format testing
- **Metadata Tracking:** Detailed backup information storage
- **Automatic Cleanup:** Configurable retention policies
- **Restore Safety:** Confirmation prompts and clean restore options
- **Compression Support:** Automatic compression for space efficiency

### Database Health Monitoring

The health monitoring system provides:

- **Comprehensive Metrics:** Database size, connections, performance
- **Table Statistics:** Live/dead tuples, vacuum status, sizes
- **Index Analysis:** Usage statistics and efficiency metrics
- **Integrity Checks:** Orphaned records and constraint violations
- **Workspace Analytics:** Usage patterns and resource consumption
- **Performance Monitoring:** Slow queries and cache hit ratios
- **Report Generation:** JSON export for external monitoring systems

## Integration with Monitoring Systems

### Prometheus Integration

Export database metrics for Prometheus monitoring:

```bash
# Generate metrics in Prometheus format
python scripts/database-utils.py --health-report --save-report /var/lib/prometheus/chatsaas_db_metrics.json
```

### Log Analysis

All scripts provide structured logging suitable for log aggregation:

- Timestamp-based log entries
- Structured error reporting
- Operation success/failure tracking
- Performance metrics logging

### Alerting Integration

Set up alerts based on script outputs:

```bash
# Example: Alert on backup failures
if ! python scripts/database-backup-manager.py --full-backup; then
    echo "ALERT: Database backup failed" | mail -s "ChatSaaS Backup Alert" admin@company.com
fi

# Example: Alert on high dead tuple ratio
python scripts/database-utils.py --health-report --save-report /tmp/health.json
if [ $(jq '.summary.dead_tuple_ratio > 0.2' /tmp/health.json) = "true" ]; then
    echo "ALERT: High dead tuple ratio detected" | mail -s "ChatSaaS DB Alert" admin@company.com
fi
```