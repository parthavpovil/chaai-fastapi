#!/bin/bash
# Cleanup script for ChatSaaS Backend
# Removes cache files, test artifacts, and temporary files

echo "🧹 Cleaning up ChatSaaS Backend..."

# Remove Python cache
echo "Removing Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type f -name "*.pyo" -delete 2>/dev/null
find . -type f -name "*.pyd" -delete 2>/dev/null

# Remove pytest cache
echo "Removing pytest cache..."
rm -rf .pytest_cache 2>/dev/null

# Remove hypothesis cache (keep examples for faster testing)
echo "Cleaning hypothesis cache..."
find .hypothesis -type f -name "*.json" ! -name "charmap.json*" -delete 2>/dev/null

# Remove coverage reports
echo "Removing coverage reports..."
rm -rf htmlcov .coverage 2>/dev/null

# Remove log files
echo "Removing log files..."
rm -f logs/*.log 2>/dev/null

# Remove temporary files
echo "Removing temporary files..."
find . -type f -name "*.tmp" -delete 2>/dev/null
find . -type f -name "*.temp" -delete 2>/dev/null
find . -type f -name "*~" -delete 2>/dev/null

echo "✅ Cleanup complete!"
