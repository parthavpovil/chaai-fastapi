# SSL/TLS Configuration for ChatSaaS Backend

This document provides instructions for setting up SSL/TLS certificates for secure HTTPS communication.

## Option 1: Let's Encrypt (Recommended for Production)

Let's Encrypt provides free SSL certificates with automatic renewal.

### Prerequisites
- Domain name pointing to your server
- Nginx installed and configured
- Port 80 and 443 open in firewall

### Installation

1. **Install Certbot:**
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install certbot python3-certbot-nginx
   
   # CentOS/RHEL
   sudo yum install certbot python3-certbot-nginx
   ```

2. **Obtain SSL Certificate:**
   ```bash
   sudo certbot --nginx -d your-domain.com -d www.your-domain.com
   ```

3. **Test Automatic Renewal:**
   ```bash
   sudo certbot renew --dry-run
   ```

4. **Update Nginx Configuration:**
   The nginx.conf file is already configured for SSL. Update the certificate paths:
   ```nginx
   ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
   ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
   ```

## Option 2: Self-Signed Certificates (Development/Testing)

For development or internal testing environments.

### Generate Self-Signed Certificate

```bash
# Create SSL directory
sudo mkdir -p /etc/ssl/private /etc/ssl/certs

# Generate private key
sudo openssl genrsa -out /etc/ssl/private/chatsaas.key 2048

# Generate certificate signing request
sudo openssl req -new -key /etc/ssl/private/chatsaas.key -out /tmp/chatsaas.csr

# Generate self-signed certificate (valid for 365 days)
sudo openssl x509 -req -days 365 -in /tmp/chatsaas.csr -signkey /etc/ssl/private/chatsaas.key -out /etc/ssl/certs/chatsaas.crt

# Set proper permissions
sudo chmod 600 /etc/ssl/private/chatsaas.key
sudo chmod 644 /etc/ssl/certs/chatsaas.crt

# Clean up
sudo rm /tmp/chatsaas.csr
```

## Option 3: Commercial SSL Certificate

If you have a commercial SSL certificate from a Certificate Authority:

1. **Upload Certificate Files:**
   ```bash
   sudo cp your-certificate.crt /etc/ssl/certs/chatsaas.crt
   sudo cp your-private-key.key /etc/ssl/private/chatsaas.key
   sudo cp ca-bundle.crt /etc/ssl/certs/ca-bundle.crt
   ```

2. **Set Permissions:**
   ```bash
   sudo chmod 600 /etc/ssl/private/chatsaas.key
   sudo chmod 644 /etc/ssl/certs/chatsaas.crt
   sudo chmod 644 /etc/ssl/certs/ca-bundle.crt
   ```

3. **Update Nginx Configuration:**
   ```nginx
   ssl_certificate /etc/ssl/certs/chatsaas.crt;
   ssl_certificate_key /etc/ssl/private/chatsaas.key;
   ssl_trusted_certificate /etc/ssl/certs/ca-bundle.crt;
   ```

## SSL Configuration Verification

### Test SSL Configuration

1. **Test Nginx Configuration:**
   ```bash
   sudo nginx -t
   ```

2. **Reload Nginx:**
   ```bash
   sudo systemctl reload nginx
   ```

3. **Test SSL Certificate:**
   ```bash
   # Check certificate details
   openssl x509 -in /etc/ssl/certs/chatsaas.crt -text -noout
   
   # Test SSL connection
   openssl s_client -connect your-domain.com:443 -servername your-domain.com
   ```

4. **Online SSL Test:**
   - Use [SSL Labs SSL Test](https://www.ssllabs.com/ssltest/) to verify your SSL configuration
   - Should achieve A+ rating with the provided configuration

### Security Headers Verification

Test security headers using curl:

```bash
curl -I https://your-domain.com/health
```

Expected headers:
- `Strict-Transport-Security`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection`
- `Content-Security-Policy`

## Firewall Configuration

Ensure proper firewall rules are in place:

```bash
# UFW (Ubuntu)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# iptables
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables-save > /etc/iptables/rules.v4
```

## Monitoring SSL Certificate Expiration

### Automated Monitoring Script

Create a monitoring script to check certificate expiration:

```bash
#!/bin/bash
# /usr/local/bin/check-ssl-expiry.sh

DOMAIN="your-domain.com"
THRESHOLD_DAYS=30

EXPIRY_DATE=$(openssl s_client -connect $DOMAIN:443 -servername $DOMAIN 2>/dev/null | openssl x509 -noout -dates | grep notAfter | cut -d= -f2)
EXPIRY_TIMESTAMP=$(date -d "$EXPIRY_DATE" +%s)
CURRENT_TIMESTAMP=$(date +%s)
DAYS_UNTIL_EXPIRY=$(( ($EXPIRY_TIMESTAMP - $CURRENT_TIMESTAMP) / 86400 ))

if [ $DAYS_UNTIL_EXPIRY -lt $THRESHOLD_DAYS ]; then
    echo "WARNING: SSL certificate for $DOMAIN expires in $DAYS_UNTIL_EXPIRY days"
    # Send alert email or notification
fi
```

### Cron Job for Monitoring

```bash
# Add to crontab (crontab -e)
0 6 * * * /usr/local/bin/check-ssl-expiry.sh
```

## Troubleshooting

### Common Issues

1. **Certificate Chain Issues:**
   - Ensure you're using the full certificate chain
   - For Let's Encrypt, use `fullchain.pem` not `cert.pem`

2. **Permission Issues:**
   - Nginx user must be able to read certificate files
   - Private key should be readable only by root/nginx

3. **Mixed Content Warnings:**
   - Ensure all resources are loaded over HTTPS
   - Update any hardcoded HTTP URLs in your application

4. **Certificate Mismatch:**
   - Certificate must match the domain name exactly
   - Include both www and non-www versions if needed

### Log Files

Check these log files for SSL-related issues:
- `/var/log/nginx/error.log`
- `/var/log/nginx/access.log`
- `/var/log/letsencrypt/letsencrypt.log` (if using Let's Encrypt)

## Security Best Practices

1. **Use Strong Ciphers:** The provided nginx configuration uses secure cipher suites
2. **Enable HSTS:** Configured in nginx.conf with 2-year max-age
3. **Disable Weak Protocols:** Only TLS 1.2 and 1.3 are enabled
4. **Regular Updates:** Keep certificates and nginx updated
5. **Monitor Expiration:** Set up automated monitoring for certificate expiry
6. **Backup Certificates:** Keep secure backups of your certificates and keys