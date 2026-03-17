# ChatSaaS Backend Monitoring Guide

This document provides comprehensive information about monitoring, health checks, and alerting for the ChatSaaS Backend application.

## Overview

The ChatSaaS Backend includes a comprehensive monitoring system with:

- **Health Check Endpoints**: Load balancer and detailed health checks
- **Metrics Collection**: Application, business, and performance metrics
- **Real-time Monitoring**: Request tracking and performance monitoring
- **Alerting System**: Automated error detection and notification
- **Structured Logging**: JSON-formatted logs for analysis
- **Background Tasks**: Periodic health checks and metrics collection

## Health Check Endpoints

### Basic Health Check
```
GET /health
```
Returns basic health status for load balancers:
```json
{
  "status": "healthy",
  "service": "chatsaas-backend",
  "timestamp": 1703123456.789,
  "checks": {
    "database": {"status": "healthy", "response_time_ms": 12.34},
    "storage": {"status": "healthy", "free_space_gb": 45.67},
    "maintenance_mode": {"status": "inactive"}
  },
  "response_time_ms": 15.23
}
```

### Detailed Health Check
```
GET /api/metrics/health/detailed
```
Returns comprehensive health information including performance metrics.

### WebSocket Health Check
```
GET /api/ws/health
```
Returns WebSocket service health and connection statistics.

### Webhook Health Check
```
GET /api/webhooks/health
```
Returns webhook service health status.

## Metrics Endpoints

### System Metrics
```
GET /api/metrics/system
```
Returns comprehensive system metrics:
- Application metrics (workspaces, channels, agents)
- Business metrics (messages, tokens, conversations)
- Performance metrics (database connections, response times)
- Health metrics (stale conversations, failed documents)

### Workspace Metrics
```
GET /api/metrics/workspace/{workspace_id}
```
Returns metrics for a specific workspace including usage statistics and conversation metrics.

### Prometheus Metrics
```
GET /api/metrics/prometheus
```
Returns metrics in Prometheus exposition format for scraping:
```
chatsaas_workspaces_total 42
chatsaas_channels_total 156
chatsaas_agents_active 23
chatsaas_messages_sent_total 12345
chatsaas_tokens_used_total 987654
chatsaas_db_connections_active 8
chatsaas_health_score 95.0
chatsaas_conversations_stale 2
```

### Alert Status
```
GET /api/metrics/alerts/status
```
Returns current alert status and active alerts.

### Middleware Metrics
```
GET /metrics/middleware
```
Returns HTTP request metrics collected by monitoring middleware:
- Request counts by method, status, endpoint
- Response time statistics (avg, min, max, percentiles)
- Error rates and active request counts

## Monitoring Components

### 1. Metrics Service (`app/services/metrics_service.py`)
Collects and aggregates metrics from the database:
- **Application Metrics**: Workspace counts, channel statistics, agent counts
- **Business Metrics**: Message volumes, token usage, conversation statistics
- **Performance Metrics**: Database connection stats, response times
- **Health Metrics**: System health indicators, error counts

### 2. Alerting Service (`app/services/alerting_service.py`)
Monitors system health and generates alerts:
- **Database Health**: Connection counts, long-running queries
- **Conversation Backlog**: Stale escalations, high escalation rates
- **Document Processing**: Failed processing, stuck documents
- **Usage Patterns**: Unusual token consumption, resource exhaustion

### 3. Monitoring Middleware (`app/middleware/monitoring_middleware.py`)
Collects HTTP request metrics:
- Request/response tracking
- Performance monitoring
- Error rate calculation
- Endpoint usage statistics

### 4. Background Tasks (`app/tasks/monitoring_tasks.py`)
Periodic monitoring tasks:
- Health checks every 5 minutes (configurable)
- Metrics collection every 1 minute (configurable)
- Alert processing and notification

## Alert Types and Thresholds

### Critical Alerts
- **Service Down**: Application not responding
- **Database Connection Failed**: Cannot connect to database
- **High Error Rate**: >10% of requests failing (5-minute window)

### Warning Alerts
- **High Response Time**: P95 response time >2 seconds (10-minute window)
- **High Memory Usage**: >90% memory utilization (15-minute window)
- **Low Disk Space**: <5GB free space on storage volume
- **AI Provider Errors**: >5% AI provider error rate (10-minute window)
- **Stale Conversations**: >10 escalated conversations without activity (24+ hours)
- **Failed Documents**: >5 documents in failed processing state

### Configuration
Alert thresholds can be configured via environment variables:
```bash
ALERT_ERROR_RATE_THRESHOLD=0.05          # 5%
ALERT_RESPONSE_TIME_THRESHOLD=2000       # 2 seconds
ALERT_DB_CONNECTION_THRESHOLD=50         # connections
ALERT_STALE_CONVERSATION_THRESHOLD=10    # conversations
ALERT_FAILED_DOCUMENT_THRESHOLD=5        # documents
ALERT_DISK_SPACE_THRESHOLD=5.0          # GB
ALERT_MEMORY_USAGE_THRESHOLD=90.0       # percent
```

## Logging Configuration

### Log Levels
- **DEBUG**: Detailed debugging information
- **INFO**: General information about application flow
- **WARNING**: Warning conditions that should be monitored
- **ERROR**: Error conditions that need attention
- **CRITICAL**: Critical errors requiring immediate action

### Log Formats
- **Development**: Human-readable format with timestamps
- **Production**: JSON format for structured logging and analysis

### Log Files
- **Application Log**: `/var/log/chatsaas/chatsaas-backend.log`
- **Error Log**: `/var/log/chatsaas/chatsaas-backend-errors.log`
- **Log Rotation**: Daily rotation, 30-day retention, compressed

### Structured Logging
Production logs use JSON format with fields:
```json
{
  "timestamp": "2024-01-01T12:00:00.000Z",
  "level": "INFO",
  "logger": "app.services.message_processor",
  "message": "Message processed successfully",
  "module": "message_processor",
  "function": "process_message",
  "line": 123,
  "workspace_id": "uuid-here",
  "conversation_id": "uuid-here"
}
```

### Special Event Logging
- **Security Events**: Authentication failures, unauthorized access
- **Business Events**: Message processing, escalations, document uploads
- **Performance Events**: Slow operations, resource usage

## Setup and Deployment

### 1. Automatic Setup
Run the monitoring setup script:
```bash
sudo ./scripts/setup-monitoring.sh
```

This script:
- Creates monitoring directories and service user
- Sets up log rotation and permissions
- Installs health check scripts and systemd services
- Configures periodic health monitoring
- Sets up monitoring environment configuration

### 2. Manual Configuration

#### Environment Variables
```bash
# Application Configuration
APP_URL=http://localhost:8000
DATABASE_URL=postgresql://user:pass@localhost:5432/chatsaas
STORAGE_PATH=/var/chatsaas/storage
LOG_DIR=/var/log/chatsaas
ENVIRONMENT=production

# Monitoring Configuration
HEALTH_CHECK_INTERVAL=300
METRICS_COLLECTION_INTERVAL=60

# Alert Configuration
ADMIN_EMAIL=admin@your-domain.com
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

#### Systemd Services
The setup script creates:
- `chatsaas-health-monitor.service`: One-shot health check service
- `chatsaas-health-monitor.timer`: Timer for periodic health checks (every 5 minutes)

#### Log Rotation
Configured in `/etc/logrotate.d/chatsaas`:
- Daily rotation
- 30-day retention
- Compression enabled
- Service reload after rotation

### 3. External Monitoring Integration

#### Prometheus Integration
1. Configure Prometheus to scrape `/api/metrics/prometheus`
2. Import alerting rules from `monitoring.yml`
3. Set up notification channels (email, Slack, PagerDuty)

#### Grafana Dashboard
1. Import dashboard configuration from `monitoring_dashboard.json`
2. Configure data sources (Prometheus, ChatSaaS API)
3. Set up notification channels
4. Configure alert rules and thresholds

#### Example Prometheus Configuration
```yaml
scrape_configs:
  - job_name: 'chatsaas-backend'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/api/metrics/prometheus'
    scrape_interval: 30s
```

## Monitoring Best Practices

### 1. Health Check Strategy
- **Load Balancer**: Use basic `/health` endpoint
- **Deep Health**: Use `/api/metrics/health/detailed` for comprehensive checks
- **Dependency Checks**: Monitor database, storage, and external services
- **Graceful Degradation**: Continue serving traffic during partial failures

### 2. Metrics Collection
- **Business Metrics**: Track messages, conversations, escalations
- **Technical Metrics**: Monitor response times, error rates, resource usage
- **User Experience**: Track escalation rates, response quality
- **Capacity Planning**: Monitor growth trends and resource utilization

### 3. Alerting Strategy
- **Severity Levels**: Critical (immediate action), Warning (monitor), Info (awareness)
- **Alert Fatigue**: Avoid too many low-priority alerts
- **Escalation**: Route critical alerts to on-call personnel
- **Documentation**: Include runbooks and troubleshooting steps

### 4. Log Management
- **Structured Logging**: Use JSON format for machine parsing
- **Log Levels**: Appropriate levels for different environments
- **Retention**: Balance storage costs with debugging needs
- **Security**: Avoid logging sensitive information (passwords, tokens)

## Troubleshooting

### Common Issues

#### High Response Times
1. Check database connection pool usage
2. Review slow query logs
3. Monitor AI provider response times
4. Check system resource utilization

#### High Error Rates
1. Review error logs for patterns
2. Check external service availability
3. Monitor database connectivity
4. Verify configuration settings

#### Memory Issues
1. Monitor memory usage trends
2. Check for memory leaks in long-running processes
3. Review connection pool configurations
4. Monitor garbage collection metrics

#### Disk Space Issues
1. Check log file sizes and rotation
2. Monitor document storage growth
3. Review backup retention policies
4. Clean up temporary files

### Monitoring Commands

#### Check Service Status
```bash
chatsaas-monitoring-status
```

#### Manual Health Check
```bash
sudo -u chatsaas /usr/local/bin/chatsaas-health-check
```

#### View Recent Logs
```bash
tail -f /var/log/chatsaas/chatsaas-backend.log
journalctl -u chatsaas-backend -f
```

#### Check System Resources
```bash
htop
df -h
free -h
```

## Security Considerations

### 1. Metrics Endpoint Security
- Metrics endpoints require authentication (except Prometheus endpoint)
- Rate limiting on public endpoints
- No sensitive data in metrics or logs

### 2. Log Security
- Secure log file permissions (644, owned by service user)
- Log rotation to prevent disk exhaustion
- No passwords or tokens in logs

### 3. Alert Security
- Secure notification channels (encrypted email, HTTPS webhooks)
- Alert deduplication to prevent spam
- Sensitive information redacted from alerts

## Performance Impact

### Monitoring Overhead
- **Metrics Collection**: <1% CPU overhead
- **Request Monitoring**: <0.1ms per request
- **Health Checks**: Minimal impact (every 5 minutes)
- **Log Writing**: Asynchronous, minimal blocking

### Resource Usage
- **Memory**: ~50MB additional for monitoring components
- **Disk**: Log files (rotated daily, 30-day retention)
- **Network**: Minimal (health checks, metrics scraping)

## Maintenance

### Regular Tasks
- **Weekly**: Review alert thresholds and adjust as needed
- **Monthly**: Analyze performance trends and capacity planning
- **Quarterly**: Review and update monitoring configuration
- **Annually**: Audit log retention and storage requirements

### Updates
- Monitor for security updates to monitoring dependencies
- Test monitoring configuration changes in staging
- Document any custom modifications or extensions
- Keep monitoring documentation up to date