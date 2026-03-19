-- Database initialization script for ChatSaaS Backend
-- This script sets up the PostgreSQL database with pgvector extension

-- Create the pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create additional indexes for performance (these will be created by Alembic migrations)
-- This script ensures the extension is available

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON DATABASE chatsaas_prod TO chatsaas_user;

-- Set timezone to UTC
SET timezone = 'UTC';