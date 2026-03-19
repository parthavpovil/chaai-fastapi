# Tier Management System

## Overview

The ChatSaaS platform uses a **4-tier subscription system** with different resource limits for each tier. Currently, **only super admins can change workspace tiers** - there is no self-service upgrade functionality for users.

## Available Tiers

| Tier | Channels | Agents | Documents | Monthly Messages |
|------|----------|--------|-----------|------------------|
| **Free** | 1 | 0 | 3 | 500 |
| **Starter** | 2 | 0 | 10 | 2,000 |
| **Growth** | 4 | 0 | 25 | 10,000 |
| **Pro** | 4 | 2 | 100 | 50,000 |

## How Tier Changes Work

### Current Implementation: Admin-Only

**Only super admins can change workspace tiers** through the admin API:

```bash
POST /api/admin/workspaces/change-tier
Authorization: Bearer <admin_token>

{
  "workspace_id": "uuid-here",
  "new_tier": "pro",
  "reason": "Customer upgrade request"
}
```

### What Happens During a Tier Change

1. **Validation**:
   - Verifies the requester is a super admin
   - Checks if the new tier is valid (free, starter, growth, pro)
   - Ensures workspace exists
   - Prevents changing to the same tier

2. **Audit Logging**:
   - Creates a record in the `tier_changes` table with:
     - `workspace_id`
     - `from_tier`
     - `to_tier`
     - `changed_by` (admin email)
     - `note` (reason for change)
     - `created_at` (timestamp)

3. **Workspace Update**:
   - Updates `workspace.tier`
   - Sets `workspace.tier_changed_at`
   - Sets `workspace.tier_changed_by`

4. **Immediate Effect**:
   - New limits apply immediately
   - Existing resources are not deleted (even if over new limits)
   - New resource creation uses new tier limits

## User Tier Upgrade Flow (Not Implemented)

Currently, users **cannot upgrade their own tiers**. They must:

1. Contact support/admin
2. Admin manually changes tier via admin API
3. User gets access to new limits

### Future Implementation Options

If you want to add self-service tier upgrades, you would need to:

#### Option 1: Simple Admin Approval
```
User → Request Upgrade → Admin Reviews → Admin Approves → Tier Changed
```

#### Option 2: Payment Integration
```
User → Choose Plan → Payment Gateway → Payment Success → Tier Changed Automatically
```

#### Option 3: Hybrid Approach
```
User → Choose Plan → Payment → Admin Notification → Admin Confirms → Tier Changed
```

## Tier Enforcement

The `TierManager` service enforces limits when users try to create resources:

```python
# Example: Creating a channel
tier_manager = TierManager(db)
await tier_manager.check_channel_limit(workspace_id)
# Raises TierLimitError if limit exceeded
```

### When Limits Are Checked

- **Channels**: When creating a new channel
- **Agents**: When inviting a new agent
- **Documents**: When uploading a new document
- **Messages**: When sending a message (monthly counter)

### Error Response

When a limit is exceeded:
```json
{
  "detail": "Channel limit reached for free tier (1/1). Upgrade to create more channels."
}
```
HTTP Status: `402 Payment Required`

## Viewing Tier Change History

Super admins can view tier change history:

```bash
GET /api/admin/tier-changes?workspace_id=<uuid>&limit=50
Authorization: Bearer <admin_token>
```

Response:
```json
[
  {
    "workspace_name": "Acme Corp",
    "workspace_slug": "acme-corp",
    "from_tier": "free",
    "to_tier": "pro",
    "changed_by": "admin@yourdomain.com",
    "changed_at": "2026-03-19T10:30:00Z",
    "note": "Customer upgrade request"
  }
]
```

## Testing Tier Changes

### Test Script

```bash
# Login as admin
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourdomain.com","password":"admin123"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Get a workspace ID
WORKSPACE_ID="74d4b725-3e20-4b7e-96b5-35296bd7f208"

# Change tier
curl -X POST "http://localhost:8000/api/admin/workspaces/change-tier" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "'$WORKSPACE_ID'",
    "new_tier": "pro",
    "reason": "Testing tier upgrade"
  }'

# View tier change history
curl "http://localhost:8000/api/admin/tier-changes?workspace_id=$WORKSPACE_ID&limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## Database Schema

### Workspace Table
```sql
CREATE TABLE workspaces (
    id UUID PRIMARY KEY,
    name VARCHAR NOT NULL,
    slug VARCHAR UNIQUE NOT NULL,
    tier VARCHAR DEFAULT 'free',
    tier_changed_at TIMESTAMP,
    tier_changed_by VARCHAR,
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Tier Changes Table (Audit Log)
```sql
CREATE TABLE tier_changes (
    id UUID PRIMARY KEY,
    workspace_id UUID REFERENCES workspaces(id),
    from_tier VARCHAR NOT NULL,
    to_tier VARCHAR NOT NULL,
    changed_by VARCHAR NOT NULL,
    note TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

## Common Questions

### Q: Can users upgrade their own tier?
**A:** No, currently only super admins can change tiers.

### Q: What happens to existing resources when downgrading?
**A:** Existing resources remain, but new resources cannot be created if over the new limit.

### Q: Are tier changes immediate?
**A:** Yes, tier changes take effect immediately.

### Q: Can I see who changed a workspace's tier?
**A:** Yes, check the `tier_changes` table or use the `/api/admin/tier-changes` endpoint.

### Q: What if I want to add payment integration?
**A:** You would need to:
1. Integrate a payment gateway (Stripe, PayPal, etc.)
2. Create a user-facing `/api/workspaces/upgrade` endpoint
3. Handle payment webhooks
4. Automatically call `admin_service.change_workspace_tier()` on successful payment

## Implementation Checklist for Self-Service Upgrades

If you want to add user-facing tier upgrades:

- [ ] Choose payment gateway (Stripe recommended)
- [ ] Add payment gateway credentials to config
- [ ] Create `/api/workspaces/upgrade` endpoint
- [ ] Add payment processing logic
- [ ] Handle payment webhooks
- [ ] Add subscription management UI
- [ ] Add billing history endpoint
- [ ] Add invoice generation
- [ ] Add payment method management
- [ ] Add cancellation/downgrade flow
- [ ] Add proration logic for mid-month changes
- [ ] Add email notifications for tier changes
- [ ] Update documentation
