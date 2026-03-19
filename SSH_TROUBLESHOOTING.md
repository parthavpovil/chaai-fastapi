# SSH Password Login Troubleshooting

## Quick Diagnosis

Try connecting and note the exact error:

```bash
ssh username@your-vps-ip
```

Common errors and solutions below:

---

## Error 1: "Permission denied (publickey)"

**Meaning**: Server is configured to only accept SSH keys, not passwords.

**Solution**: Enable password authentication

```bash
# If you have SSH key access or console access:
sudo nano /etc/ssh/sshd_config

# Find and change these lines:
PasswordAuthentication yes
PubkeyAuthentication yes
ChallengeResponseAuthentication yes

# Save and restart SSH
sudo systemctl restart sshd
# or
sudo service ssh restart
```

**If you don't have any access**, use your VPS provider's console/terminal:
- DigitalOcean: Droplet → Access → Launch Console
- AWS: EC2 → Connect → EC2 Instance Connect
- Linode: Launch LISH Console
- Vultr: View Console

---

## Error 2: "Connection refused"

**Possible causes:**

### A. SSH service not running

```bash
# Check if SSH is running
sudo systemctl status sshd
# or
sudo service ssh status

# If not running, start it
sudo systemctl start sshd
sudo systemctl enable sshd
```

### B. Firewall blocking port 22

```bash
# Check firewall status
sudo ufw status

# If port 22 is not allowed:
sudo ufw allow 22/tcp
sudo ufw reload

# Or if using iptables:
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables-save
```

### C. SSH running on different port

```bash
# Check what port SSH is using
sudo grep "^Port" /etc/ssh/sshd_config

# If it shows something like "Port 2222", connect with:
ssh -p 2222 username@your-vps-ip
```

---

## Error 3: "Connection timed out"

**Possible causes:**

### A. VPS provider firewall

Check your VPS provider's firewall/security groups:

**DigitalOcean:**
- Networking → Firewalls → Allow SSH (port 22)

**AWS:**
- Security Groups → Inbound Rules → Add SSH (port 22) from 0.0.0.0/0

**Linode:**
- Firewalls → Add rule for SSH (port 22)

### B. Wrong IP address

```bash
# Verify your VPS IP
# Check your VPS provider dashboard

# Try pinging the IP
ping your-vps-ip

# If ping fails, IP might be wrong or ICMP is blocked
```

---

## Error 4: "Access denied" or "Authentication failed"

**Possible causes:**

### A. Wrong username

Common usernames by provider:
- Ubuntu: `ubuntu`
- Debian: `debian`
- CentOS: `centos`
- Root access: `root`

```bash
# Try different usernames
ssh root@your-vps-ip
ssh ubuntu@your-vps-ip
ssh admin@your-vps-ip
```

### B. Wrong password

- Check if you have the correct password
- Some VPS providers send initial password via email
- You may need to reset password via provider's console

### C. Account locked

```bash
# Via console, check if account is locked
sudo passwd -S username

# If locked, unlock it
sudo passwd -u username
```

---

## Complete SSH Configuration Check

If you have console access, run this diagnostic:

```bash
#!/bin/bash
echo "=== SSH Configuration Diagnostic ==="

echo -e "\n1. SSH Service Status:"
sudo systemctl status sshd | grep Active

echo -e "\n2. SSH Port:"
sudo grep "^Port" /etc/ssh/sshd_config || echo "Default port 22"

echo -e "\n3. Password Authentication:"
sudo grep "^PasswordAuthentication" /etc/ssh/sshd_config

echo -e "\n4. Root Login:"
sudo grep "^PermitRootLogin" /etc/ssh/sshd_config

echo -e "\n5. Firewall Status:"
sudo ufw status | grep 22 || echo "UFW not active or port 22 not configured"

echo -e "\n6. Listening Ports:"
sudo netstat -tlnp | grep :22 || sudo ss -tlnp | grep :22

echo -e "\n7. SSH Config File:"
sudo cat /etc/ssh/sshd_config | grep -v "^#" | grep -v "^$"
```

---

## Recommended SSH Configuration

For GitHub Actions deployment, use this configuration:

```bash
# Edit SSH config
sudo nano /etc/ssh/sshd_config

# Recommended settings:
Port 22
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
ChallengeResponseAuthentication yes
UsePAM yes

# Optional security improvements:
MaxAuthTries 3
MaxSessions 10
ClientAliveInterval 300
ClientAliveCountMax 2

# Save and restart
sudo systemctl restart sshd
```

---

## Testing SSH Password Login

### From your local machine:

```bash
# Test connection
ssh username@your-vps-ip

# If it asks for password, it's working!
# If it says "Permission denied (publickey)", password auth is disabled
```

### Test with verbose output:

```bash
ssh -v username@your-vps-ip

# Look for these lines:
# "debug1: Authentications that can continue: publickey,password"
# This means password auth is enabled

# "debug1: Authentications that can continue: publickey"
# This means password auth is disabled
```

---

## Quick Fix Script

Run this on your VPS (via console) to enable password authentication:

```bash
#!/bin/bash
# Enable SSH password authentication

echo "Backing up SSH config..."
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup

echo "Enabling password authentication..."
sudo sed -i 's/^PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config

echo "Enabling root login (if needed)..."
sudo sed -i 's/^PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config
sudo sed -i 's/^#PermitRootLogin yes/PermitRootLogin yes/' /etc/ssh/sshd_config

echo "Restarting SSH service..."
sudo systemctl restart sshd || sudo service ssh restart

echo "Done! Try connecting now:"
echo "ssh $(whoami)@$(hostname -I | awk '{print $1}')"
```

---

## Security Considerations

### After enabling password authentication:

1. **Use strong passwords**
   ```bash
   # Change password
   sudo passwd username
   # Use at least 16 characters with mix of letters, numbers, symbols
   ```

2. **Consider fail2ban** (blocks brute force attacks)
   ```bash
   sudo apt install fail2ban -y
   sudo systemctl enable fail2ban
   sudo systemctl start fail2ban
   ```

3. **Change default SSH port** (optional, but adds security)
   ```bash
   sudo nano /etc/ssh/sshd_config
   # Change: Port 2222
   sudo systemctl restart sshd
   
   # Update firewall
   sudo ufw allow 2222/tcp
   sudo ufw delete allow 22/tcp
   
   # Connect with: ssh -p 2222 username@ip
   ```

4. **Disable root login after setup** (use sudo instead)
   ```bash
   sudo nano /etc/ssh/sshd_config
   # Change: PermitRootLogin no
   sudo systemctl restart sshd
   ```

---

## For GitHub Actions

Your workflow needs these settings enabled:

```bash
# On VPS:
PasswordAuthentication yes  # Required for sshpass
PermitRootLogin yes         # If using root user
```

**Alternative**: Use SSH keys instead of passwords (more secure)

```yaml
# In GitHub workflow, use SSH key instead:
- name: Setup SSH
  run: |
    mkdir -p ~/.ssh
    echo "${{ secrets.SSH_PRIVATE_KEY }}" > ~/.ssh/id_rsa
    chmod 600 ~/.ssh/id_rsa
    ssh-keyscan -H ${{ secrets.VPS_HOST }} >> ~/.ssh/known_hosts

- name: Deploy
  run: |
    ssh ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }} 'bash /tmp/deploy.sh'
```

---

## Still Not Working?

### Check these:

1. **VPS provider's firewall/security groups**
   - Must allow inbound traffic on port 22
   - Check provider's dashboard

2. **VPS is actually running**
   - Check provider's dashboard
   - Try accessing via web console

3. **Correct IP address**
   - Double-check IP in provider's dashboard
   - Try pinging: `ping your-vps-ip`

4. **SSH service is running**
   - Via console: `sudo systemctl status sshd`

5. **No typos in username/password**
   - Username is case-sensitive
   - Password is case-sensitive

---

## Get Help

If still stuck, run this and share the output:

```bash
# On VPS (via console):
echo "=== System Info ==="
uname -a
cat /etc/os-release | grep PRETTY_NAME

echo -e "\n=== SSH Status ==="
sudo systemctl status sshd

echo -e "\n=== SSH Config ==="
sudo grep -E "^(Port|PasswordAuthentication|PermitRootLogin)" /etc/ssh/sshd_config

echo -e "\n=== Firewall ==="
sudo ufw status verbose || echo "UFW not installed"

echo -e "\n=== Listening Ports ==="
sudo ss -tlnp | grep :22
```

This will help diagnose the issue!
