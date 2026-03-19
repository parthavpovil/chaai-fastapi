# Admin Architecture

## Overview

The ChatSaaS backend uses a **simplified, email-based super admin system**. There is only one admin level: **Super Admin**.

## How It Works

### Super Admin Identification

Super admin status is determined by comparing the user's email address with the `SUPER_ADMIN_EMAIL` environment variable:

```python
# In app/services/admin_service.py
def is_super_admin(self, user_email: str) -> bool:
    return user_email.lower() == settings.SUPER_ADMIN_EMAIL.lower()
```

### No Database Field

Unlike traditional role-based systems, there is **no `is_super_admin` or `role` field** in the User model. The User model only has:
- `id`
- `email`
- `hashed_password`
- `is_active`
- `created_at`
- `last_login`

### Configuration

**Default Configuration** (in `app/config.py`):
```python
SUPER_ADMIN_EMAIL: str = Field(
    default="admin@yourdomain.com",
    description="Super administrator email address"
)
```

**Override in `.env`**:
```bash
SUPER_ADMIN_EMAIL=your-admin@example.com
```

## Creating a Super Admin User

To create a super admin user:

1. Set the `SUPER_ADMIN_EMAIL` in your `.env` file
2. Create a regular user account with that exact email address
3. The user will automatically have super admin privileges

**Example**:
```bash
# In .env
SUPER_ADMIN_EMAIL=admin@yourdomain.com

# Then create user via API or script
python3 << 'EOF'
import asyncio
from app.models.user import User
from app.services.auth_service import AuthService
from app.database import get_db_session

async def create_admin():
    async with get_db_session() as session:
        hashed_password = AuthService.hash_password("your-secure-password")
        admin = User(
            email="admin@yourdomain.com",  # Must match SUPER_ADMIN_EMAIL
            hashed_password=hashed_password,
            is_active=True
        )
        session.add(admin)
        await session.commit()

asyncio.run(create_admin())
EOF
```

## Admin Endpoints

All admin endpoints require super admin access via the `require_super_admin` dependency:

```python
@router.get("/overview")
async def get_admin_overview(
    current_user: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db)
):
    # Only accessible if current_user.email == SUPER_ADMIN_EMAIL
    ...
```

### Available Admin Endpoints

1. **GET /api/admin/overview** - Platform overview statistics
2. **GET /api/admin/workspaces** - List all workspaces
3. **GET /api/admin/users** - List all users
4. **GET /api/admin/analytics** - Platform analytics

## Security Considerations

### Advantages
- Simple to implement and understand
- No complex role management
- Easy to change super admin (just update env variable)
- No database migrations needed for admin changes

### Limitations
- Only supports one super admin email at a time
- No role hierarchy (workspace admin, platform admin, etc.)
- Cannot have multiple super admins without code changes

## Testing Admin Endpoints

Use the provided test script:

```bash
# Set admin credentials in test_admin_apis.sh
ADMIN_EMAIL="admin@yourdomain.com"
ADMIN_PASSWORD="your-password"

# Run tests
bash backend/test_admin_apis.sh
```

## Future Enhancements

If you need more complex admin roles in the future, consider:

1. **Add role field to User model**:
   ```python
   role = Column(String, default="user")  # user, admin, super_admin
   ```

2. **Create separate Admin model**:
   ```python
   class Admin(Base):
       user_id = Column(UUID, ForeignKey("users.id"))
       role = Column(String)  # admin, super_admin
       permissions = Column(JSON)
   ```

3. **Implement workspace-level admins**:
   - Workspace owners can invite workspace admins
   - Workspace admins can manage channels, agents, documents
   - Platform super admins can manage all workspaces

## Current Test Credentials

**Super Admin**:
- Email: `admin@yourdomain.com`
- Password: `admin123`

**Regular User**:
- Email: `testuser@example.com`
- Password: `securepassword123`
