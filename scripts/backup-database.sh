#!/bin/bash

# ChatSaaS Backend Database Backup Script
# Creates compressed backups with timestamp and retention management

set -e  # Exit on any error

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/chatsaas}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
DATABASE_URL="${DATABASE_URL:-postgresql://chatsaas_user:password@localhost:5432/chatsaas_prod}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="chatsaas_backup_${TIMESTAMP}.sql.gz"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

# Parse database URL
parse_db_url() {
    if [[ $DATABASE_URL =~ postgresql\+?.*://([^:]+):([^@]+)@([^:]+):([0-9]+)/(.+) ]]; then
        DB_USER="${BASH_REMATCH[1]}"
        DB_PASS="${BASH_REMATCH[2]}"
        DB_HOST="${BASH_REMATCH[3]}"
        DB_PORT="${BASH_REMATCH[4]}"
        DB_NAME="${BASH_REMATCH[5]}"
    else
        error "Invalid DATABASE_URL format"
    fi
}

# Create backup directory
create_backup_dir() {
    if [[ ! -d "$BACKUP_DIR" ]]; then
        log "Creating backup directory: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
    fi
}

# Perform database backup
backup_database() {
    log "Starting database backup..."
    log "Database: $DB_NAME"
    log "Host: $DB_HOST:$DB_PORT"
    log "Backup file: $BACKUP_FILE"
    
    # Set password for pg_dump
    export PGPASSWORD="$DB_PASS"
    
    # Create backup with compression
    if pg_dump \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --verbose \
        --no-password \
        --format=custom \
        --compress=9 \
        --file="$BACKUP_DIR/$BACKUP_FILE.custom"; then
        
        # Also create a plain SQL backup for easier inspection
        pg_dump \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            --dbname="$DB_NAME" \
            --no-password \
            --format=plain | gzip > "$BACKUP_DIR/$BACKUP_FILE"
        
        log "✅ Database backup completed successfully"
        log "Custom format: $BACKUP_DIR/$BACKUP_FILE.custom"
        log "SQL format: $BACKUP_DIR/$BACKUP_FILE"
        
        # Get file sizes
        CUSTOM_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE.custom" | cut -f1)
        SQL_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)
        log "Backup sizes - Custom: $CUSTOM_SIZE, SQL: $SQL_SIZE"
        
    else
        error "Database backup failed"
    fi
    
    # Clear password
    unset PGPASSWORD
}

# Clean old backups
cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."
    
    # Find and delete old backup files
    DELETED_COUNT=0
    while IFS= read -r -d '' file; do
        log "Deleting old backup: $(basename "$file")"
        rm "$file"
        ((DELETED_COUNT++))
    done < <(find "$BACKUP_DIR" -name "chatsaas_backup_*.sql.gz*" -mtime +$RETENTION_DAYS -print0)
    
    if [[ $DELETED_COUNT -gt 0 ]]; then
        log "✅ Cleaned up $DELETED_COUNT old backup files"
    else
        log "No old backups to clean up"
    fi
}

# Verify backup integrity
verify_backup() {
    log "Verifying backup integrity..."
    
    # Test gzip integrity
    if gzip -t "$BACKUP_DIR/$BACKUP_FILE"; then
        log "✅ SQL backup integrity verified"
    else
        error "SQL backup integrity check failed"
    fi
    
    # Test custom format backup
    export PGPASSWORD="$DB_PASS"
    if pg_restore --list "$BACKUP_DIR/$BACKUP_FILE.custom" > /dev/null 2>&1; then
        log "✅ Custom backup integrity verified"
    else
        warn "Custom backup integrity check failed"
    fi
    unset PGPASSWORD
}

# Main backup function
main() {
    log "Starting ChatSaaS database backup process..."
    
    # Parse database connection
    parse_db_url
    
    # Create backup directory
    create_backup_dir
    
    # Perform backup
    backup_database
    
    # Verify backup
    verify_backup
    
    # Cleanup old backups
    cleanup_old_backups
    
    log "🎉 Database backup process completed successfully!"
    log "Latest backup: $BACKUP_DIR/$BACKUP_FILE"
}

# Check if running as script
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi