# Multi-stage Dockerfile for ChatSaaS Backend
FROM python:3.12-slim as builder

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.12-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r chatsaas && useradd -r -g chatsaas chatsaas

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /var/chatsaas/storage/documents && \
    mkdir -p /var/run/chatsaas && \
    mkdir -p /var/log/chatsaas

# Make entrypoint executable and set ownership
RUN chmod +x /app/entrypoint.sh && \
    chown -R chatsaas:chatsaas /app /var/chatsaas /var/run/chatsaas /var/log/chatsaas

# Switch to non-root user
USER chatsaas

# Expose port
EXPOSE 8000

# Health check — start_period must account for cold-import time (~70s on
# constrained CPU containers) plus first cold R2 connection. --max-time 5
# makes curl give up fast when gunicorn workers haven't dequeued the
# connection yet (port is bound by master before workers finish import).
HEALTHCHECK --interval=10s --timeout=10s --start-period=240s --retries=5 \
    CMD curl -f --max-time 5 http://localhost:8000/health || exit 1

# Default command
CMD ["/app/entrypoint.sh"]