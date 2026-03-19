#!/bin/bash

# ChatSaaS Backend Deployment Script
# This script automates the deployment process for production

set -e  # Exit on any error

# Configuration
APP_NAME="chatsaas-backend"
APP_USER="chatsaas"
APP_DIR="/opt/chatsaas"
VENV_DIR="$APP_DIR/venv"
BACKEND_DIR="$APP_DIR/backend"
SERVICE_NAME="chatsaas-backend.service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
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

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    error "This script should not be run as root. Run as a user with sudo privileges."
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    if ! command_exists python3; then
        error "Python 3 is not installed"
    fi
    
    if ! command_exists pip3; then
        error "pip3 is not installed"
    fi
    
    if ! command_exists nginx; then
        warn "Nginx is not installed. Please install nginx for reverse proxy."
    fi
    
    if ! command_exists postgresql; then
        warn "PostgreSQL is not installed. Please install PostgreSQL 15+ with pgvector extension."
    fi
    
    log "Prerequisites check completed"
}

# Create application user and directories
setup_user_and_directories() {
    log "Setting up user and directories..."
    
    # Create application user if it doesn't exist
    if ! id "$APP_USER" &>/dev/null; then
        sudo useradd -r -s /bin/bash -d "$APP_DIR" "$APP_USER"
        log "Created user: $APP_USER"
    fi
    
    # Create directories
    sudo mkdir -p "$APP_DIR"
    sudo mkdir -p "$BACKEND_DIR"
    sudo mkdir -p /var/chatsaas/storage/documents
    sudo mkdir -p /var/run/chatsaas
    sudo mkdir -p /var/log/chatsaas
    
    # Set ownership
    sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    sudo chown -R "$APP_USER:$APP_USER" /var/chatsaas
    sudo chown -R "$APP_USER:$APP_USER" /var/run/chatsaas
    sudo chown -R "$APP_USER:$APP_USER" /var/log/chatsaas
    
    log "User and directories setup completed"
}

# Setup Python virtual environment
setup_python_environment() {
    log "Setting up Python virtual environment..."
    
    # Create virtual environment
    sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
    
    # Upgrade pip
    sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    
    log "Python virtual environment setup completed"
}

# Deploy application code
deploy_application() {
    log "Deploying application code..."
    
    # Copy application files
    sudo cp -r . "$BACKEND_DIR/"
    
    # Install Python dependencies
    sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
    
    # Set ownership
    sudo chown -R "$APP_USER:$APP_USER" "$BACKEND_DIR"
    
    log "Application deployment completed"
}

# Setup database
setup_database() {
    log "Setting up database..."
    
    # Check if .env file exists
    if [[ ! -f "$BACKEND_DIR/.env" ]]; then
        warn ".env file not found. Please create it from .env.production template"
        return
    fi
    
    # Run database migrations
    cd "$BACKEND_DIR"
    sudo -u "$APP_USER" "$VENV_DIR/bin/alembic" upgrade head
    
    log "Database setup completed"
}

# Setup systemd service
setup_systemd_service() {
    log "Setting up systemd service..."
    
    # Copy service file
    sudo cp "$BACKEND_DIR/$SERVICE_NAME" "/etc/systemd/system/"
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable service
    sudo systemctl enable "$SERVICE_NAME"
    
    log "Systemd service setup completed"
}

# Setup nginx
setup_nginx() {
    log "Setting up Nginx configuration..."
    
    if command_exists nginx; then
        # Copy nginx configuration
        sudo cp "$BACKEND_DIR/nginx.conf" "/etc/nginx/sites-available/chatsaas"
        
        # Enable site
        sudo ln -sf "/etc/nginx/sites-available/chatsaas" "/etc/nginx/sites-enabled/"
        
        # Remove default site
        sudo rm -f "/etc/nginx/sites-enabled/default"
        
        # Test nginx configuration
        sudo nginx -t
        
        log "Nginx configuration setup completed"
    else
        warn "Nginx not installed. Skipping nginx configuration."
    fi
}

# Start services
start_services() {
    log "Starting services..."
    
    # Start application service
    sudo systemctl start "$SERVICE_NAME"
    
    # Start nginx if available
    if command_exists nginx; then
        sudo systemctl restart nginx
    fi
    
    log "Services started"
}

# Check service status
check_status() {
    log "Checking service status..."
    
    # Check application service
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        log "✓ $SERVICE_NAME is running"
    else
        error "✗ $SERVICE_NAME is not running"
    fi
    
    # Check nginx
    if command_exists nginx && sudo systemctl is-active --quiet nginx; then
        log "✓ Nginx is running"
    else
        warn "✗ Nginx is not running or not installed"
    fi
    
    # Check health endpoint
    if curl -f http://localhost:8000/health >/dev/null 2>&1; then
        log "✓ Application health check passed"
    else
        warn "✗ Application health check failed"
    fi
}

# Main deployment function
main() {
    log "Starting ChatSaaS Backend deployment..."
    
    check_prerequisites
    setup_user_and_directories
    setup_python_environment
    deploy_application
    setup_database
    setup_systemd_service
    setup_nginx
    start_services
    check_status
    
    log "Deployment completed successfully!"
    log "Please ensure you have:"
    log "1. Created .env file with production configuration"
    log "2. Configured SSL certificates"
    log "3. Set up your domain DNS"
    log "4. Configured firewall rules"
}

# Run main function
main "$@"