#!/bin/bash

BASE_URL="http://localhost:8000"

echo "📊 Testing Tier Limit Changes"
echo "======================================"
echo ""

# Login as regular user
echo "1️⃣  Logging in as regular user..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser@example.com","password":"securepassword123"}')

USER_TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$USER_TOKEN" ]; then
    echo "❌ Failed to get user token"
    exit 1
fi
echo "✅ User logged in"
echo ""

# Check current channels
echo "2️⃣  Checking current channels..."
CHANNELS_RESPONSE=$(curl -s "$BASE_URL/api/channels/" \
  -H "Authorization: Bearer $USER_TOKEN")

CHANNEL_COUNT=$(echo "$CHANNELS_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null)
echo "Current channels: $CHANNEL_COUNT"
echo ""

# Try to create a second channel (should work now with pro tier)
echo "3️⃣  Attempting to create a second WebChat channel..."
CREATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/channels/" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_type": "webchat",
    "name": "Second WebChat Widget",
    "credentials": {
      "business_name": "Test Business 2",
      "primary_color": "#3366FF",
      "position": "bottom-left",
      "welcome_message": "Welcome to our second chat!"
    },
    "is_active": true
  }')

STATUS=$(echo "$CREATE_RESPONSE" | tail -n1)
BODY=$(echo "$CREATE_RESPONSE" | sed '$d')

if [ "$STATUS" -eq 200 ] || [ "$STATUS" -eq 201 ]; then
    echo "✅ Second channel created successfully!"
    echo "$BODY" | python3 -m json.tool 2>/dev/null | head -15
else
    echo "❌ Channel creation failed (Status: $STATUS)"
    echo "$BODY" | python3 -m json.tool 2>/dev/null
fi
echo ""

# Check channel count again
echo "4️⃣  Checking updated channel count..."
CHANNELS_RESPONSE=$(curl -s "$BASE_URL/api/channels/" \
  -H "Authorization: Bearer $USER_TOKEN")

NEW_CHANNEL_COUNT=$(echo "$CHANNELS_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null)
echo "New channel count: $NEW_CHANNEL_COUNT"
echo ""

echo "======================================"
echo "Pro tier allows 4 channels"
echo "Current channels: $NEW_CHANNEL_COUNT/4"
echo "✅ Tier Limit Test Complete"
