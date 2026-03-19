"""
Logging Configuration for Production Monitoring

Configures structured logging with appropriate levels and formatters
"""

import logging
import logging.config
import os
import sys
from datetime import datetime
import json

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                          'filename', 'module', 'lineno', 'funcName', 'created', 
                          'msecs', 'relativeCreated', 'thread', 'threadName', 
                          'processName', 'process', 'getMessage', 'exc_info', 
                          'exc_text', 'stack_info']:
                log_entry[key] = value
        
        return json.dumps(log_entry)

def setup_logging():
    """Setup logging configuration"""
    
    # Determine log level
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Determine if we're in production
    is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
    
    # Log directory
    log_dir = os.getenv("LOG_DIR", "/var/log/chatsaas" if is_production else "./logs")
    os.makedirs(log_dir, exist_ok=True)
    
    # Logging configuration
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            },
            "detailed": {
                "format": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s"
            },
            "json": {
                "()": JSONFormatter
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard" if not is_production else "json",
                "stream": sys.stdout
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": log_level,
                "formatter": "json" if is_production else "detailed",
                "filename": os.path.join(log_dir, "chatsaas-backend.log"),
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "json" if is_production else "detailed",
                "filename": os.path.join(log_dir, "chatsaas-backend-errors.log"),
                "maxBytes": 10485760,  # 10MB
                "backupCount": 10
            }
        },
        "loggers": {
            # Application loggers
            "app": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False
            },
            "app.services": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False
            },
            "app.routers": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False
            },
            "app.middleware": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False
            },
            "app.tasks": {
                "level": log_level,
                "handlers": ["console", "file", "error_file"],
                "propagate": False
            },
            
            # Third-party loggers
            "sqlalchemy.engine": {
                "level": "WARNING",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            },
            "fastapi": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False
            }
        },
        "root": {
            "level": log_level,
            "handlers": ["console", "file", "error_file"]
        }
    }
    
    # Apply configuration
    logging.config.dictConfig(config)
    
    # Log startup message
    logger = logging.getLogger("app")
    logger.info(f"Logging configured - Level: {log_level}, Production: {is_production}, Log Dir: {log_dir}")
    
    return logger

# Security and audit logging
def log_security_event(event_type: str, user_id: str = None, workspace_id: str = None, 
                      details: dict = None, severity: str = "INFO"):
    """Log security-related events"""
    logger = logging.getLogger("app.security")
    
    log_data = {
        "event_type": event_type,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "details": details or {},
        "severity": severity
    }
    
    if severity == "CRITICAL":
        logger.critical("Security event", extra=log_data)
    elif severity == "WARNING":
        logger.warning("Security event", extra=log_data)
    else:
        logger.info("Security event", extra=log_data)

def log_business_event(event_type: str, workspace_id: str, details: dict = None):
    """Log business-related events"""
    logger = logging.getLogger("app.business")
    
    log_data = {
        "event_type": event_type,
        "workspace_id": workspace_id,
        "details": details or {}
    }
    
    logger.info("Business event", extra=log_data)

def log_performance_event(event_type: str, duration_ms: float, details: dict = None):
    """Log performance-related events"""
    logger = logging.getLogger("app.performance")
    
    log_data = {
        "event_type": event_type,
        "duration_ms": duration_ms,
        "details": details or {}
    }
    
    if duration_ms > 5000:  # More than 5 seconds
        logger.warning("Slow operation", extra=log_data)
    else:
        logger.info("Performance event", extra=log_data)

# Initialize logging when module is imported
if __name__ != "__main__":
    setup_logging()