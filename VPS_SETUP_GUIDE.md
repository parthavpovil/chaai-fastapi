# VPS Setup Guide for ChatSaaS Backend

Complete guide to set up your VPS at 84.247.169.119 for deployment.

## Step 1: Initial VPS Setup

SSH into your VPS:
```bash
ssh parkar@84.247.169.119
```

### Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### Install Docker and Docker Compose
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker parkar

# Install Docker Compose
sudo apt install docker-compose -y

# Enable Docker to start on boot
sudo systemctl enable docker
sudo systemctl start docker

# Verify installation
docker --version
docker-compose --version
```

### Install Nginx
```bash
sudo apt install nginx -y
sudo systemctl enable nginx
sudo systemctl start nginx
```

## Step 2: Configure Firewall

```bash
# Install UFW if not installed
sudo apt install ufw -y

# Allow SSH (IMPORTANT - do this first!)
sudo ufw allow 22/tcp

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Check status
sudo ufw status
```

## Step 3: Create Application Directory

```bash
# Create directory structure
sudo mkdir -p /opt/chatsaas
sudo chown parkar:parkar /opt/chatsaas

# Create storage directory
sudo mkdir -p /var/chatsaas/storage
sudo chown parkar:parkar /var/chatsaas/storage

# Create log directory
sudo mkdir -p /var/log/chatsaas
sudo chown parkar:parkar /var/log/chatsaas
```

## Step 4: Set Up SSL with Let's Encrypt

### Install Certbot
```bash
sudo apt install certbot python3-certbot-nginx -y
```

### Obtain SSL Certificate
```bash
# Make sure nginx is running
sudo systemctl status nginx

# Get certificate for both domains
sudo certbot --nginx -d parthavpovil.in -d api.parthavpovil.in

# Follow the prompts:
# - Enter your email address
# - Agree to terms of service
# - Choose whether to redirect HTTP to HTTPS (recommended: Yes)
```

### Test Auto-Renewal
```bash
sudo certbot renew --dry-run
```

## Step 5: Configure Nginx

### Copy nginx configuration
```bash
# The nginx.conf file will be deployed by GitHub Actions
# Or manually copy it:
sudo cp /opt/chatsaas/nginx.conf /etc/nginx/sites-available/chatsaas
sudo ln -s /etc/nginx/sites-available/chatsaas /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

## Step 6: Set Up SSH Key for GitHub Actions

### Generate SSH key pair (on your local machine)
```bash
# Generate new SSH key
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/chatsaas-deploy

# This creates two files:
# - chatsaas-deploy (private key - add to GitHub Secrets)
# - chatsaas-deploy.pub (public key - add to VPS)
```

### Add public key to VPS
```bash
# On your VPS
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Add the public key content to authorized_keys
nano ~/.ssh/authorized_keys
# Paste the content of chatsaas-deploy.pub

chmod 600 ~/.ssh/authorized_keys
```

### Test SSH connection
```bash
# From your local machine
ssh -i ~/.ssh/chatsaas-deploy parkar@84.247.169.119
```

## Step 7: Configure GitHub Secrets

Go to your GitHub repository: https://github.com/parthavpovil/chaai-fastapi

Navigate to: Settings → Secrets and variables → Actions → New repository secret

Add these secrets:

### VPS Connection (4 secrets)
```
VPS_HOST = 84.247.169.119
VPS_USER = parkar
VPS_PORT = 22
VPS_SSH_KEY = <paste content of chatsaas-deploy private key>
```

### Database (2 secrets)
```
POSTGRES_PASSWORD = <generate strong password>
REDIS_PASSWORD = <generate strong password>
```

### Application Security (3 secrets)
```
JWT_SECRET_KEY = <generate 32+ character random string>
ENCRYPTION_KEY = <generate exactly 64 character hex string>
PROCESS_SECRET = <generate 32+ character random string>
```

### AI Provider Keys (at least 1 required)
```
GOOGLE_API_KEY = <your-google-ai-key>
OPENAI_API_KEY = <your-openai-key>
GROQ_API_KEY = <your-groq-key>
```

### Email Service
```
RESEND_API_KEY = <your-resend-api-key>
```

### Admin Configuration
```
SUPER_ADMIN_EMAIL = <your-admin-email>
```

### Optional Channel Secrets
```
TELEGRAM_SECRET_TOKEN = <if-using-telegram>
WHATSAPP_APP_SECRET = <if-using-whatsapp>
INSTAGRAM_APP_SECRET = <if-using-instagram>
```

## Step 8: Generate Secure Keys

### Generate JWT Secret Key (32+ characters)
```bash
openssl rand -base64 32
```

### Generate Encryption Key (exactly 64 hex characters)
```bash
openssl rand -hex 32
```

### Generate Process Secret (32+ characters)
```bash
openssl rand -base64 32
```

### Generate Database Passwords
```bash
openssl rand -base64 24
```

## Step 9: Verify DNS Configuration

```bash
# Check if DNS is working
nslookup api.parthavpovil.in
nslookup parthavpovil.in

# Both should return: 84.247.169.119

# Or use dig
dig api.parthavpovil.in +short
dig parthavpovil.in +short
```

## Step 10: Test Deployment

Once GitHub Actions is set up, you can:

1. Push code to main branch → automatic deployment
2. Or manually trigger deployment from GitHub Actions tab

### Monitor Deployment
```bash
# On VPS, check logs
docker-compose -f /opt/chatsaas/docker-compose.prod.yml logs -f

# Check running containers
docker ps

# Check nginx logs
sudo tail -f /var/log/nginx/api.parthavpovil.in.access.log
sudo tail -f /var/log/nginx/api.parthavpovil.in.error.log
```

### Test API
```bash
# Test health endpoint
curl https://api.parthavpovil.in/health

# Should return: {"status": "healthy"}
```

## Troubleshooting

### Check Docker status
```bash
sudo systemctl status docker
docker ps -a
```

### Check Nginx status
```bash
sudo systemctl status nginx
sudo nginx -t
```

### Check SSL certificate
```bash
sudo certbot certificates
```

### View application logs
```bash
docker-compose -f /opt/chatsaas/docker-compose.prod.yml logs backend
```

### Restart services
```bash
# Restart Docker containers
cd /opt/chatsaas
docker-compose -f docker-compose.prod.yml restart

# Restart Nginx
sudo systemctl restart nginx
```

## Security Checklist

- [ ] Firewall configured (UFW enabled)
- [ ] SSH key authentication set up
- [ ] SSL certificates installed
- [ ] Strong passwords generated for databases
- [ ] GitHub Secrets configured
- [ ] Nginx security headers enabled
- [ ] Regular backups configured
- [ ] Monitoring set up

## Next Steps

After VPS setup is complete:
1. Configure GitHub Actions workflow (will be created in the CI/CD spec)
2. Push code to trigger first deployment
3. Set up monitoring and alerts
4. Configure database backups
5. Set up log rotation

## Maintenance

### Update SSL certificates (automatic with Let's Encrypt)
```bash
sudo certbot renew
```

### Update system packages
```bash
sudo apt update && sudo apt upgrade -y
```

### Clean up Docker
```bash
docker system prune -a
```

### Backup database
```bash
docker exec chatsaas-postgres pg_dump -U chatsaas_user chatsaas_prod > backup_$(date +%Y%m%d).sql
```
