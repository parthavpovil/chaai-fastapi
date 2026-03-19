# CI/CD Setup Guide

## Overview

This guide explains how to set up the GitHub Actions CI/CD pipeline for automated deployment of the ChatSaaS backend to your VPS.

## Prerequisites

- GitHub repository with the ChatSaaS backend code
- VPS with Ubuntu 20.04+ and Docker installed
- SSH access to the VPS
- Domain name pointed to your VPS (optional but recommended)

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Actions                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. TEST                                                    │
│     ├── Checkout code                                       │
│     ├── Setup Python                                        │
│     ├── Install dependencies                                │
│     ├── Run linting                                         │
│     └── Run tests                                           │
│                                                             │
│  2. BUILD                                                   │
│     ├── Build Docker image                                  │
│     ├── Tag with commit SHA                                 │
│     └── Upload artifact                                     │
│                                                             │
│  3. DEPLOY                                                  │
│     ├── Download Docker image                               │
│     ├── Transfer to VPS via SSH                             │
│     ├── Run database migrations                             │
│     ├── Deploy with zero-downtime                           │
│     ├── Health check                                        │
│     └── Cleanup old images                                  │
│                                                             │
│  4. NOTIFY                                                  │
│     └── Send deployment status                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Step 1: VPS Preparation

### 1.1 Install Docker and Docker Compose

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version
```

### 1.2 Install Nginx

```bash
sudo apt install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 1.3 Create Deployment Directory

```bash
sudo mkdir -p /var/www/chatsaas
sudo mkdir -p /var/chatsaas/storage
sudo chown -R $USER:$USER /var/www/chatsaas
sudo chown -R $USER:$USER /var/chatsaas
```

### 1.4 Setup PostgreSQL with pgvector

```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib -y

# Install pgvector
sudo apt install postgresql-16-pgvector -y

# Create database and user
sudo -u postgres psql << EOF
CREATE DATABASE chatsaas;
CREATE USER chatsaas_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE chatsaas TO chatsaas_user;
\c chatsaas
CREATE EXTENSION IF NOT EXISTS vector;
EOF
```

## Step 2: SSH Key Setup

### 2.1 Generate SSH Key Pair

On your local machine:

```bash
# Generate SSH key for deployment
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy_key

# This creates:
# - ~/.ssh/github_deploy_key (private key - for GitHub Secrets)
# - ~/.ssh/github_deploy_key.pub (public key - for VPS)
```

### 2.2 Add Public Key to VPS

```bash
# Copy public key to VPS
ssh-copy-id -i ~/.ssh/github_deploy_key.pub user@your-vps-ip

# Or manually:
cat ~/.ssh/github_deploy_key.pub | ssh user@your-vps-ip "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

### 2.3 Test SSH Connection

```bash
ssh -i ~/.ssh/github_deploy_key user@your-vps-ip
```

## Step 3: GitHub Secrets Configuration

Go to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

Add the following secrets:

### Required Secrets

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `SSH_PRIVATE_KEY` | Private SSH key content | Contents of `~/.ssh/github_deploy_key` |
| `VPS_HOST` | VPS IP address or domain | `123.45.67.89` or `api.yourdomain.com` |
| `VPS_USER` | SSH username | `ubuntu` or `deploy` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost:5432/chatsaas` |
| `JWT_SECRET_KEY` | JWT signing key | Generate with `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | Data encryption key | Generate with `openssl rand -hex 32` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key | `sk-ant-...` |
| `RESEND_API_KEY` | Resend email API key | `re_...` |
| `RESEND_FROM_EMAIL` | From email address | `noreply@yourdomain.com` |
| `SUPER_ADMIN_EMAIL` | Super admin email | `admin@yourdomain.com` |

### Optional Secrets

| Secret Name | Description |
|-------------|-------------|
| `TELEGRAM_SECRET_TOKEN` | Telegram webhook secret |
| `WHATSAPP_APP_SECRET` | WhatsApp app secret |
| `INSTAGRAM_APP_SECRET` | Instagram app secret |

### How to Add Secrets

1. Go to repository Settings
2. Click "Secrets and variables" → "Actions"
3. Click "New repository secret"
4. Enter name and value
5. Click "Add secret"

## Step 4: Environment Configuration

### 4.1 Generate Required Keys

```bash
# Generate JWT secret key
openssl rand -hex 32

# Generate encryption key (must be 64 hex characters)
openssl rand -hex 32
```

### 4.2 Database URL Format

```
postgresql+asyncpg://username:password@host:port/database
```

Example:
```
postgresql+asyncpg://chatsaas_user:your_password@localhost:5432/chatsaas
```

## Step 5: Nginx Configuration

The pipeline will automatically deploy the nginx configuration, but you can manually set it up:

```bash
# Create nginx config
sudo nano /etc/nginx/sites-available/chatsaas

# Paste the content from backend/nginx.conf

# Enable site
sudo ln -s /etc/nginx/sites-available/chatsaas /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

## Step 6: SSL Certificate (Optional but Recommended)

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain certificate
sudo certbot --nginx -d yourdomain.com -d api.yourdomain.com

# Auto-renewal is configured automatically
```

## Step 7: Testing the Pipeline

### 7.1 Manual Trigger

1. Go to GitHub repository → Actions
2. Select "Deploy to VPS" workflow
3. Click "Run workflow"
4. Select branch (main)
5. Click "Run workflow"

### 7.2 Automatic Trigger

Push code to the main branch:

```bash
git add .
git commit -m "Test CI/CD pipeline"
git push origin main
```

The pipeline will automatically:
1. Run tests
2. Build Docker image
3. Deploy to VPS
4. Verify deployment

## Step 8: Monitoring Deployments

### 8.1 View Workflow Runs

1. Go to GitHub repository → Actions
2. Click on a workflow run to see details
3. View logs for each step

### 8.2 Check Deployment Status on VPS

```bash
# SSH into VPS
ssh user@your-vps-ip

# Check running containers
docker ps

# View container logs
docker logs chatsaas-backend

# Check application health
curl http://localhost:8000/api/metrics/health/detailed
```

## Step 9: Rollback Procedure

If a deployment fails or causes issues:

### 9.1 Using Rollback Workflow

1. Go to GitHub repository → Actions
2. Select "Rollback Deployment" workflow
3. Click "Run workflow"
4. Enter:
   - **Commit SHA**: The commit hash to rollback to
   - **Reason**: Why you're rolling back
5. Click "Run workflow"

### 9.2 Finding Commit SHA

```bash
# View recent commits
git log --oneline -10

# Or on GitHub: Repository → Commits
```

### 9.3 Manual Rollback on VPS

```bash
# SSH into VPS
ssh user@your-vps-ip

# View available Docker images
docker images chatsaas-backend

# Tag desired version as latest
docker tag chatsaas-backend:abc1234 chatsaas-backend:latest

# Restart containers
cd /var/www/chatsaas
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

## Troubleshooting

### Issue: Tests Failing

**Solution**: Check test logs in GitHub Actions

```bash
# Run tests locally
cd backend
pytest tests/ -v
```

### Issue: SSH Connection Failed

**Solution**: Verify SSH key and VPS access

```bash
# Test SSH connection
ssh -i ~/.ssh/github_deploy_key user@your-vps-ip

# Check SSH key in GitHub Secrets
# Ensure it includes "-----BEGIN OPENSSH PRIVATE KEY-----" header
```

### Issue: Docker Build Failed

**Solution**: Check Dockerfile and dependencies

```bash
# Build locally
cd backend
docker build -t chatsaas-backend:test .
```

### Issue: Health Check Failed

**Solution**: Check application logs

```bash
# On VPS
docker logs chatsaas-backend

# Check if database is accessible
docker exec chatsaas-backend python -c "from app.database import engine; print('DB OK')"
```

### Issue: Database Migration Failed

**Solution**: Check migration files and database connection

```bash
# On VPS
cd /var/www/chatsaas
docker-compose -f docker-compose.prod.yml run --rm backend alembic current
docker-compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

## Security Best Practices

1. **Never commit secrets** to the repository
2. **Use strong passwords** for database and JWT keys
3. **Enable firewall** on VPS:
   ```bash
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   ```
4. **Keep Docker images clean** - pipeline automatically removes old images
5. **Monitor logs** regularly for suspicious activity
6. **Use SSL/TLS** for production deployments
7. **Restrict SSH access** to specific IP addresses if possible

## Maintenance

### Update Dependencies

```bash
# Update Python packages
cd backend
pip install --upgrade -r requirements.txt
pip freeze > requirements.txt

# Commit and push
git add requirements.txt
git commit -m "Update dependencies"
git push origin main
```

### Clean Up Old Docker Images

The pipeline automatically keeps the last 3 images. Manual cleanup:

```bash
# On VPS
docker image prune -a --filter "until=720h"  # Remove images older than 30 days
```

### Database Backups

```bash
# Create backup script
sudo nano /usr/local/bin/backup-chatsaas-db.sh

# Add:
#!/bin/bash
BACKUP_DIR="/var/backups/chatsaas"
mkdir -p $BACKUP_DIR
pg_dump -U chatsaas_user chatsaas | gzip > $BACKUP_DIR/chatsaas_$(date +%Y%m%d_%H%M%S).sql.gz

# Make executable
sudo chmod +x /usr/local/bin/backup-chatsaas-db.sh

# Add to crontab (daily at 2 AM)
crontab -e
# Add: 0 2 * * * /usr/local/bin/backup-chatsaas-db.sh
```

## Pipeline Features

✅ **Automated Testing** - Runs full test suite before deployment
✅ **Zero-Downtime Deployment** - New container starts before old one stops
✅ **Health Checks** - Verifies application is running correctly
✅ **Database Migrations** - Automatically runs Alembic migrations
✅ **Rollback Support** - Easy rollback to previous versions
✅ **Docker Image Tagging** - Tags images with commit SHA for version tracking
✅ **Automatic Cleanup** - Removes old Docker images
✅ **Deployment Logs** - Detailed logs for troubleshooting
✅ **Manual Triggers** - Can manually trigger deployments
✅ **Path Filtering** - Only deploys when backend code changes

## Next Steps

1. ✅ Set up VPS and install dependencies
2. ✅ Configure GitHub Secrets
3. ✅ Test SSH connection
4. ✅ Run first deployment
5. ✅ Set up SSL certificate
6. ✅ Configure monitoring
7. ✅ Set up database backups
8. ✅ Document your deployment process

## Support

For issues or questions:
- Check GitHub Actions logs
- Review VPS logs: `docker logs chatsaas-backend`
- Check nginx logs: `sudo tail -f /var/log/nginx/error.log`
- Verify database connection
- Test health endpoint: `curl http://localhost:8000/api/metrics/health/detailed`
