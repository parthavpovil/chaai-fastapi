# GitHub Secrets Reference

## Overview

This document lists all GitHub Secrets required for the CI/CD pipeline to deploy the ChatSaaS backend to your VPS.

## How to Add Secrets

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Enter the **Name** and **Value**
5. Click **Add secret**

## Required Secrets

### 🔐 VPS Connection Secrets

| Secret Name | Description | Example | How to Get |
|-------------|-------------|---------|------------|
| `VPS_HOST` | VPS IP address or domain name | `123.45.67.89` or `api.yourdomain.com` | Your VPS provider dashboard |
| `VPS_USER` | SSH username for VPS | `root` or `ubuntu` or `deploy` | Your VPS provider (usually `root` or `ubuntu`) |
| `VPS_PASSWORD` | SSH password for VPS | `YourSecurePassword123!` | Your VPS provider or set via `passwd` command |

**Important**: Make sure SSH password authentication is enabled on your VPS:
```bash
# On VPS, edit SSH config
sudo nano /etc/ssh/sshd_config

# Ensure these lines are set:
PasswordAuthentication yes
PermitRootLogin yes  # or 'without-password' if using non-root user

# Restart SSH service
sudo systemctl restart sshd
```

---

### 🗄️ Database Secrets

| Secret Name | Description | Example | How to Get |
|-------------|-------------|---------|------------|
| `POSTGRES_PASSWORD` | PostgreSQL password for Docker container | `MySecureDbPass123!` | Generate a strong password |

**Important**: Your PostgreSQL runs in a Docker container (defined in `docker-compose.prod.yml`), so you only need to set the password.

**Database Configuration** (handled automatically by docker-compose):
- Database name: `chatsaas_prod`
- Username: `chatsaas_user`
- Password: `${POSTGRES_PASSWORD}` (from GitHub Secret)
- Host: `postgres` (Docker container name)
- Port: `5432`

**Full DATABASE_URL** (constructed automatically):
```
postgresql+asyncpg://chatsaas_user:${POSTGRES_PASSWORD}@postgres:5432/chatsaas_prod
```

**Generate a secure password**:
```bash
# Generate a strong password
openssl rand -base64 32
```

---

### 🔑 Security Secrets

| Secret Name | Description | Example | How to Generate |
|-------------|-------------|---------|-----------------|
| `JWT_SECRET_KEY` | Secret key for JWT token signing | `a1b2c3d4e5f6...` (64 chars) | `openssl rand -hex 32` |
| `ENCRYPTION_KEY` | Key for encrypting sensitive data | `0123456789abcdef...` (64 chars) | `openssl rand -hex 32` |

**Generate these keys**:
```bash
# Generate JWT secret key
openssl rand -hex 32

# Generate encryption key
openssl rand -hex 32
```

**Important**: 
- Keep these keys secret and secure
- Never share or commit them to git
- Use different keys for production and development

---

### 🤖 AI Provider Secrets

| Secret Name | Description | Example | How to Get |
|-------------|-------------|---------|------------|
| `OPENAI_API_KEY` | OpenAI API key | `sk-proj-abc123...` | [OpenAI Platform](https://platform.openai.com/api-keys) |
| `ANTHROPIC_API_KEY` | Anthropic (Claude) API key | `sk-ant-api03-xyz...` | [Anthropic Console](https://console.anthropic.com/) |

**How to get OpenAI API key**:
1. Go to https://platform.openai.com/api-keys
2. Sign in or create account
3. Click "Create new secret key"
4. Copy the key (starts with `sk-proj-` or `sk-`)

**How to get Anthropic API key**:
1. Go to https://console.anthropic.com/
2. Sign in or create account
3. Go to API Keys section
4. Create new key
5. Copy the key (starts with `sk-ant-`)

---

### 📧 Email Secrets

| Secret Name | Description | Example | How to Get |
|-------------|-------------|---------|------------|
| `RESEND_API_KEY` | Resend email service API key | `re_Z2zknuN8_HNobuKdcKmTKX3931PXGYbyX` | [Resend Dashboard](https://resend.com/api-keys) |
| `RESEND_FROM_EMAIL` | Email address to send from | `noreply@mail.parthavpovil.in` | Your verified domain in Resend |
| `RESEND_WEBHOOK_SECRET` | Webhook signing secret for verifying webhooks | `whsec_IIekMRhGSxG/hVU32yLUlB+8USEn+klY` | [Resend Webhooks](https://resend.com/webhooks) |

**✅ Your Configuration**:
- API Key: `re_Z2zknuN8_HNobuKdcKmTKX3931PXGYbyX`
- From Email: `noreply@mail.parthavpovil.in`
- Webhook Secret: `whsec_IIekMRhGSxG/hVU32yLUlB+8USEn+klY`
- Domain: `mail.parthavpovil.in` (Verified ✅)

**How to get Resend API key**:
1. Go to https://resend.com/
2. Sign up for account
3. Go to API Keys section
4. Create new API key
5. Copy the key (starts with `re_`)

**How to set up from email**:
1. Add and verify your domain in Resend
2. Use format: `noreply@yourdomain.com` or `support@yourdomain.com`

**How to get webhook secret**:
1. Go to https://resend.com/webhooks
2. Create webhook with your endpoint URL
3. Copy the signing secret (starts with `whsec_`)

---

### 👤 Admin Secrets

| Secret Name | Description | Example | Notes |
|-------------|-------------|---------|-------|
| `SUPER_ADMIN_EMAIL` | Super admin email address | `admin@yourdomain.com` | This email will have full admin access |

**Important**: 
- This email will have super admin privileges
- Create a user account with this email to access admin features
- Keep this email secure

---

### 🔗 Webhook Secrets (Optional)

These are optional and only needed if you're using these channels:

| Secret Name | Description | Example | When Needed |
|-------------|-------------|---------|-------------|
| `TELEGRAM_SECRET_TOKEN` | Telegram webhook secret token | `your_secret_token_123` | When using Telegram channel |
| `WHATSAPP_APP_SECRET` | WhatsApp app secret | `abc123xyz...` | When using WhatsApp channel |
| `INSTAGRAM_APP_SECRET` | Instagram app secret | `def456uvw...` | When using Instagram channel |

---

## Complete Secrets Checklist

Copy this checklist and check off as you add each secret:

### Required (Must Have)
- [x] `VPS_HOST` - Your VPS IP or domain ✅
- [x] `VPS_USER` - SSH username (e.g., `root` or `ubuntu`) ✅
- [x] `VPS_PASSWORD` - SSH password ✅
- [x] `POSTGRES_PASSWORD` - PostgreSQL password for Docker container ✅
- [x] `JWT_SECRET_KEY` - Generated with `openssl rand -hex 32` ✅
- [x] `ENCRYPTION_KEY` - Generated with `openssl rand -hex 32` ✅
- [ ] `GROQ_API_KEY` - From Groq console (ADD THIS NOW!)
- [x] `RESEND_API_KEY` - From Resend dashboard ✅
- [x] `RESEND_FROM_EMAIL` - Your verified email domain ✅
- [x] `RESEND_WEBHOOK_SECRET` - From Resend webhooks ✅
- [x] `SUPER_ADMIN_EMAIL` - Admin email address ✅

### Optional (Add if Needed)
- [ ] `TELEGRAM_SECRET_TOKEN` - If using Telegram
- [ ] `WHATSAPP_APP_SECRET` - If using WhatsApp
- [ ] `INSTAGRAM_APP_SECRET` - If using Instagram

---

## Quick Setup Commands

### 1. Generate Security Keys

```bash
# Generate JWT secret key
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)"

# Generate encryption key
echo "ENCRYPTION_KEY=$(openssl rand -hex 32)"

# Generate PostgreSQL password
echo "POSTGRES_PASSWORD=$(openssl rand -base64 32)"
```

### 2. Test VPS Connection

```bash
# Test SSH connection with password
ssh username@your-vps-ip

# If connection fails, enable password authentication:
# On VPS:
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication yes
sudo systemctl restart sshd
```

### 3. Setup Database

**No manual setup needed!** PostgreSQL runs in a Docker container and is automatically configured by docker-compose.

The database will be created automatically when you deploy. Just make sure you've set the `POSTGRES_PASSWORD` secret in GitHub.

**What happens automatically:**
```bash
# Docker Compose will:
# 1. Pull pgvector/pgvector:pg15 image
# 2. Create database: chatsaas_prod
# 3. Create user: chatsaas_user with your password
# 4. Run init-db.sql to create pgvector extension
# 5. Persist data in Docker volume: postgres_data
```

---

## Example Secrets Configuration

Here's an example of what your secrets might look like (with fake values):

```
VPS_HOST=123.45.67.89
VPS_USER=root
VPS_PASSWORD=MySecureVPSPassword123!

POSTGRES_PASSWORD=DbPass456SecureRandom

JWT_SECRET_KEY=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2
ENCRYPTION_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

OPENAI_API_KEY=sk-proj-abc123xyz789def456ghi012jkl345mno678pqr901stu234vwx567yza890
ANTHROPIC_API_KEY=sk-ant-api03-xyz789abc123def456ghi789jkl012mno345pqr678stu901vwx234

RESEND_API_KEY=re_abc123xyz789
RESEND_FROM_EMAIL=noreply@yourdomain.com

SUPER_ADMIN_EMAIL=admin@yourdomain.com
```

---

## Security Best Practices

1. ✅ **Never commit secrets to git**
2. ✅ **Use strong, unique passwords**
3. ✅ **Rotate keys periodically** (every 90 days)
4. ✅ **Use different keys for dev/staging/production**
5. ✅ **Limit access to GitHub repository**
6. ✅ **Enable 2FA on GitHub account**
7. ✅ **Monitor GitHub Actions logs** for suspicious activity
8. ✅ **Use firewall on VPS** to restrict access

---

## Troubleshooting

### Issue: "Permission denied (publickey,password)"

**Solution**: Enable password authentication on VPS
```bash
# On VPS
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication yes
sudo systemctl restart sshd
```

### Issue: "Database connection failed"

**Solution**: Check POSTGRES_PASSWORD is set correctly
```bash
# The database runs in Docker, so connection issues are usually:
# 1. Wrong POSTGRES_PASSWORD in GitHub Secrets
# 2. Docker container not started
# 3. Check logs: docker logs chatsaas-postgres
```

### Issue: "OpenAI API key invalid"

**Solution**: Verify API key is correct and has credits
- Check https://platform.openai.com/api-keys
- Ensure key starts with `sk-proj-` or `sk-`
- Check billing and usage limits

### Issue: "Resend API key invalid"

**Solution**: Verify API key and domain
- Check https://resend.com/api-keys
- Ensure domain is verified
- Key should start with `re_`

---

## Testing Secrets

After adding all secrets, test the deployment:

1. Go to **Actions** tab in GitHub
2. Select **Deploy to VPS** workflow
3. Click **Run workflow**
4. Select `main` branch
5. Click **Run workflow**

The pipeline will:
- ✅ Run tests
- ✅ Build Docker image
- ✅ Deploy to VPS
- ✅ Run migrations
- ✅ Verify health

If any step fails, check the logs for which secret might be incorrect.

---

## Updating Secrets

To update a secret:

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click on the secret name
3. Click **Update secret**
4. Enter new value
5. Click **Update secret**

**Note**: After updating secrets, you may need to re-run the deployment.

---

## Need Help?

If you're stuck:

1. Check the **Actions** tab for error logs
2. Verify all secrets are added correctly
3. Test VPS connection manually: `ssh user@vps-ip`
4. Test database connection on VPS
5. Verify API keys are valid and have credits

---

## Summary

**Total Required Secrets**: 11
**Optional Secrets**: 3

Once all secrets are configured, your CI/CD pipeline will automatically deploy your application whenever you push to the `main` branch!
