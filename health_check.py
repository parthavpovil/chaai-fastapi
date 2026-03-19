#!/usr/bin/env python3
"""
ChatSaaS Backend Health Check Script
This script performs comprehensive health checks for production monitoring
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from typing import Dict, Any, List
import aiohttp
import asyncpg
from pathlib import Path
import os

# Configuration
HEALTH_CHECK_CONFIG = {
    "app_url": os.getenv("APP_URL", "http://localhost:8000"),
    "database_url": os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/chatsaas"),
    "storage_path": os.getenv("STORAGE_PATH", "/var/chatsaas/storage"),
    "timeout": 10,
    "critical_thresholds": {
        "response_time_ms": 5000,
        "disk_free_gb": 5,
        "memory_usage_percent": 90
    }
}

class HealthChecker:
    """Comprehensive health checker for ChatSaaS Backend"""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "unknown",
            "checks": {},
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "warnings": 0
            }
        }
    
    async def check_application_health(self) -> Dict[str, Any]:
        """Check application health endpoint"""
        check_name = "application_health"
        start_time = time.time()
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HEALTH_CHECK_CONFIG["timeout"])) as session:
                async with session.get(f"{HEALTH_CHECK_CONFIG['app_url']}/health") as response:
                    response_time = (time.time() - start_time) * 1000
                    
                    if response.status == 200:
                        data = await response.json()
                        
                        result = {
                            "status": "pass" if response_time < HEALTH_CHECK_CONFIG["critical_thresholds"]["response_time_ms"] else "warn",
                            "response_time_ms": round(response_time, 2),
                            "http_status": response.status,
                            "response_data": data
                        }
                        
                        if response_time >= HEALTH_CHECK_CONFIG["critical_thresholds"]["response_time_ms"]:
                            result["warning"] = f"Response time {response_time:.2f}ms exceeds threshold"
                    else:
                        result = {
                            "status": "fail",
                            "response_time_ms": round(response_time, 2),
                            "http_status": response.status,
                            "error": f"HTTP {response.status}"
                        }
        
        except asyncio.TimeoutError:
            result = {
                "status": "fail",
                "error": "Request timeout",
                "timeout_seconds": HEALTH_CHECK_CONFIG["timeout"]
            }
        except Exception as e:
            result = {
                "status": "fail",
                "error": str(e)
            }
        
        return {check_name: result}
    
    async def check_database_connectivity(self) -> Dict[str, Any]:
        """Check database connectivity and basic operations"""
        check_name = "database_connectivity"
        start_time = time.time()
        
        try:
            # Parse database URL for asyncpg
            db_url = HEALTH_CHECK_CONFIG["database_url"]
            if db_url.startswith("postgresql+asyncpg://"):
                db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
            
            conn = await asyncpg.connect(db_url)
            
            # Test basic query
            await conn.execute("SELECT 1")
            
            # Check if pgvector extension is available
            vector_check = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
            
            # Get connection count
            connection_count = await conn.fetchval("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
            
            await conn.close()
            
            response_time = (time.time() - start_time) * 1000
            
            result = {
                "status": "pass",
                "response_time_ms": round(response_time, 2),
                "pgvector_available": vector_check,
                "active_connections": connection_count
            }
            
        except Exception as e:
            result = {
                "status": "fail",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2)
            }
        
        return {check_name: result}
    
    def check_storage_availability(self) -> Dict[str, Any]:
        """Check file storage availability and disk space"""
        check_name = "storage_availability"
        
        try:
            storage_path = Path(HEALTH_CHECK_CONFIG["storage_path"])
            
            # Check if storage path exists and is writable
            if not storage_path.exists():
                return {check_name: {
                    "status": "fail",
                    "error": f"Storage path does not exist: {storage_path}"
                }}
            
            if not os.access(storage_path, os.W_OK):
                return {check_name: {
                    "status": "fail",
                    "error": f"Storage path is not writable: {storage_path}"
                }}
            
            # Check disk space
            stat = os.statvfs(storage_path)
            free_bytes = stat.f_bavail * stat.f_frsize
            total_bytes = stat.f_blocks * stat.f_frsize
            free_gb = free_bytes / (1024**3)
            total_gb = total_bytes / (1024**3)
            used_percent = ((total_bytes - free_bytes) / total_bytes) * 100
            
            status = "pass"
            warnings = []
            
            if free_gb < HEALTH_CHECK_CONFIG["critical_thresholds"]["disk_free_gb"]:
                status = "fail"
                warnings.append(f"Low disk space: {free_gb:.2f}GB free")
            elif free_gb < HEALTH_CHECK_CONFIG["critical_thresholds"]["disk_free_gb"] * 2:
                status = "warn"
                warnings.append(f"Disk space warning: {free_gb:.2f}GB free")
            
            result = {
                "status": status,
                "free_space_gb": round(free_gb, 2),
                "total_space_gb": round(total_gb, 2),
                "used_percent": round(used_percent, 2),
                "path": str(storage_path)
            }
            
            if warnings:
                result["warnings"] = warnings
            
        except Exception as e:
            result = {
                "status": "fail",
                "error": str(e)
            }
        
        return {check_name: result}
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage"""
        check_name = "system_resources"
        
        try:
            import psutil
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # Load average (Unix only)
            load_avg = None
            if hasattr(os, 'getloadavg'):
                load_avg = os.getloadavg()
            
            status = "pass"
            warnings = []
            
            if memory_percent > HEALTH_CHECK_CONFIG["critical_thresholds"]["memory_usage_percent"]:
                status = "fail"
                warnings.append(f"High memory usage: {memory_percent:.1f}%")
            elif memory_percent > HEALTH_CHECK_CONFIG["critical_thresholds"]["memory_usage_percent"] * 0.8:
                status = "warn"
                warnings.append(f"Memory usage warning: {memory_percent:.1f}%")
            
            if cpu_percent > 90:
                if status != "fail":
                    status = "warn"
                warnings.append(f"High CPU usage: {cpu_percent:.1f}%")
            
            result = {
                "status": status,
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_available_gb": round(memory.available / (1024**3), 2),
                "memory_total_gb": round(memory.total / (1024**3), 2)
            }
            
            if load_avg:
                result["load_average"] = {
                    "1min": load_avg[0],
                    "5min": load_avg[1],
                    "15min": load_avg[2]
                }
            
            if warnings:
                result["warnings"] = warnings
            
        except ImportError:
            result = {
                "status": "warn",
                "error": "psutil not available - install with: pip install psutil"
            }
        except Exception as e:
            result = {
                "status": "fail",
                "error": str(e)
            }
        
        return {check_name: result}
    
    async def run_all_checks(self) -> Dict[str, Any]:
        """Run all health checks"""
        checks = []
        
        # Application health check
        checks.append(self.check_application_health())
        
        # Database connectivity check
        checks.append(self.check_database_connectivity())
        
        # Storage availability check (synchronous)
        storage_result = self.check_storage_availability()
        
        # System resources check (synchronous)
        system_result = self.check_system_resources()
        
        # Run async checks
        async_results = await asyncio.gather(*checks, return_exceptions=True)
        
        # Combine all results
        for result in async_results:
            if isinstance(result, Exception):
                check_name = f"error_{len(self.results['checks'])}"
                self.results["checks"][check_name] = {
                    "status": "fail",
                    "error": str(result)
                }
            else:
                self.results["checks"].update(result)
        
        # Add synchronous results
        self.results["checks"].update(storage_result)
        self.results["checks"].update(system_result)
        
        # Calculate summary
        for check_name, check_result in self.results["checks"].items():
            self.results["summary"]["total"] += 1
            
            status = check_result.get("status", "unknown")
            if status == "pass":
                self.results["summary"]["passed"] += 1
            elif status == "warn":
                self.results["summary"]["warnings"] += 1
            else:
                self.results["summary"]["failed"] += 1
        
        # Determine overall status
        if self.results["summary"]["failed"] > 0:
            self.results["overall_status"] = "fail"
        elif self.results["summary"]["warnings"] > 0:
            self.results["overall_status"] = "warn"
        else:
            self.results["overall_status"] = "pass"
        
        return self.results

async def main():
    """Main function"""
    checker = HealthChecker()
    results = await checker.run_all_checks()
    
    # Output results as JSON
    print(json.dumps(results, indent=2))
    
    # Exit with appropriate code
    if results["overall_status"] == "fail":
        sys.exit(1)
    elif results["overall_status"] == "warn":
        sys.exit(2)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())