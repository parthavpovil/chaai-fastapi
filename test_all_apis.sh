#!/bin/bash

# Comprehensive API Testing Script
# Tests all major endpoints including user and admin APIs

BASE_URL="http://localhost:8000"
ADMIN_EMAIL="admin@chatsaas.com"
ADMIN_PASSWORD="admin123"

echo "🧪 ChatSaaS Backend API - Comprehensive Testing"
echo "============================================================"
echo "Base URL: $BASE_URL"
echo "============================================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

test_endpoint() {
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    local name="$1"
    local status_code="$2"
    
    if [ "$status_code" -ge 200 ] && [ "$status_code" -lt 300 ]; then
        echo -e "${GREEN}✅ PASS${NC} - $name (Status: $status_code)"
        PASSED_TESTS=$((PASSED_TESTS + 1))
    else
        echo -e "${RED}❌ FAIL${NC} - $name (Status: $status_code)"
        FAILED_TESTS=$((FAILED_TESTS + 1))
    fi
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 SECTION 1: Health & Monitoring APIs (Public)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 1: Health Check
echo "1️⃣  GET /api/metrics/health/detailed"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/metrics/health/detailed")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Health Check" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -10
echo ""

# Test 2: Prometheus Metrics
echo "2️⃣  GET /api/metrics/prometheus"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/metrics/prometheus")
test_endpoint "Prometheus Metrics" "$STATUS"
echo ""

# Test 3: WebSocket Health
echo "3️⃣  GET /ws/health"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/ws/health")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "WebSocket Health" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -10
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔐 SECTION 2: Authentication APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 4: User Login
echo "4️⃣  POST /api/auth/login"
LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "testuser@example.com",
    "password": "securepassword123"
  }')
STATUS=$(echo "$LOGIN_RESPONSE" | tail -n1)
BODY=$(echo "$LOGIN_RESPONSE" | sed '$d')
test_endpoint "User Login" "$STATUS"

# Extract tokens
ACCESS_TOKEN=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)
WORKSPACE_ID=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('workspace', {}).get('id', ''))" 2>/dev/null)
WORKSPACE_SLUG=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('workspace', {}).get('slug', ''))" 2>/dev/null)

if [ -n "$ACCESS_TOKEN" ]; then
    echo -e "${GREEN}✓${NC} Access Token: ${ACCESS_TOKEN:0:50}..."
    echo -e "${GREEN}✓${NC} Workspace ID: $WORKSPACE_ID"
    echo -e "${GREEN}✓${NC} Workspace Slug: $WORKSPACE_SLUG"
else
    echo -e "${RED}✗${NC} Failed to extract access token"
fi
echo ""

# Test 5: Get Current User
echo "5️⃣  GET /api/auth/me"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Get Current User" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 SECTION 3: Channel Management APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 6: List Channels
echo "6️⃣  GET /api/channels/"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/channels/" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "List Channels" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20
echo ""

# Test 7: Create WebChat Channel
echo "7️⃣  POST /api/channels/ (WebChat)"
CHANNEL_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/channels/" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_type": "webchat",
    "name": "Test WebChat Widget",
    "credentials": {
      "business_name": "Test Business",
      "primary_color": "#FF5733",
      "position": "bottom-right",
      "welcome_message": "Hello! How can we help you?"
    },
    "is_active": true
  }')
STATUS=$(echo "$CHANNEL_RESPONSE" | tail -n1)
BODY=$(echo "$CHANNEL_RESPONSE" | sed '$d')
test_endpoint "Create WebChat Channel" "$STATUS"

CHANNEL_ID=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)
WIDGET_ID=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('widget_id', ''))" 2>/dev/null)

if [ -n "$CHANNEL_ID" ]; then
    echo -e "${GREEN}✓${NC} Channel ID: $CHANNEL_ID"
    echo -e "${GREEN}✓${NC} Widget ID: $WIDGET_ID"
fi
echo ""

# Test 8: Get Channel by ID
if [ -n "$CHANNEL_ID" ]; then
    echo "8️⃣  GET /api/channels/$CHANNEL_ID"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/channels/$CHANNEL_ID" \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    STATUS=$(echo "$RESPONSE" | tail -n1)
    test_endpoint "Get Channel by ID" "$STATUS"
    echo ""
fi

# Test 9: Channel Stats
echo "9️⃣  GET /api/channels/stats/summary"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/channels/stats/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Channel Stats" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📄 SECTION 4: Document Management APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 10: List Documents
echo "🔟 GET /api/documents/"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/documents/?limit=10&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "List Documents" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20
echo ""

# Test 11: Document Stats
echo "1️⃣1️⃣  GET /api/documents/stats/summary"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/documents/stats/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Document Stats" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "👥 SECTION 5: Agent Management APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 12: List Agents
echo "1️⃣2️⃣  GET /api/agents/"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/agents/" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "List Agents" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20
echo ""

# Test 13: Agent Stats
echo "1️⃣3️⃣  GET /api/agents/stats"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/agents/stats" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Agent Stats" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

# Test 14: Pending Invitations
echo "1️⃣4️⃣  GET /api/agents/pending"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/agents/pending" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
test_endpoint "Pending Agent Invitations" "$STATUS"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "💬 SECTION 6: Conversation Management APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 15: List Conversations
echo "1️⃣5️⃣  GET /api/conversations/"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/conversations/?limit=10&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "List Conversations" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20
echo ""

# Test 16: Conversation Stats
echo "1️⃣6️⃣  GET /api/conversations/stats/summary"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/conversations/stats/summary" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Conversation Stats" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 SECTION 7: WebChat Public APIs (No Auth)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 17: Get Widget Config
if [ -n "$WORKSPACE_SLUG" ]; then
    echo "1️⃣7️⃣  GET /api/webchat/config/$WORKSPACE_SLUG"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/webchat/config/$WORKSPACE_SLUG")
    STATUS=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    test_endpoint "Get Widget Config" "$STATUS"
    echo "$BODY" | python3 -m json.tool 2>/dev/null
    echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 SECTION 8: System Metrics APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 18: System Metrics
echo "1️⃣8️⃣  GET /api/metrics/system"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/metrics/system" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "System Metrics" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
echo ""

# Test 19: Workspace Metrics
if [ -n "$WORKSPACE_ID" ]; then
    echo "1️⃣9️⃣  GET /api/metrics/workspace/$WORKSPACE_ID"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/metrics/workspace/$WORKSPACE_ID" \
      -H "Authorization: Bearer $ACCESS_TOKEN")
    STATUS=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    test_endpoint "Workspace Metrics" "$STATUS"
    echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
    echo ""
fi

# Test 20: Alert Status
echo "2️⃣0️⃣  GET /api/metrics/alerts/status"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/metrics/alerts/status" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Alert Status" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 SECTION 9: Admin APIs (Requires Super Admin)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo -e "${YELLOW}Note: Admin APIs require super admin role. Testing with user token...${NC}"
echo ""

# Test 21: Admin Overview
echo "2️⃣1️⃣  GET /api/admin/overview"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/overview" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Admin Overview" "$STATUS"
if [ "$STATUS" -eq 403 ]; then
    echo -e "${YELLOW}⚠️  Expected 403 - User does not have admin role${NC}"
else
    echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20
fi
echo ""

# Test 22: List Workspaces (Admin)
echo "2️⃣2️⃣  GET /api/admin/workspaces"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/workspaces?limit=10&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
test_endpoint "Admin List Workspaces" "$STATUS"
if [ "$STATUS" -eq 403 ]; then
    echo -e "${YELLOW}⚠️  Expected 403 - User does not have admin role${NC}"
fi
echo ""

# Test 23: List Users (Admin)
echo "2️⃣3️⃣  GET /api/admin/users"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/users?limit=10&offset=0" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
test_endpoint "Admin List Users" "$STATUS"
if [ "$STATUS" -eq 403 ]; then
    echo -e "${YELLOW}⚠️  Expected 403 - User does not have admin role${NC}"
fi
echo ""

# Test 24: Analytics (Admin)
echo "2️⃣4️⃣  GET /api/admin/analytics"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/analytics" \
  -H "Authorization: Bearer $ACCESS_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
test_endpoint "Admin Analytics" "$STATUS"
if [ "$STATUS" -eq 403 ]; then
    echo -e "${YELLOW}⚠️  Expected 403 - User does not have admin role${NC}"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📈 TEST SUMMARY"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Total Tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
else
    echo -e "${YELLOW}⚠️  Some tests failed. Check the output above for details.${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Testing Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
