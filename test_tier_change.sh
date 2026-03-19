#!/bin/bash

BASE_URL="http://localhost:8000"

echo "🔄 Testing Tier Change Functionality"
echo "======================================"
echo ""

# Login as admin
echo "1️⃣  Logging in as admin..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourdomain.com","password":"admin123"}')

ADMIN_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$ADMIN_TOKEN" ]; then
    echo "❌ Failed to get admin token"
    exit 1
fi
echo "✅ Admin logged in"
echo ""

# Get test workspace
WORKSPACE_ID="74d4b725-3e20-4b7e-96b5-35296bd7f208"

# Check current tier
echo "2️⃣  Checking current workspace tier..."
WORKSPACE_RESPONSE=$(curl -s "$BASE_URL/api/admin/workspaces?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

CURRENT_TIER=$(echo "$WORKSPACE_RESPONSE" | python3 -c "
import sys, json
workspaces = json.load(sys.stdin)
for ws in workspaces:
    if ws['id'] == '$WORKSPACE_ID':
        print(ws['tier'])
        break
" 2>/dev/null)

echo "Current tier: $CURRENT_TIER"
echo ""

# Change tier to pro
echo "3️⃣  Changing tier from $CURRENT_TIER to pro..."
CHANGE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/admin/workspaces/change-tier" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"workspace_id\": \"$WORKSPACE_ID\",
    \"new_tier\": \"pro\",
    \"reason\": \"Testing tier upgrade functionality\"
  }")

STATUS=$(echo "$CHANGE_RESPONSE" | tail -n1)
BODY=$(echo "$CHANGE_RESPONSE" | sed '$d')

if [ "$STATUS" -eq 200 ]; then
    echo "✅ Tier changed successfully"
    echo "$BODY" | python3 -m json.tool 2>/dev/null
else
    echo "❌ Tier change failed (Status: $STATUS)"
    echo "$BODY"
fi
echo ""

# View tier change history
echo "4️⃣  Viewing tier change history..."
HISTORY_RESPONSE=$(curl -s "$BASE_URL/api/admin/tier-changes?workspace_id=$WORKSPACE_ID&limit=5" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

echo "$HISTORY_RESPONSE" | python3 -m json.tool 2>/dev/null | head -30
echo ""

# Verify new tier
echo "5️⃣  Verifying new tier..."
WORKSPACE_RESPONSE=$(curl -s "$BASE_URL/api/admin/workspaces?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN")

NEW_TIER=$(echo "$WORKSPACE_RESPONSE" | python3 -c "
import sys, json
workspaces = json.load(sys.stdin)
for ws in workspaces:
    if ws['id'] == '$WORKSPACE_ID':
        print(ws['tier'])
        break
" 2>/dev/null)

echo "New tier: $NEW_TIER"

if [ "$NEW_TIER" = "pro" ]; then
    echo "✅ Tier change verified!"
else
    echo "❌ Tier verification failed"
fi

echo ""
echo "======================================"
echo "✅ Tier Change Test Complete"
