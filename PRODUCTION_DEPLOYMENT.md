# ChatSaaS Backend - Production Deployment Guide

This guide provides comprehensive instructions for deploying the ChatSaaS Backend to a production environment.

## Prerequisites

### System Requirements

- **Operating System:** Ubuntu 20.04+ or CentOS 8+ (recommended)
- **CPU:** 2+ cores
- **RAM:** 4GB minimum, 8GB recommended
- **Storage:** 50GB minimum, SSD recommended
- **Network:** Static IP address with domain name

### Software Requirements

- **Python:** 3.12+
- **PostgreSQL:** 15+ with pgvector extension
- **Nginx:** 1.18+
- **SSL Certificate:** Let's Encrypt or commercial certificate

## Deployment Options

### Option 1: Traditional Server Deployment

#### 1. Server Preparation

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3 python3-pip python3-venv nginx postgresql-15 postgresql-contrib git curl

# Install pgvector extension
sudo apt install -y postgresql-15-pgvector
```

#### 2. Database Setup

```bash
# Switch to postgres user
sudo -u postgres psql

# Create database and user
CREATE DATABASE chatsaas_prod;
CREATE USER chatsaas_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE chatsaas_prod TO chatsaas_user;

# Enable pgvector extension
\c chatsaas_prod
CREATE EXTENSION vector;
\q
```

#### 3. Application Deployment

```bash
# Clone repository
git clone https://github.com/your-org/chatsaas-backend.git
cd chatsaas-backend/backend

# Run deployment script
chmod +x deploy.sh
./deploy.sh
```

#### 4. Environment Configuration

```bash
# Copy and configure environment file
sudo cp .env.production /opt/chatsaas/backend/.env
sudo nano /opt/chatsaas/backend/.env

# Generate secure keys
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('ENCRYPTION_KEY=' + secrets.token_hex(32))"
python3 -c "import secrets; print('PROCESS_SECRET=' + secrets.token_urlsafe(32))"
```

#### 5. SSL Certificate Setup

Follow the [SSL_SETUP.md](SSL_SETUP.md) guide to configure SSL certificates.

#### 6. Service Management

```bash
# Start services
sudo systemctl start chatsaas-backend
sudo systemctl start nginx

# Enable auto-start
sudo systemctl enable chatsaas-backend
sudo systemctl enable nginx

# Check status
sudo systemctl status chatsaas-backend
sudo systemctl status nginx
```

### Option 2: Docker Deployment

#### 1. Install Docker and Docker Compose

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

#### 2. Prepare Environment

```bash
# Create environment file
cp .env.production .env

# Edit environment variables
nano .env

# Create SSL certificate directory
mkdir -p ssl
# Place your SSL certificates in the ssl/ directory
```

#### 3. Deploy with Docker Compose

```bash
# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check logs
docker-compose -f docker-compose.prod.yml logs -f

# Run database migrations
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Configuration

### Environment Variables

Key environment variables that must be configured:

```bash
# Application
DEBUG=false
APP_URL=https://your-domain.com
ALLOWED_ORIGINS=["https://your-frontend-domain.com"]

# Database
DATABASE_URL=postgresql+asyncpg://chatsaas_user:password@localhost:5432/chatsaas_prod

# Security
JWT_SECRET_KEY=your-secure-jwt-secret
ENCRYPTION_KEY=your-64-character-hex-key
PROCESS_SECRET=your-secure-process-secret

# AI Providers (configure at least one)
GOOGLE_API_KEY=your-google-api-key
OPENAI_API_KEY=your-openai-api-key
GROQ_API_KEY=your-groq-api-key

# Email
RESEND_API_KEY=your-resend-api-key
RESEND_FROM_EMAIL=noreply@your-domain.com

# Administration
SUPER_ADMIN_EMAIL=admin@your-domain.com
```

### Nginx Configuration

The provided `nginx.conf` includes:
- SSL/TLS termination
- Rate limiting
- Security headers
- WebSocket support
- Static file serving
- Health check endpoints

Update the following in `nginx.conf`:
- Replace `your-domain.com` with your actual domain
- Update SSL certificate paths
- Adjust rate limiting if needed

### Gunicorn Configuration

The `gunicorn.conf.py` is optimized for production with:
- Worker count based on CPU cores
- Uvicorn workers for async support
- Proper timeouts and limits
- Process management
- Logging configuration

## Security Hardening

### 1. Firewall Configuration

```bash
# UFW (Ubuntu)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Check status
sudo ufw status
```

### 2. Fail2Ban Setup

```bash
# Install fail2ban
sudo apt install fail2ban

# Configure for nginx
sudo nano /etc/fail2ban/jail.local
```

Add to `/etc/fail2ban/jail.local`:
```ini
[nginx-http-auth]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log

[nginx-limit-req]
enabled = true
port = http,https
logpath = /var/log/nginx/error.log
maxretry = 10
```

### 3. System Updates

```bash
# Enable automatic security updates
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 4. Log Monitoring

Set up log monitoring and alerting:
- Application logs: `/var/log/chatsaas/`
- Nginx logs: `/var/log/nginx/`
- System logs: `/var/log/syslog`

## Monitoring and Maintenance

### Health Checks

The application provides several health check endpoints:

- `GET /health` - Basic application health
- Database connectivity is checked during startup
- WebSocket connections are monitored

### Log Management

```bash
# View application logs
sudo journalctl -u chatsaas-backend -f

# View nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Rotate logs
sudo logrotate -f /etc/logrotate.conf
```

### Database Maintenance

```bash
# Backup database
sudo -u postgres pg_dump chatsaas_prod > backup_$(date +%Y%m%d_%H%M%S).sql

# Vacuum and analyze
sudo -u postgres psql -d chatsaas_prod -c "VACUUM ANALYZE;"

# Check database size
sudo -u postgres psql -d chatsaas_prod -c "SELECT pg_size_pretty(pg_database_size('chatsaas_prod'));"
```

### Performance Monitoring

Monitor these key metrics:
- CPU and memory usage
- Database connections and query performance
- Response times and error rates
- WebSocket connection counts
- File storage usage

## Scaling Considerations

### Horizontal Scaling

To scale horizontally:

1. **Load Balancer:** Add a load balancer (HAProxy, AWS ALB, etc.)
2. **Multiple App Instances:** Run multiple backend instances
3. **Shared Storage:** Use shared storage for file uploads
4. **Database Scaling:** Consider read replicas for database scaling

### Vertical Scaling

For vertical scaling:
- Increase server resources (CPU, RAM)
- Adjust Gunicorn worker count
- Optimize database configuration
- Tune Nginx worker processes

## Backup and Recovery

### Automated Backups

Create backup script `/usr/local/bin/backup-chatsaas.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/chatsaas"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Database backup
sudo -u postgres pg_dump chatsaas_prod | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# File storage backup
tar -czf $BACKUP_DIR/storage_$DATE.tar.gz /var/chatsaas/storage/

# Configuration backup
tar -czf $BACKUP_DIR/config_$DATE.tar.gz /opt/chatsaas/backend/.env /etc/nginx/sites-available/chatsaas

# Clean old backups (keep 7 days)
find $BACKUP_DIR -name "*.gz" -mtime +7 -delete

echo "Backup completed: $DATE"
```

Add to crontab:
```bash
# Daily backup at 2 AM
0 2 * * * /usr/local/bin/backup-chatsaas.sh
```

### Recovery Procedures

1. **Database Recovery:**
   ```bash
   sudo -u postgres psql -d chatsaas_prod < backup.sql
   ```

2. **File Storage Recovery:**
   ```bash
   tar -xzf storage_backup.tar.gz -C /
   ```

3. **Configuration Recovery:**
   ```bash
   tar -xzf config_backup.tar.gz -C /
   ```

## Troubleshooting

### Common Issues

1. **Service Won't Start:**
   ```bash
   sudo journalctl -u chatsaas-backend -n 50
   sudo systemctl status chatsaas-backend
   ```

2. **Database Connection Issues:**
   ```bash
   sudo -u postgres psql -d chatsaas_prod -c "SELECT 1;"
   ```

3. **SSL Certificate Issues:**
   ```bash
   sudo nginx -t
   openssl x509 -in /etc/ssl/certs/chatsaas.crt -text -noout
   ```

4. **High Memory Usage:**
   ```bash
   ps aux --sort=-%mem | head
   sudo systemctl restart chatsaas-backend
   ```

### Log Analysis

Key log patterns to monitor:
- Database connection errors
- AI provider API failures
- WebSocket connection issues
- Rate limiting violations
- SSL/TLS handshake failures

## Support and Maintenance

### Regular Maintenance Tasks

- **Weekly:** Review logs and performance metrics
- **Monthly:** Update system packages and dependencies
- **Quarterly:** Review and rotate SSL certificates
- **Annually:** Security audit and penetration testing

### Emergency Procedures

1. **Service Outage:**
   - Check service status
   - Review recent logs
   - Restart services if needed
   - Notify stakeholders

2. **Database Issues:**
   - Check database connectivity
   - Review query performance
   - Consider read-only mode if needed

3. **Security Incident:**
   - Isolate affected systems
   - Review access logs
   - Update credentials if compromised
   - Document incident for review

For additional support, refer to the application logs and monitoring dashboards.