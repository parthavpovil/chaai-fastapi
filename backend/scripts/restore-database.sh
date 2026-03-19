#!/bin/bash

# ChatSaaS Backend Database Restore Script
# Restores database from backup with safety checks

set -e  # Exit on any error

# Configuration
BACKUP_DIR="${BACKUP_DIR:-/var/backups/chatsaas}"
DATABASE_URL="${DATABASE_URL:-postgresql://chatsaas_user:password@localhost:5432/chatsaas_prod}"

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

# Show usage
usage() {
    echo "Usage: $0 [OPTIONS] BACKUP_FILE"
    echo ""
    echo "Restore ChatSaaS database from backup"
    echo ""
    echo "Arguments:"
    echo "  BACKUP_FILE    Path to backup file (.sql.gz or .custom)"
    echo ""
    echo "Options:"
    echo "  -f, --force    Skip confirmation prompts"
    echo "  -c, --clean    Drop existing database before restore"
    echo "  -h, --help     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 /var/backups/chatsaas/chatsaas_backup_20240101_120000.sql.gz"
    echo "  $0 --clean --force backup.custom"
    echo ""
    echo "Environment Variables:"
    echo "  DATABASE_URL   Database connection string"
    echo "  BACKUP_DIR     Default backup directory"
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

# Check if backup file exists and is readable
validate_backup_file() {
    local backup_file="$1"
    
    if [[ ! -f "$backup_file" ]]; then
        error "Backup file not found: $backup_file"
    fi
    
    if [[ ! -r "$backup_file" ]]; then
        error "Backup file not readable: $backup_file"
    fi
    
    # Check file format
    if [[ "$backup_file" == *.sql.gz ]]; then
        BACKUP_FORMAT="sql"
        log "Detected SQL backup format"
        
        # Test gzip integrity
        if ! gzip -t "$backup_file"; then
            error "Backup file is corrupted (gzip test failed)"
        fi
    elif [[ "$backup_file" == *.custom ]]; then
        BACKUP_FORMAT="custom"
        log "Detected custom backup format"
        
        # Test custom format
        export PGPASSWORD="$DB_PASS"
        if ! pg_restore --list "$backup_file" > /dev/null 2>&1; then
            error "Backup file is corrupted (pg_restore test failed)"
        fi
        unset PGPASSWORD
    else
        error "Unsupported backup format. Use .sql.gz or .custom files"
    fi
    
    log "✅ Backup file validation passed"
}

# Check database connection
check_database_connection() {
    log "Testing database connection..."
    
    export PGPASSWORD="$DB_PASS"
    if psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="postgres" \
        --command="SELECT 1;" > /dev/null 2>&1; then
        log "✅ Database connection successful"
    else
        error "Cannot connect to database server"
    fi
    unset PGPASSWORD
}

# Create database if it doesn't exist
create_database_if_needed() {
    log "Checking if database exists..."
    
    export PGPASSWORD="$DB_PASS"
    
    # Check if database exists
    if psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="postgres" \
        --tuples-only \
        --command="SELECT 1 FROM pg_database WHERE datname='$DB_NAME';" | grep -q 1; then
        log "Database '$DB_NAME' exists"
    else
        log "Creating database '$DB_NAME'..."
        createdb \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            --owner="$DB_USER" \
            "$DB_NAME"
        log "✅ Database created"
    fi
    
    unset PGPASSWORD
}

# Drop database if clean restore requested
drop_database_if_clean() {
    if [[ "$CLEAN_RESTORE" == "true" ]]; then
        log "Dropping existing database for clean restore..."
        
        export PGPASSWORD="$DB_PASS"
        
        # Terminate existing connections
        psql \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            --dbname="postgres" \
            --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid <> pg_backend_pid();" > /dev/null 2>&1 || true
        
        # Drop database
        dropdb \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            "$DB_NAME" 2>/dev/null || true
        
        log "✅ Database dropped"
        unset PGPASSWORD
        
        # Recreate database
        create_database_if_needed
    fi
}

# Restore from SQL backup
restore_sql_backup() {
    local backup_file="$1"
    
    log "Restoring from SQL backup..."
    
    export PGPASSWORD="$DB_PASS"
    
    if zcat "$backup_file" | psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --quiet; then
        log "✅ SQL backup restored successfully"
    else
        error "SQL backup restore failed"
    fi
    
    unset PGPASSWORD
}

# Restore from custom backup
restore_custom_backup() {
    local backup_file="$1"
    
    log "Restoring from custom backup..."
    
    export PGPASSWORD="$DB_PASS"
    
    local restore_args=(
        --host="$DB_HOST"
        --port="$DB_PORT"
        --username="$DB_USER"
        --dbname="$DB_NAME"
        --verbose
        --no-password
    )
    
    if [[ "$CLEAN_RESTORE" == "true" ]]; then
        restore_args+=(--clean --create)
    fi
    
    if pg_restore "${restore_args[@]}" "$backup_file"; then
        log "✅ Custom backup restored successfully"
    else
        error "Custom backup restore failed"
    fi
    
    unset PGPASSWORD
}

# Verify restore
verify_restore() {
    log "Verifying database restore..."
    
    export PGPASSWORD="$DB_PASS"
    
    # Check if we can connect and query
    if psql \
        --host="$DB_HOST" \
        --port="$DB_PORT" \
        --username="$DB_USER" \
        --dbname="$DB_NAME" \
        --command="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';" > /dev/null 2>&1; then
        
        # Get table count
        TABLE_COUNT=$(psql \
            --host="$DB_HOST" \
            --port="$DB_PORT" \
            --username="$DB_USER" \
            --dbname="$DB_NAME" \
            --tuples-only \
            --command="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
        
        log "✅ Database restore verified - $TABLE_COUNT tables found"
    else
        error "Database restore verification failed"
    fi
    
    unset PGPASSWORD
}

# Confirmation prompt
confirm_restore() {
    if [[ "$FORCE_RESTORE" == "true" ]]; then
        return 0
    fi
    
    echo ""
    warn "⚠️  DATABASE RESTORE WARNING ⚠️"
    echo ""
    echo "This will restore the database: $DB_NAME"
    echo "Host: $DB_HOST:$DB_PORT"
    echo "Backup file: $BACKUP_FILE"
    echo "Format: $BACKUP_FORMAT"
    
    if [[ "$CLEAN_RESTORE" == "true" ]]; then
        echo ""
        echo "🔥 CLEAN RESTORE: This will DROP the existing database!"
        echo "   All current data will be PERMANENTLY LOST!"
    fi
    
    echo ""
    read -p "Are you sure you want to continue? (type 'yes' to confirm): " -r
    
    if [[ ! $REPLY == "yes" ]]; then
        log "Restore cancelled by user"
        exit 0
    fi
}

# Main restore function
main() {
    local backup_file=""
    FORCE_RESTORE="false"
    CLEAN_RESTORE="false"
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--force)
                FORCE_RESTORE="true"
                shift
                ;;
            -c|--clean)
                CLEAN_RESTORE="true"
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            -*)
                error "Unknown option: $1"
                ;;
            *)
                if [[ -z "$backup_file" ]]; then
                    backup_file="$1"
                else
                    error "Multiple backup files specified"
                fi
                shift
                ;;
        esac
    done
    
    # Check if backup file was provided
    if [[ -z "$backup_file" ]]; then
        error "No backup file specified. Use --help for usage information."
    fi
    
    # Convert relative path to absolute
    BACKUP_FILE=$(realpath "$backup_file")
    
    log "Starting ChatSaaS database restore process..."
    log "Backup file: $BACKUP_FILE"
    
    # Parse database connection
    parse_db_url
    
    # Validate backup file
    validate_backup_file "$BACKUP_FILE"
    
    # Check database connection
    check_database_connection
    
    # Confirm restore
    confirm_restore
    
    # Create database if needed
    create_database_if_needed
    
    # Drop database if clean restore
    drop_database_if_clean
    
    # Perform restore based on format
    if [[ "$BACKUP_FORMAT" == "sql" ]]; then
        restore_sql_backup "$BACKUP_FILE"
    elif [[ "$BACKUP_FORMAT" == "custom" ]]; then
        restore_custom_backup "$BACKUP_FILE"
    fi
    
    # Verify restore
    verify_restore
    
    log "🎉 Database restore completed successfully!"
    
    # Suggest next steps
    echo ""
    log "Next steps:"
    log "1. Run database migrations if needed: alembic upgrade head"
    log "2. Restart the application"
    log "3. Run health checks"
}

# Check if running as script
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi