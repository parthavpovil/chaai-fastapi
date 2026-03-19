#!/usr/bin/env python3
"""
Database Utilities
Comprehensive database management utilities for production operations.
"""
import asyncio
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import get_async_session, engine
from app.config import settings


class DatabaseUtils:
    """Comprehensive database utilities"""
    
    def __init__(self):
        self.stats = {}
    
    async def get_database_info(self) -> Dict:
        """Get comprehensive database information"""
        print("📊 Gathering database information...")
        
        info = {}
        
        try:
            async with engine.begin() as conn:
                # PostgreSQL version
                result = await conn.execute(text("SELECT version()"))
                info["postgresql_version"] = result.scalar()
                
                # Database size
                result = await conn.execute(text("""
                    SELECT pg_size_pretty(pg_database_size(current_database()))
                """))
                info["database_size"] = result.scalar()
                
                # Table count
                result = await conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """))
                info["table_count"] = result.scalar()
                
                # Extension info
                result = await conn.execute(text("""
                    SELECT extname, extversion 
                    FROM pg_extension 
                    ORDER BY extname
                """))
                info["extensions"] = [{"name": row[0], "version": row[1]} for row in result.fetchall()]
                
                # Connection info
                result = await conn.execute(text("""
                    SELECT count(*) as active_connections,
                           max(setting::int) as max_connections
                    FROM pg_stat_activity, pg_settings 
                    WHERE name = 'max_connections'
                    GROUP BY max_connections
                """))
                conn_info = result.fetchone()
                if conn_info:
                    info["connections"] = {
                        "active": conn_info[0],
                        "max": conn_info[1]
                    }
                
                return info
                
        except Exception as e:
            print(f"❌ Failed to get database info: {e}")
            return {}
    
    async def get_table_statistics(self) -> List[Dict]:
        """Get detailed table statistics"""
        print("📈 Gathering table statistics...")
        
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("""
                    SELECT 
                        schemaname,
                        tablename,
                        n_tup_ins as inserts,
                        n_tup_upd as updates,
                        n_tup_del as deletes,
                        n_live_tup as live_tuples,
                        n_dead_tup as dead_tuples,
                        last_vacuum,
                        last_autovacuum,
                        last_analyze,
                        last_autoanalyze,
                        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size
                    FROM pg_stat_user_tables 
                    ORDER BY n_live_tup DESC
                """))
                
                tables = []
                for row in result.fetchall():
                    tables.append({
                        "schema": row[0],
                        "table": row[1],
                        "inserts": row[2],
                        "updates": row[3],
                        "deletes": row[4],
                        "live_tuples": row[5],
                        "dead_tuples": row[6],
                        "last_vacuum": row[7].isoformat() if row[7] else None,
                        "last_autovacuum": row[8].isoformat() if row[8] else None,
                        "last_analyze": row[9].isoformat() if row[9] else None,
                        "last_autoanalyze": row[10].isoformat() if row[10] else None,
                        "size": row[11]
                    })
                
                return tables
                
        except Exception as e:
            print(f"❌ Failed to get table statistics: {e}")
            return []
    
    async def get_index_statistics(self) -> List[Dict]:
        """Get index usage statistics"""
        print("🔍 Gathering index statistics...")
        
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("""
                    SELECT 
                        schemaname,
                        tablename,
                        indexname,
                        idx_tup_read,
                        idx_tup_fetch,
                        pg_size_pretty(pg_relation_size(indexrelid)) as size
                    FROM pg_stat_user_indexes 
                    ORDER BY idx_tup_read DESC
                """))
                
                indexes = []
                for row in result.fetchall():
                    indexes.append({
                        "schema": row[0],
                        "table": row[1],
                        "index": row[2],
                        "tuples_read": row[3],
                        "tuples_fetched": row[4],
                        "size": row[5]
                    })
                
                return indexes
                
        except Exception as e:
            print(f"❌ Failed to get index statistics: {e}")
            return []
    
    async def check_data_integrity(self) -> Dict:
        """Check data integrity across tables"""
        print("🔍 Checking data integrity...")
        
        integrity_checks = {}
        
        try:
            async with get_async_session() as session:
                # Check foreign key constraints
                result = await session.execute(text("""
                    SELECT conname, conrelid::regclass, confrelid::regclass
                    FROM pg_constraint 
                    WHERE contype = 'f'
                """))
                
                fk_constraints = result.fetchall()
                integrity_checks["foreign_key_constraints"] = len(fk_constraints)
                
                # Check for orphaned records (example checks)
                checks = [
                    ("orphaned_messages", """
                        SELECT COUNT(*) FROM messages m 
                        LEFT JOIN conversations c ON m.conversation_id = c.id 
                        WHERE c.id IS NULL
                    """),
                    ("orphaned_conversations", """
                        SELECT COUNT(*) FROM conversations c 
                        LEFT JOIN contacts ct ON c.contact_id = ct.id 
                        WHERE ct.id IS NULL
                    """),
                    ("orphaned_document_chunks", """
                        SELECT COUNT(*) FROM document_chunks dc 
                        LEFT JOIN documents d ON dc.document_id = d.id 
                        WHERE d.id IS NULL
                    """),
                    ("inactive_workspaces_with_data", """
                        SELECT COUNT(DISTINCT w.id) FROM workspaces w 
                        JOIN conversations c ON w.id = c.workspace_id 
                        WHERE w.tier = 'inactive'
                    """)
                ]
                
                for check_name, query in checks:
                    try:
                        result = await session.execute(text(query))
                        count = result.scalar()
                        integrity_checks[check_name] = count
                        
                        if count > 0:
                            print(f"⚠️  Found {count} {check_name.replace('_', ' ')}")
                        
                    except Exception as e:
                        print(f"⚠️  Could not run check {check_name}: {e}")
                        integrity_checks[check_name] = "error"
                
                return integrity_checks
                
        except Exception as e:
            print(f"❌ Data integrity check failed: {e}")
            return {}
    
    async def analyze_workspace_usage(self) -> List[Dict]:
        """Analyze workspace usage patterns"""
        print("📊 Analyzing workspace usage...")
        
        try:
            async with get_async_session() as session:
                result = await session.execute(text("""
                    SELECT 
                        w.id,
                        w.name,
                        w.tier,
                        w.created_at,
                        COUNT(DISTINCT c.id) as channels,
                        COUNT(DISTINCT ct.id) as contacts,
                        COUNT(DISTINCT conv.id) as conversations,
                        COUNT(DISTINCT m.id) as messages,
                        COUNT(DISTINCT d.id) as documents,
                        COUNT(DISTINCT a.id) as agents,
                        COALESCE(uc.messages_sent, 0) as monthly_messages,
                        COALESCE(uc.tokens_used, 0) as monthly_tokens
                    FROM workspaces w
                    LEFT JOIN channels c ON w.id = c.workspace_id
                    LEFT JOIN contacts ct ON w.id = ct.workspace_id
                    LEFT JOIN conversations conv ON w.id = conv.workspace_id
                    LEFT JOIN messages m ON conv.id = m.conversation_id
                    LEFT JOIN documents d ON w.id = d.workspace_id
                    LEFT JOIN agents a ON w.id = a.workspace_id
                    LEFT JOIN usage_counters uc ON w.id = uc.workspace_id 
                        AND uc.month = to_char(CURRENT_DATE, 'YYYY-MM')
                    GROUP BY w.id, w.name, w.tier, w.created_at, uc.messages_sent, uc.tokens_used
                    ORDER BY monthly_messages DESC
                """))
                
                workspaces = []
                for row in result.fetchall():
                    workspaces.append({
                        "workspace_id": str(row[0]),
                        "name": row[1],
                        "tier": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                        "channels": row[4],
                        "contacts": row[5],
                        "conversations": row[6],
                        "messages": row[7],
                        "documents": row[8],
                        "agents": row[9],
                        "monthly_messages": row[10],
                        "monthly_tokens": row[11]
                    })
                
                return workspaces
                
        except Exception as e:
            print(f"❌ Workspace usage analysis failed: {e}")
            return []
    
    async def get_performance_metrics(self) -> Dict:
        """Get database performance metrics"""
        print("⚡ Gathering performance metrics...")
        
        try:
            async with engine.begin() as conn:
                metrics = {}
                
                # Query performance
                result = await conn.execute(text("""
                    SELECT 
                        query,
                        calls,
                        total_time,
                        mean_time,
                        rows
                    FROM pg_stat_statements 
                    ORDER BY total_time DESC 
                    LIMIT 10
                """))
                
                slow_queries = []
                for row in result.fetchall():
                    slow_queries.append({
                        "query": row[0][:100] + "..." if len(row[0]) > 100 else row[0],
                        "calls": row[1],
                        "total_time": float(row[2]),
                        "mean_time": float(row[3]),
                        "rows": row[4]
                    })
                
                metrics["slow_queries"] = slow_queries
                
                # Cache hit ratio
                result = await conn.execute(text("""
                    SELECT 
                        sum(heap_blks_read) as heap_read,
                        sum(heap_blks_hit) as heap_hit,
                        sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as ratio
                    FROM pg_statio_user_tables
                """))
                
                cache_stats = result.fetchone()
                if cache_stats and cache_stats[2]:
                    metrics["cache_hit_ratio"] = float(cache_stats[2])
                
                # Lock information
                result = await conn.execute(text("""
                    SELECT mode, count(*) 
                    FROM pg_locks 
                    GROUP BY mode 
                    ORDER BY count(*) DESC
                """))
                
                locks = {}
                for row in result.fetchall():
                    locks[row[0]] = row[1]
                
                metrics["locks"] = locks
                
                return metrics
                
        except Exception as e:
            print(f"⚠️  Performance metrics collection failed (pg_stat_statements may not be enabled): {e}")
            return {}
    
    async def generate_health_report(self) -> Dict:
        """Generate comprehensive database health report"""
        print("🏥 Generating database health report...")
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "database_info": await self.get_database_info(),
            "table_statistics": await self.get_table_statistics(),
            "index_statistics": await self.get_index_statistics(),
            "integrity_checks": await self.check_data_integrity(),
            "workspace_usage": await self.analyze_workspace_usage(),
            "performance_metrics": await self.get_performance_metrics()
        }
        
        # Calculate summary statistics
        tables = report["table_statistics"]
        if tables:
            total_live_tuples = sum(t["live_tuples"] for t in tables)
            total_dead_tuples = sum(t["dead_tuples"] for t in tables)
            
            report["summary"] = {
                "total_tables": len(tables),
                "total_live_tuples": total_live_tuples,
                "total_dead_tuples": total_dead_tuples,
                "dead_tuple_ratio": total_dead_tuples / (total_live_tuples + total_dead_tuples) if (total_live_tuples + total_dead_tuples) > 0 else 0,
                "workspaces_count": len(report["workspace_usage"]),
                "active_workspaces": len([w for w in report["workspace_usage"] if w["monthly_messages"] > 0])
            }
        
        return report
    
    def save_report(self, report: Dict, filename: Optional[str] = None):
        """Save health report to file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"database_health_report_{timestamp}.json"
        
        report_file = backend_dir / "logs" / filename
        report_file.parent.mkdir(exist_ok=True)
        
        try:
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2, default=str)
            
            print(f"📄 Health report saved: {report_file}")
            return str(report_file)
            
        except Exception as e:
            print(f"❌ Failed to save report: {e}")
            return None
    
    def print_summary(self, report: Dict):
        """Print health report summary"""
        print("\n" + "="*60)
        print("📋 Database Health Report Summary")
        print("="*60)
        
        # Database info
        db_info = report.get("database_info", {})
        if db_info:
            print(f"Database Size: {db_info.get('database_size', 'Unknown')}")
            print(f"Tables: {db_info.get('table_count', 'Unknown')}")
            print(f"Extensions: {len(db_info.get('extensions', []))}")
            
            connections = db_info.get("connections", {})
            if connections:
                print(f"Connections: {connections.get('active', 0)}/{connections.get('max', 0)}")
        
        # Summary stats
        summary = report.get("summary", {})
        if summary:
            print(f"Total Workspaces: {summary.get('workspaces_count', 0)}")
            print(f"Active Workspaces: {summary.get('active_workspaces', 0)}")
            print(f"Live Tuples: {summary.get('total_live_tuples', 0):,}")
            print(f"Dead Tuples: {summary.get('total_dead_tuples', 0):,}")
            
            dead_ratio = summary.get('dead_tuple_ratio', 0)
            if dead_ratio > 0.1:
                print(f"⚠️  Dead Tuple Ratio: {dead_ratio:.2%} (consider VACUUM)")
            else:
                print(f"✅ Dead Tuple Ratio: {dead_ratio:.2%}")
        
        # Integrity issues
        integrity = report.get("integrity_checks", {})
        issues = [k for k, v in integrity.items() if isinstance(v, int) and v > 0]
        if issues:
            print(f"⚠️  Integrity Issues: {len(issues)} types found")
        else:
            print("✅ No integrity issues detected")
        
        # Performance
        performance = report.get("performance_metrics", {})
        if "cache_hit_ratio" in performance:
            cache_ratio = performance["cache_hit_ratio"]
            if cache_ratio < 0.9:
                print(f"⚠️  Cache Hit Ratio: {cache_ratio:.2%} (consider more memory)")
            else:
                print(f"✅ Cache Hit Ratio: {cache_ratio:.2%}")


async def main():
    """Main database utilities function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Database Utilities")
    parser.add_argument("--info", action="store_true", help="Show database information")
    parser.add_argument("--tables", action="store_true", help="Show table statistics")
    parser.add_argument("--indexes", action="store_true", help="Show index statistics")
    parser.add_argument("--integrity", action="store_true", help="Check data integrity")
    parser.add_argument("--workspaces", action="store_true", help="Analyze workspace usage")
    parser.add_argument("--performance", action="store_true", help="Show performance metrics")
    parser.add_argument("--health-report", action="store_true", help="Generate comprehensive health report")
    parser.add_argument("--save-report", type=str, help="Save report to specified file")
    parser.add_argument("--all", action="store_true", help="Show all information")
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    utils = DatabaseUtils()
    
    print("🔧 ChatSaaS Database Utilities")
    print("=" * 50)
    
    try:
        if args.health_report or args.all:
            report = await utils.generate_health_report()
            utils.print_summary(report)
            
            if args.save_report:
                utils.save_report(report, args.save_report)
            elif args.health_report:
                utils.save_report(report)
        
        else:
            if args.info or args.all:
                info = await utils.get_database_info()
                print("\n📊 Database Information:")
                for key, value in info.items():
                    if key == "extensions":
                        print(f"  {key}: {len(value)} installed")
                    else:
                        print(f"  {key}: {value}")
            
            if args.tables or args.all:
                tables = await utils.get_table_statistics()
                print(f"\n📈 Table Statistics ({len(tables)} tables):")
                for table in tables[:10]:  # Show top 10
                    print(f"  {table['table']}: {table['live_tuples']:,} live, {table['dead_tuples']:,} dead, {table['size']}")
            
            if args.indexes or args.all:
                indexes = await utils.get_index_statistics()
                print(f"\n🔍 Index Statistics ({len(indexes)} indexes):")
                for index in indexes[:10]:  # Show top 10
                    print(f"  {index['index']}: {index['tuples_read']:,} reads, {index['size']}")
            
            if args.integrity or args.all:
                integrity = await utils.check_data_integrity()
                print("\n🔍 Data Integrity Checks:")
                for check, result in integrity.items():
                    status = "✅" if result == 0 else "⚠️"
                    print(f"  {status} {check}: {result}")
            
            if args.workspaces or args.all:
                workspaces = await utils.analyze_workspace_usage()
                print(f"\n📊 Workspace Usage ({len(workspaces)} workspaces):")
                for workspace in workspaces[:10]:  # Show top 10
                    print(f"  {workspace['name']} ({workspace['tier']}): "
                          f"{workspace['messages']:,} messages, {workspace['monthly_messages']:,} this month")
            
            if args.performance or args.all:
                performance = await utils.get_performance_metrics()
                print("\n⚡ Performance Metrics:")
                if "cache_hit_ratio" in performance:
                    print(f"  Cache Hit Ratio: {performance['cache_hit_ratio']:.2%}")
                if "slow_queries" in performance:
                    print(f"  Slow Queries: {len(performance['slow_queries'])} found")
        
        return True
        
    except Exception as e:
        print(f"❌ Database utilities failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)