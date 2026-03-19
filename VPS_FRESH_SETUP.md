# Fresh VPS Setup - Complete Guide

## Prerequisites
- Fresh Ubuntu VPS (20.04 or 22.04)
- Root access
- Your local machine with SSH

---

## Step 1: Connect to VPS

```bash
# From your local machine
ssh-keygen -R 84.247.169.119  # Remove old key
ssh root@84.247.169.119       # Connect (enter password)
```

---

## Step 2: Update System

```bash
# Update package list
apt update

# Upgrade all packages
apt upgrade -y

# Install basic utilities
apt install -y curl wget git vim nano ufw
```

---

## Step 3: Configure SSH (Keep Password Login Enabled)

```bash
# Backup SSH config
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

# Edit SSH config
nano /etc/ssh/sshd_config
```

**Find and set these values** (use Ctrl+W to search):

```
Port 22
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
ChallengeResponseAuthentication yes
UsePAM yes
```

**Save and exit**: Ctrl+X, then Y, then Enter

```bash
# Restart SSH
systemctl restart sshd

# Verify SSH is running
systemctl status sshd
```

---

## Step 4: Configure Firewall

```bash
# Allow SSH
ufw allow 22/tcp

# Allow HTTP
ufw allow 80/tcp

# Allow HTTPS
ufw allow 443/tcp

# Enable firewall (will ask for confirmation, type 'y')
ufw enable

# Check status
ufw status
```

**Expected output:**
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                     ALLOW       Anywhere
```

---

## Step 5: Install Docker

```bash
# Remove old Docker versions (if any)
apt remove -y docker docker-engine docker.io containerd runc

# Install prerequisites
apt install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up Docker repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Update package list
apt update

# Install Docker
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Start Docker
systemctl start docker
systemctl enable docker

# Verify Docker installation
docker --version
docker compose version
```

**Expected output:**
```
Docker version 24.x.x
Docker Compose version v2.x.x
```

---

## Step 6: Install Nginx

```bash
# Install Nginx
apt install -y nginx

# Start Nginx
systemctl start nginx
systemctl enable nginx

# Check status
systemctl status nginx
```

**Test**: Open `http://84.247.169.119` in your browser - you should see "Welcome to nginx!"

---

## Step 7: Create Deployment Directory

```bash
# Create directory
mkdir -p /var/www/chatsaas

# Set permissions
chown -R root:root /var/www/chatsaas
chmod -R 755 /var/www/chatsaas

# Create storage directory
mkdir -p /var/chatsaas/storage
chown -R root:root /var/chatsaas
chmod -R 755 /var/chatsaas

# Verify
ls -la /var/www/
ls -la /var/chatsaas/
```

---

## Step 8: Test Docker

```bash
# Run test container
docker run hello-world

# Should see: "Hello from Docker!"

# Clean up test container
docker rm $(docker ps -aq)
```

---

## Step 9: Verify Everything

```bash
# Check Docker
docker --version
docker compose version

# Check Nginx
nginx -v
systemctl status nginx

# Check firewall
ufw status

# Check SSH config
grep "PasswordAuthentication" /etc/ssh/sshd_config
grep "PermitRootLogin" /etc/ssh/sshd_config

# Check directories
ls -la /var/www/chatsaas
ls -la /var/chatsaas/storage
```

---

## Step 10: Set Up GitHub Actions Deployment

Your VPS is now ready! Now configure GitHub Secrets:

### Required GitHub Secrets:

1. **VPS_HOST**: `84.247.169.119`
2. **VPS_USER**: `root`
3. **VPS_PASSWORD**: Your root password
4. **POSTGRES_PASSWORD**: Generate with `openssl rand -base64 32`
5. **JWT_SECRET_KEY**: Generate with `openssl rand -hex 32`
6. **ENCRYPTION_KEY**: Generate with `openssl rand -hex 32`
7. **OPENAI_API_KEY**: Your OpenAI API key
8. **ANTHROPIC_API_KEY**: Your Anthropic API key
9. **RESEND_API_KEY**: Your Resend API key
10. **RESEND_FROM_EMAIL**: Your email (e.g., `noreply@yourdomain.com`)
11. **SUPER_ADMIN_EMAIL**: Your admin email

### Generate Secrets:

```bash
# On your local machine, generate these:
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)"
```

Copy these values and add them to GitHub Secrets.

---

## Step 11: Deploy from GitHub Actions

1. Go to your GitHub repository
2. Click **Actions** tab
3. Select **Deploy to VPS** workflow
4. Click **Run workflow**
5. Select `main` branch
6. Click **Run workflow**

GitHub Actions will:
- ✅ Run tests
- ✅ Build Docker image
- ✅ Transfer to VPS
- ✅ Start PostgreSQL container
- ✅ Run migrations
- ✅ Start backend container
- ✅ Configure Nginx
- ✅ Deploy!

---

## Step 12: Verify Deployment

After GitHub Actions completes:

```bash
# On VPS, check containers
docker ps

# Should see:
# - chatsaas-postgres
# - chatsaas-backend
# - chatsaas-nginx (if using docker-compose nginx)

# Check logs
docker logs chatsaas-backend
docker logs chatsaas-postgres

# Test API
curl http://localhost:8000/api/metrics/health/detailed
```

---

## Troubleshooting

### If Docker containers aren't running:

```bash
# Check what's running
docker ps -a

# Check logs
docker logs chatsaas-backend
docker logs chatsaas-postgres

# Restart containers
cd /var/www/chatsaas
docker-compose -f docker-compose.prod.yml restart
```

### If Nginx isn't working:

```bash
# Check Nginx status
systemctl status nginx

# Check Nginx config
nginx -t

# Restart Nginx
systemctl restart nginx

# Check logs
tail -f /var/log/nginx/error.log
```

### If SSH password login stops working:

```bash
# Check SSH config
grep "PasswordAuthentication" /etc/ssh/sshd_config

# Should show: PasswordAuthentication yes

# If not, edit:
nano /etc/ssh/sshd_config
# Set: PasswordAuthentication yes
# Save and restart:
systemctl restart sshd
```

---

## Summary

Your VPS is now configured with:
- ✅ Ubuntu updated
- ✅ SSH with password login enabled
- ✅ Firewall configured (ports 22, 80, 443)
- ✅ Docker installed
- ✅ Docker Compose installed
- ✅ Nginx installed
- ✅ Deployment directories created
- ✅ Ready for GitHub Actions deployment

**Next step**: Add GitHub Secrets and run the deployment workflow!

---

## Quick Reference Commands

```bash
# Check Docker
docker ps
docker logs chatsaas-backend

# Check Nginx
systemctl status nginx
nginx -t

# Check firewall
ufw status

# Restart services
systemctl restart docker
systemctl restart nginx
systemctl restart sshd

# View logs
docker logs chatsaas-backend -f
docker logs chatsaas-postgres -f
tail -f /var/log/nginx/error.log
```

---

## Security Notes

- ✅ Firewall is enabled (only ports 22, 80, 443 open)
- ✅ SSH password login is enabled (for GitHub Actions)
- ⚠️ Consider adding fail2ban for brute force protection
- ⚠️ Consider changing SSH port from 22 to something else
- ⚠️ Consider setting up SSL/TLS certificates (Let's Encrypt)

**For production, also consider:**
```bash
# Install fail2ban (blocks brute force attacks)
apt install -y fail2ban
systemctl enable fail2ban
systemctl start fail2ban
```

---

## Done! 🚀

Your VPS is ready for deployment. Push to `main` branch or manually trigger the GitHub Actions workflow!
