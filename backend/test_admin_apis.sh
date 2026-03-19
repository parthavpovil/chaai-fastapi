#!/bin/bash

# Admin API Testing Script
# Tests all admin endpoints with super admin credentials

BASE_URL="http://localhost:8000"
ADMIN_EMAIL="admin@yourdomain.com"
ADMIN_PASSWORD="admin123"

echo "🔧 ChatSaaS Backend API - Admin Endpoint Testing"
echo "============================================================"
echo "Base URL: $BASE_URL"
echo "Admin Email: $ADMIN_EMAIL"
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
echo "🔐 Admin Authentication"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Admin Login
echo "1️⃣  POST /api/auth/login (Admin)"
LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{
    \"email\": \"$ADMIN_EMAIL\",
    \"password\": \"$ADMIN_PASSWORD\"
  }")
STATUS=$(echo "$LOGIN_RESPONSE" | tail -n1)
BODY=$(echo "$LOGIN_RESPONSE" | sed '$d')
test_endpoint "Admin Login" "$STATUS"

# Extract admin token
ADMIN_TOKEN=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -n "$ADMIN_TOKEN" ]; then
    echo -e "${GREEN}✓${NC} Admin Token: ${ADMIN_TOKEN:0:50}..."
else
    echo -e "${RED}✗${NC} Failed to extract admin token"
    exit 1
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 Admin APIs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Test 2: Admin Overview
echo "2️⃣  GET /api/admin/overview"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/overview" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Admin Overview" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
echo ""

# Test 3: List Workspaces (Admin)
echo "3️⃣  GET /api/admin/workspaces"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/workspaces?limit=5&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Admin List Workspaces" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
echo ""

# Test 4: List Users (Admin)
echo "4️⃣  GET /api/admin/users"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/users?limit=5&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Admin List Users" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
echo ""

# Test 5: Analytics (Admin)
echo "5️⃣  GET /api/admin/analytics"
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/admin/analytics" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
STATUS=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
test_endpoint "Admin Analytics" "$STATUS"
echo "$BODY" | python3 -m json.tool 2>/dev/null | head -30
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
    echo -e "${GREEN}🎉 All admin tests passed!${NC}"
else
    echo -e "${YELLOW}⚠️  Some tests failed. Check the output above for details.${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Admin Testing Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
