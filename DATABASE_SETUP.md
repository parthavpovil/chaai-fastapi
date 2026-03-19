# Database Setup - Simplified with Docker

## Overview

Your PostgreSQL database runs in a **Docker container**, which means:
- ✅ No manual PostgreSQL installation needed
- ✅ No manual database creation needed
- ✅ No manual user creation needed
- ✅ Automatic pgvector extension setup
- ✅ Data persists in Docker volumes

## Configuration

### Docker Compose Setup

Your `docker-compose.prod.yml` defines the PostgreSQL service:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg15
    container_name: chatsaas-postgres
    environment:
      POSTGRES_DB: chatsaas_prod
      POSTGRES_USER: chatsaas_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # From .env file
    volumes:
      - postgres_data:/var/lib/postgresql/data  # Persistent storage
      - ./init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U chatsaas_user -d chatsaas_prod"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### What This Means

**Automatic Configuration:**
- Database name: `chatsaas_prod`
- Username: `chatsaas_user`
- Password: From `POSTGRES_PASSWORD` environment variable
- Host: `postgres` (Docker container name)
- Port: `5432`

**Automatic Initialization:**
- The `init-db.sql` file runs automatically on first startup
- Creates the `vector` extension for pgvector
- Sets up any initial schema if needed

**Data Persistence:**
- Data is stored in Docker volume: `postgres_data`
- Survives container restarts
- Survives container recreation
- Only lost if you explicitly delete the volume

## GitHub Secrets Setup

You only need to set **ONE** database secret:

```
POSTGRES_PASSWORD = YourSecurePassword123
```

**Generate a secure password:**
```bash
openssl rand -base64 32
```

## How It Works

### 1. Deployment Process

When you deploy via GitHub Actions:

```bash
# 1. GitHub Actions creates .env file on VPS
cat > /var/www/chatsaas/.env << EOF
POSTGRES_PASSWORD=YourSecurePassword123
# ... other secrets
EOF

# 2. Docker Compose reads .env and starts containers
cd /var/www/chatsaas
docker-compose -f docker-compose.prod.yml up -d

# 3. PostgreSQL container starts with:
#    - Database: chatsaas_prod (created automatically)
#    - User: chatsaas_user (created automatically)
#    - Password: YourSecurePassword123 (from .env)
#    - Extension: vector (from init-db.sql)

# 4. Backend container connects using:
DATABASE_URL=postgresql+asyncpg://chatsaas_user:YourSecurePassword123@postgres:5432/chatsaas_prod
```

### 2. Connection String

The backend automatically constructs the DATABASE_URL:

```python
# In docker-compose.prod.yml
environment:
  - DATABASE_URL=postgresql+asyncpg://chatsaas_user:${POSTGRES_PASSWORD}@postgres:5432/chatsaas_prod
```

**Breakdown:**
- `postgresql+asyncpg://` - Protocol (async PostgreSQL)
- `chatsaas_user` - Username (hardcoded in docker-compose)
- `${POSTGRES_PASSWORD}` - Password (from .env file)
- `@postgres` - Host (Docker container name)
- `:5432` - Port (PostgreSQL default)
- `/chatsaas_prod` - Database name (hardcoded in docker-compose)

### 3. First Startup

On first startup, PostgreSQL automatically:

1. Creates the database `chatsaas_prod`
2. Creates the user `chatsaas_user` with your password
3. Runs `init-db.sql` to create the vector extension
4. Becomes ready to accept connections

### 4. Migrations

After PostgreSQL is ready, the deployment script runs migrations:

```bash
docker-compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

This creates all your tables, indexes, and constraints.

## Data Persistence

### Docker Volumes

Your data is stored in a Docker volume:

```yaml
volumes:
  postgres_data:
    driver: local
```

**Location on VPS:**
```
/var/lib/docker/volumes/chatsaas_postgres_data/_data
```

**Persistence:**
- ✅ Survives `docker-compose restart`
- ✅ Survives `docker-compose down` and `docker-compose up`
- ✅ Survives VPS reboot
- ❌ Lost if you run `docker-compose down -v` (removes volumes)
- ❌ Lost if you run `docker volume rm postgres_data`

### Backup Strategy

**Manual Backup:**
```bash
# On VPS
docker exec chatsaas-postgres pg_dump -U chatsaas_user chatsaas_prod > backup.sql
```

**Restore from Backup:**
```bash
# On VPS
cat backup.sql | docker exec -i chatsaas-postgres psql -U chatsaas_user -d chatsaas_prod
```

**Automated Backup (recommended):**
Add to crontab:
```bash
# Backup daily at 2 AM
0 2 * * * docker exec chatsaas-postgres pg_dump -U chatsaas_user chatsaas_prod | gzip > /backups/chatsaas_$(date +\%Y\%m\%d).sql.gz
```

## Accessing the Database

### From VPS

```bash
# Connect to PostgreSQL container
docker exec -it chatsaas-postgres psql -U chatsaas_user -d chatsaas_prod

# Run SQL commands
chatsaas_prod=# \dt  # List tables
chatsaas_prod=# SELECT * FROM workspaces;
chatsaas_prod=# \q   # Quit
```

### From Local Machine

```bash
# Forward port from VPS to local machine
ssh -L 5432:localhost:5432 user@your-vps-ip

# Then connect locally
psql postgresql://chatsaas_user:password@localhost:5432/chatsaas_prod
```

### Using GUI Tools

**DBeaver, pgAdmin, TablePlus, etc:**
```
Host: your-vps-ip
Port: 5432
Database: chatsaas_prod
Username: chatsaas_user
Password: [your POSTGRES_PASSWORD]
```

**Security Note:** The PostgreSQL port (5432) is exposed in docker-compose. In production, you should:
1. Use a firewall to restrict access
2. Only allow connections from localhost
3. Use SSH tunneling for remote access

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker logs chatsaas-postgres

# Common issues:
# 1. Port 5432 already in use
sudo lsof -i :5432

# 2. Permission issues with volume
sudo chown -R 999:999 /var/lib/docker/volumes/postgres_data/_data

# 3. Corrupted data
docker-compose down
docker volume rm postgres_data
docker-compose up -d  # Will recreate from scratch
```

### Connection Refused

```bash
# Check if container is running
docker ps | grep postgres

# Check if PostgreSQL is ready
docker exec chatsaas-postgres pg_isready -U chatsaas_user

# Check backend can reach postgres
docker exec chatsaas-backend ping postgres
```

### Wrong Password

```bash
# Update password in .env file
nano /var/www/chatsaas/.env
# Change POSTGRES_PASSWORD=...

# Restart containers
docker-compose -f docker-compose.prod.yml restart
```

### Data Loss Prevention

**Before destroying containers:**
```bash
# Backup first!
docker exec chatsaas-postgres pg_dump -U chatsaas_user chatsaas_prod > backup.sql

# Then you can safely:
docker-compose down -v  # Removes volumes
```

## Comparison: Docker vs Manual Setup

### Docker Setup (Current)
✅ No manual installation
✅ Consistent across environments
✅ Easy to upgrade (change image version)
✅ Isolated from host system
✅ Easy to backup/restore
✅ Automatic initialization
❌ Requires Docker knowledge
❌ Slightly more complex networking

### Manual Setup (Alternative)
✅ Direct access to PostgreSQL
✅ Familiar to DBAs
✅ Slightly better performance
❌ Manual installation required
❌ Manual configuration required
❌ OS-specific setup
❌ Harder to replicate
❌ Harder to upgrade

**Recommendation:** Stick with Docker! It's simpler and more maintainable.

## Summary

### What You Need to Do:
1. Set `POSTGRES_PASSWORD` in GitHub Secrets
2. Deploy via GitHub Actions
3. Everything else is automatic!

### What Happens Automatically:
- PostgreSQL container starts
- Database `chatsaas_prod` is created
- User `chatsaas_user` is created
- Vector extension is installed
- Migrations run
- Backend connects
- Data persists in Docker volume

### What You DON'T Need to Do:
- ❌ Install PostgreSQL on VPS
- ❌ Create database manually
- ❌ Create user manually
- ❌ Install pgvector manually
- ❌ Configure DATABASE_URL (it's automatic)

**It just works!** 🚀
