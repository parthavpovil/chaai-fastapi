#!/bin/bash

# ChatSaaS Backend Monitoring Setup Script
# This script sets up monitoring infrastructure for production deployment

set -e

echo "🔧 Setting up ChatSaaS Backend Monitoring..."

# Configuration
MONITORING_DIR="/opt/chatsaas/monitoring"
LOG_DIR="/var/log/chatsaas"
STORAGE_DIR="/var/chatsaas/storage"
SERVICE_USER="chatsaas"

# Create directories
echo "📁 Creating monitoring directories..."
sudo mkdir -p $MONITORING_DIR
sudo mkdir -p $LOG_DIR
sudo mkdir -p $STORAGE_DIR
sudo mkdir -p /etc/chatsaas

# Create service user if it doesn't exist
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "👤 Creating service user: $SERVICE_USER"
    sudo useradd --system --shell /bin/false --home-dir /opt/chatsaas --create-home $SERVICE_USER
fi

# Set permissions
echo "🔐 Setting up permissions..."
sudo chown -R $SERVICE_USER:$SERVICE_USER $LOG_DIR
sudo chown -R $SERVICE_USER:$SERVICE_USER $STORAGE_DIR
sudo chown -R $SERVICE_USER:$SERVICE_USER /opt/chatsaas
sudo chmod 755 $LOG_DIR
sudo chmod 755 $STORAGE_DIR

# Copy monitoring configuration
echo "📋 Installing monitoring configuration..."
sudo cp monitoring.yml /etc/chatsaas/
sudo cp monitoring_dashboard.json $MONITORING_DIR/
sudo cp health_check.py $MONITORING_DIR/
sudo chown $SERVICE_USER:$SERVICE_USER /etc/chatsaas/monitoring.yml
sudo chown -R $SERVICE_USER:$SERVICE_USER $MONITORING_DIR

# Install Python dependencies for health checks
echo "🐍 Installing Python dependencies..."
sudo -u $SERVICE_USER python3 -m pip install --user aiohttp asyncpg psutil

# Create health check script
echo "🏥 Setting up health check script..."
cat > /tmp/chatsaas-health-check << 'EOF'
#!/bin/bash
cd /opt/chatsaas/monitoring
python3 health_check.py
EOF

sudo mv /tmp/chatsaas-health-check /usr/local/bin/
sudo chmod +x /usr/local/bin/chatsaas-health-check
sudo chown root:root /usr/local/bin/chatsaas-health-check

# Create systemd service for health monitoring
echo "⚙️ Creating health monitoring service..."
cat > /tmp/chatsaas-health-monitor.service << EOF
[Unit]
Description=ChatSaaS Health Monitor
After=network.target

[Service]
Type=oneshot
User=$SERVICE_USER
ExecStart=/usr/local/bin/chatsaas-health-check
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo mv /tmp/chatsaas-health-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload

# Create systemd timer for periodic health checks
echo "⏰ Setting up health check timer..."
cat > /tmp/chatsaas-health-monitor.timer << EOF
[Unit]
Description=Run ChatSaaS Health Check every 5 minutes
Requires=chatsaas-health-monitor.service

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo mv /tmp/chatsaas-health-monitor.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chatsaas-health-monitor.timer

# Set up log rotation
echo "🔄 Setting up log rotation..."
cat > /tmp/chatsaas-logrotate << EOF
$LOG_DIR/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 $SERVICE_USER $SERVICE_USER
    postrotate
        systemctl reload chatsaas-backend || true
    endscript
}
EOF

sudo mv /tmp/chatsaas-logrotate /etc/logrotate.d/chatsaas
sudo chown root:root /etc/logrotate.d/chatsaas
sudo chmod 644 /etc/logrotate.d/chatsaas

# Create monitoring environment file
echo "🌍 Creating monitoring environment configuration..."
cat > /tmp/monitoring.env << EOF
# ChatSaaS Monitoring Configuration
APP_URL=http://localhost:8000
DATABASE_URL=postgresql://chatsaas:password@localhost:5432/chatsaas
STORAGE_PATH=$STORAGE_DIR
LOG_DIR=$LOG_DIR
ENVIRONMENT=production

# Alert Thresholds
ALERT_ERROR_RATE_THRESHOLD=0.05
ALERT_RESPONSE_TIME_THRESHOLD=2000
ALERT_DB_CONNECTION_THRESHOLD=50
ALERT_STALE_CONVERSATION_THRESHOLD=10
ALERT_FAILED_DOCUMENT_THRESHOLD=5
ALERT_DISK_SPACE_THRESHOLD=5.0
ALERT_MEMORY_USAGE_THRESHOLD=90.0

# Health Check Configuration
HEALTH_CHECK_INTERVAL=300
METRICS_COLLECTION_INTERVAL=60

# Notification Configuration
ADMIN_EMAIL=admin@your-domain.com
SLACK_WEBHOOK_URL=
EOF

sudo mv /tmp/monitoring.env /etc/chatsaas/
sudo chown $SERVICE_USER:$SERVICE_USER /etc/chatsaas/monitoring.env
sudo chmod 600 /etc/chatsaas/monitoring.env

# Install Prometheus Node Exporter (optional)
if command -v prometheus-node-exporter >/dev/null 2>&1; then
    echo "📊 Prometheus Node Exporter already installed"
else
    echo "📊 Installing Prometheus Node Exporter..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y prometheus-node-exporter
        sudo systemctl enable prometheus-node-exporter
        sudo systemctl start prometheus-node-exporter
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y prometheus-node-exporter
        sudo systemctl enable prometheus-node-exporter
        sudo systemctl start prometheus-node-exporter
    else
        echo "⚠️ Could not install Prometheus Node Exporter automatically"
        echo "Please install it manually for system metrics collection"
    fi
fi

# Create monitoring dashboard setup script
echo "📊 Creating dashboard setup script..."
cat > $MONITORING_DIR/setup-dashboard.sh << 'EOF'
#!/bin/bash
# Dashboard setup script
echo "Setting up monitoring dashboard..."

# This script can be extended to:
# 1. Install Grafana
# 2. Import dashboard configuration
# 3. Set up Prometheus
# 4. Configure alerting rules

echo "Dashboard configuration available in monitoring_dashboard.json"
echo "Import this configuration into your monitoring system (Grafana, etc.)"
EOF

chmod +x $MONITORING_DIR/setup-dashboard.sh

# Create monitoring status check script
echo "📋 Creating monitoring status script..."
cat > /usr/local/bin/chatsaas-monitoring-status << EOF
#!/bin/bash
echo "ChatSaaS Monitoring Status"
echo "=========================="
echo

echo "Services:"
systemctl is-active chatsaas-backend || echo "❌ chatsaas-backend: inactive"
systemctl is-active chatsaas-health-monitor.timer || echo "❌ health monitor timer: inactive"

echo
echo "Log files:"
ls -la $LOG_DIR/

echo
echo "Storage:"
df -h $STORAGE_DIR

echo
echo "Recent health check:"
sudo -u $SERVICE_USER /usr/local/bin/chatsaas-health-check | tail -20

echo
echo "Monitoring configuration:"
echo "Config: /etc/chatsaas/monitoring.yml"
echo "Dashboard: $MONITORING_DIR/monitoring_dashboard.json"
echo "Health check: /usr/local/bin/chatsaas-health-check"
EOF

sudo chmod +x /usr/local/bin/chatsaas-monitoring-status

# Start services
echo "🚀 Starting monitoring services..."
sudo systemctl start chatsaas-health-monitor.timer

# Final instructions
echo
echo "✅ ChatSaaS Backend Monitoring Setup Complete!"
echo
echo "Next steps:"
echo "1. Update /etc/chatsaas/monitoring.env with your configuration"
echo "2. Update /etc/chatsaas/monitoring.yml with your alert settings"
echo "3. Set up external monitoring system (Prometheus/Grafana) using monitoring_dashboard.json"
echo "4. Configure email/Slack notifications in monitoring.env"
echo "5. Test health checks: sudo -u $SERVICE_USER /usr/local/bin/chatsaas-health-check"
echo "6. Check monitoring status: chatsaas-monitoring-status"
echo
echo "Health checks will run every 5 minutes automatically."
echo "Logs are available in: $LOG_DIR"
echo "Monitoring config: /etc/chatsaas/"
echo
echo "For dashboard setup, run: $MONITORING_DIR/setup-dashboard.sh"