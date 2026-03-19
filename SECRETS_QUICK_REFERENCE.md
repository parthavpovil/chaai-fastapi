# GitHub Secrets Quick Reference

## 📋 Required Secrets (11 Total)

### 🖥️ VPS Connection (3)
```
VPS_HOST          = 123.45.67.89 (or api.yourdomain.com)
VPS_USER          = root (or ubuntu)
VPS_PASSWORD      = YourVPSPassword123
```

### 🗄️ Database (1)
```
POSTGRES_PASSWORD = YourSecureDbPassword123
```
*Note: PostgreSQL runs in Docker container, no manual setup needed*

### 🔐 Security (2)
```
JWT_SECRET_KEY    = [Run: openssl rand -hex 32]
ENCRYPTION_KEY    = [Run: openssl rand -hex 32]
```

### 🤖 AI Providers (2)
```
OPENAI_API_KEY    = sk-proj-... (from platform.openai.com)
ANTHROPIC_API_KEY = sk-ant-... (from console.anthropic.com)
```

### 📧 Email (2)
```
RESEND_API_KEY    = re_... (from resend.com)
RESEND_FROM_EMAIL = noreply@yourdomain.com
```

### 👤 Admin (1)
```
SUPER_ADMIN_EMAIL = admin@yourdomain.com
```

---

## 🔧 Optional Secrets (3)

```
TELEGRAM_SECRET_TOKEN   = (if using Telegram)
WHATSAPP_APP_SECRET     = (if using WhatsApp)
INSTAGRAM_APP_SECRET    = (if using Instagram)
```

---

## ⚡ Quick Setup

### 1. Generate Keys
```bash
openssl rand -hex 32      # For JWT_SECRET_KEY
openssl rand -hex 32      # For ENCRYPTION_KEY
openssl rand -base64 32   # For POSTGRES_PASSWORD
```

### 2. Enable SSH Password on VPS
```bash
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication yes
sudo systemctl restart sshd
```

### 3. Database Setup
**No manual setup needed!** PostgreSQL runs in Docker and is configured automatically.

Just set the `POSTGRES_PASSWORD` secret in GitHub.

### 4. Add Secrets to GitHub
1. Go to: **Repository → Settings → Secrets and variables → Actions**
2. Click: **New repository secret**
3. Add each secret from the list above

### 5. Deploy
```bash
git push origin main
```
Or manually trigger from **Actions** tab.

---

## ✅ Checklist

- [ ] VPS_HOST
- [ ] VPS_USER
- [ ] VPS_PASSWORD
- [ ] POSTGRES_PASSWORD
- [ ] JWT_SECRET_KEY
- [ ] ENCRYPTION_KEY
- [ ] OPENAI_API_KEY
- [ ] ANTHROPIC_API_KEY
- [ ] RESEND_API_KEY
- [ ] RESEND_FROM_EMAIL
- [ ] SUPER_ADMIN_EMAIL

---

## 🔗 Useful Links

- OpenAI API Keys: https://platform.openai.com/api-keys
- Anthropic Console: https://console.anthropic.com/
- Resend Dashboard: https://resend.com/api-keys

---

## 📖 Full Documentation

See `GITHUB_SECRETS_REFERENCE.md` for detailed explanations and troubleshooting.
