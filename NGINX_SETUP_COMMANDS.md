# Nginx Setup for 084.247.169.119

## Your DNS Setup
- Domain: `084.247.169.119`
- API Subdomain: `api.084.247.169.119`
- IP: `84.247.169.119`

---

## Step 1: Connect to VPS

```bash
ssh root@84.247.169.119
```

---

## Step 2: Install Nginx

```bash
# Install nginx
apt update
apt install -y nginx

# Verify installation
nginx -v
```

---

## Step 3: Create Nginx Configuration

**IMPORTANT**: Copy and paste this ENTIRE block as ONE command:

```bash
cat > /etc/nginx/sites-available/chatsaas << 'ENDOFFILE'
# Nginx configuration for ChatSaaS Backend
# Domain: api.084.247.169.119
# Server IP: 84.247.169.119

# Rate limiting zone
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Upstream backend
upstream backend {
    server localhost:8000;
}

# HTTP server - Main domain
server {
    listen 80;
    listen [::]:80;
    server_name 084.247.169.119 www.084.247.169.119;

    # Redirect to API subdomain
    location / {
        return 301 http://api.084.247.169.119$request_uri;
    }
}

# HTTP server - API subdomain
server {
    listen 80;
    listen [::]:80;
    server_name api.084.247.169.119;

    # Logging
    access_log /var/log/nginx/api.access.log;
    error_log /var/log/nginx/api.error.log;

    # Client settings
    client_max_body_size 10M;
    client_body_timeout 60s;
    client_header_timeout 60s;

    # Proxy settings
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;

    # API endpoints
    location / {
        # Rate limiting
        limit_req zone=api_limit burst=20 nodelay;

        # Proxy to backend
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Buffering
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # Health check endpoint (no rate limiting)
    location /health {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        access_log off;
    }

    # Deny access to hidden files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
ENDOFFILE
```

**Verify the file was created:**
```bash
cat /etc/nginx/sites-available/chatsaas
```

---

## Step 4: Enable the Configuration

```bash
# Remove default nginx site
rm -f /etc/nginx/sites-enabled/default

# Enable our site
ln -sf /etc/nginx/sites-available/chatsaas /etc/nginx/sites-enabled/

# Test nginx configuration
nginx -t
```

**Expected output:**
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

---

## Step 5: Restart Nginx

```bash
# Restart nginx
systemctl restart nginx

# Check status
systemctl status nginx

# Check if nginx is listening
netstat -tlnp | grep :80
```

---

## Step 6: Test the Setup

```bash
# Test from VPS
curl http://localhost

# Should show nginx welcome page or proxy to backend
```

**From your local machine:**
```bash
# Test main domain
curl http://084.247.169.119

# Test API subdomain
curl http://api.084.247.169.119

# Test with your browser
open http://api.084.247.169.119
```

---

## Step 7: Deploy Your Application

Now that Nginx is configured, deploy your application via GitHub Actions or manually.

### Option A: Via GitHub Actions (Recommended)

1. Add GitHub Secrets (if not already done)
2. Push to `main` branch or manually trigger workflow
3. GitHub Actions will deploy everything

### Option B: Manual Deployment

```bash
# Create deployment directory
mkdir -p /var/www/chatsaas
cd /var/www/chatsaas

# You'll need to transfer your files here
# Then run docker-compose
```

---

## Step 8: Verify Everything Works

After deployment:

```bash
# Check if backend is running
docker ps

# Should see:
# - chatsaas-postgres
# - chatsaas-backend

# Test backend directly
curl http://localhost:8000/api/metrics/health/detailed

# Test through nginx
curl http://api.084.247.169.119/api/metrics/health/detailed
```

---

## Troubleshooting

### Nginx won't start

```bash
# Check nginx error log
tail -f /var/log/nginx/error.log

# Check nginx config
nginx -t

# Check if port 80 is already in use
netstat -tlnp | grep :80

# If something else is using port 80, stop it
systemctl stop apache2  # if Apache is running
```

### Can't access from browser

```bash
# Check firewall
ufw status

# Make sure port 80 is open
ufw allow 80/tcp
ufw reload

# Check if nginx is running
systemctl status nginx

# Check nginx logs
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/api.error.log
```

### Backend not responding

```bash
# Check if backend container is running
docker ps | grep chatsaas-backend

# Check backend logs
docker logs chatsaas-backend

# Check if backend is listening on port 8000
netstat -tlnp | grep :8000

# Test backend directly
curl http://localhost:8000/api/metrics/health/detailed
```

### 502 Bad Gateway

This means Nginx can't connect to the backend.

```bash
# Check if backend is running
docker ps | grep chatsaas-backend

# Check backend logs
docker logs chatsaas-backend -f

# Make sure backend is listening on 8000
docker exec chatsaas-backend netstat -tlnp | grep :8000

# Restart backend
cd /var/www/chatsaas
docker-compose -f docker-compose.prod.yml restart backend
```

---

## SSL/HTTPS Setup (Optional - For Later)

Once everything works on HTTP, you can add SSL:

```bash
# Install certbot
apt install -y certbot python3-certbot-nginx

# Get SSL certificate
certbot --nginx -d 084.247.169.119 -d api.084.247.169.119

# Follow prompts, certbot will automatically configure nginx for HTTPS
```

---

## Complete Verification Checklist

- [ ] Nginx installed and running
- [ ] Nginx config created at `/etc/nginx/sites-available/chatsaas`
- [ ] Nginx config enabled (symlink in `/etc/nginx/sites-enabled/`)
- [ ] Nginx config test passes (`nginx -t`)
- [ ] Nginx restarted successfully
- [ ] Port 80 open in firewall
- [ ] Can access `http://084.247.169.119` (redirects to API)
- [ ] Can access `http://api.084.247.169.119`
- [ ] Backend containers running
- [ ] Backend accessible through Nginx

---

## Quick Commands Reference

```bash
# Restart nginx
systemctl restart nginx

# Check nginx status
systemctl status nginx

# Test nginx config
nginx -t

# View nginx logs
tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/api.error.log

# Check what's listening on port 80
netstat -tlnp | grep :80

# Check backend
docker ps
docker logs chatsaas-backend
curl http://localhost:8000/api/metrics/health/detailed
```

---

## Summary

Your Nginx is now configured to:
- ✅ Listen on port 80
- ✅ Serve `api.084.247.169.119`
- ✅ Redirect main domain to API subdomain
- ✅ Proxy requests to backend on port 8000
- ✅ Support WebSockets
- ✅ Rate limit API requests
- ✅ Log all requests

**Next step**: Deploy your application and test!
