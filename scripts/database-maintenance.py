#!/usr/bin/env python3
"""
Database Maintenance Script
Performs routine database maintenance tasks like VACUUM, ANALYZE, and index maintenance.
"""
import asyncio
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database import engine
from app.config import settings


class DatabaseMaintenance:
    """Database maintenance operations"""
    
    def __init__(self):
        self.stats = {
            "tables_vacuumed": 0,
            "tables_analyzed": 0,
            "indexes_reindexed": 0,
            "dead_tuples_removed": 0
        }
    
    async def get_table_stats(self):
        """Get database table statistics"""
        print("📊 Gathering database statistics...")
        
        query = """
        SELECT 
            schemaname,
            tablename,
            n_tup_ins as inserts,
            n_tup_upd as updates,
            n_tup_del as deletes,
            n_dead_tup as dead_tuples,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze
        FROM pg_stat_user_tables 
        ORDER BY n_dead_tup DESC;
        """
        
        async with engine.begin() as conn:
            result = await conn.execute(text(query))
            tables = result.fetchall()
            
            print(f"\n{'Table':<30} {'Dead Tuples':<12} {'Last Vacuum':<20} {'Last Analyze':<20}")
            print("-" * 85)
            
            for table in tables:
                last_vacuum = table.last_vacuum or table.last_autovacuum or "Never"
                last_analyze = table.last_analyze or table.last_autoanalyze or "Never"
                
                if isinstance(last_vacuum, datetime):
                    last_vacuum = last_vacuum.strftime("%Y-%m-%d %H:%M")
                if isinstance(last_analyze, datetime):
                    last_analyze = last_analyze.strftime("%Y-%m-%d %H:%M")
                
                print(f"{table.tablename:<30} {table.dead_tuples:<12} {str(last_vacuum):<20} {str(last_analyze):<20}")
            
            return tables
    
    async def vacuum_tables(self, analyze=True, full=False):
        """Vacuum database tables"""
        operation = "VACUUM FULL ANALYZE" if full else "VACUUM ANALYZE" if analyze else "VACUUM"
        print(f"🧹 Running {operation} on all tables...")
        
        # Get list of user tables
        query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        
        async with engine.begin() as conn:
            result = await conn.execute(text(query))
            tables = [row[0] for row in result.fetchall()]
            
            for table in tables:
                print(f"  Processing table: {table}")
                
                try:
                    if full:
                        await conn.execute(text(f"VACUUM FULL ANALYZE {table}"))
                    elif analyze:
                        await conn.execute(text(f"VACUUM ANALYZE {table}"))
                    else:
                        await conn.execute(text(f"VACUUM {table}"))
                    
                    self.stats["tables_vacuumed"] += 1
                    if analyze:
                        self.stats["tables_analyzed"] += 1
                    
                except Exception as e:
                    print(f"    ⚠️  Error processing {table}: {e}")
        
        print(f"✅ Vacuumed {self.stats['tables_vacuumed']} tables")
    
    async def reindex_tables(self, concurrent=True):
        """Reindex database tables"""
        print("🔄 Reindexing database tables...")
        
        # Get list of indexes
        query = """
        SELECT indexname, tablename 
        FROM pg_indexes 
        WHERE schemaname = 'public' 
        AND indexname NOT LIKE 'pg_%'
        ORDER BY tablename, indexname
        """
        
        async with engine.begin() as conn:
            result = await conn.execute(text(query))
            indexes = result.fetchall()
            
            for index in indexes:
                print(f"  Reindexing: {index.indexname}")
                
                try:
                    if concurrent:
                        await conn.execute(text(f"REINDEX INDEX CONCURRENTLY {index.indexname}"))
                    else:
                        await conn.execute(text(f"REINDEX INDEX {index.indexname}"))
                    
                    self.stats["indexes_reindexed"] += 1
                    
                except Exception as e:
                    print(f"    ⚠️  Error reindexing {index.indexname}: {e}")
        
        print(f"✅ Reindexed {self.stats['indexes_reindexed']} indexes")
    
    async def analyze_tables(self):
        """Update table statistics"""
        print("📈 Updating table statistics...")
        
        query = "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        
        async with engine.begin() as conn:
            result = await conn.execute(text(query))
            tables = [row[0] for row in result.fetchall()]
            
            for table in tables:
                print(f"  Analyzing table: {table}")
                
                try:
                    await conn.execute(text(f"ANALYZE {table}"))
                    self.stats["tables_analyzed"] += 1
                    
                except Exception as e:
                    print(f"    ⚠️  Error analyzing {table}: {e}")
        
        print(f"✅ Analyzed {self.stats['tables_analyzed']} tables")
    
    async def check_bloat(self):
        """Check for table and index bloat"""
        print("🔍 Checking for table and index bloat...")
        
        # Table bloat query
        table_bloat_query = """
        SELECT 
            tablename,
            ROUND(CASE WHEN otta=0 THEN 0.0 ELSE sml.relpages/otta::numeric END,1) AS tbloat,
            CASE WHEN relpages < otta THEN 0 ELSE bs*(sml.relpages-otta)::bigint END AS wastedbytes,
            pg_size_pretty(CASE WHEN relpages < otta THEN 0 ELSE bs*(sml.relpages-otta)::bigint END) AS wastedsize
        FROM (
            SELECT
                schemaname, tablename, cc.reltuples, cc.relpages, bs,
                CEIL((cc.reltuples*((datahdr+ma-
                    (CASE WHEN datahdr%ma=0 THEN ma ELSE datahdr%ma END))+nullhdr2+4))/(bs-20::float)) AS otta
            FROM (
                SELECT
                    ma,bs,schemaname,tablename,
                    (datawidth+(hdr+ma-(case when hdr%ma=0 THEN ma ELSE hdr%ma END)))::numeric AS datahdr,
                    (maxfracsum*(nullhdr+ma-(case when nullhdr%ma=0 THEN ma ELSE nullhdr%ma END))) AS nullhdr2
                FROM (
                    SELECT
                        schemaname, tablename, hdr, ma, bs,
                        SUM((1-null_frac)*avg_width) AS datawidth,
                        MAX(null_frac) AS maxfracsum,
                        hdr+(
                            SELECT 1+count(*)/8
                            FROM pg_stats s2
                            WHERE null_frac<>0 AND s2.schemaname = s.schemaname AND s2.tablename = s.tablename
                        ) AS nullhdr
                    FROM pg_stats s, (
                        SELECT
                            (SELECT current_setting('block_size')::numeric) AS bs,
                            CASE WHEN substring(v,12,3) IN ('8.0','8.1','8.2') THEN 27 ELSE 23 END AS hdr,
                            CASE WHEN v ~ 'mingw32' THEN 8 ELSE 4 END AS ma
                        FROM (SELECT version() AS v) AS foo
                    ) AS constants
                    WHERE schemaname='public'
                    GROUP BY 1,2,3,4,5
                ) AS foo
            ) AS rs
            JOIN pg_class cc ON cc.relname = rs.tablename
            JOIN pg_namespace nn ON cc.relnamespace = nn.oid AND nn.nspname = rs.schemaname AND nn.nspname <> 'information_schema'
        ) AS sml
        WHERE tbloat > 1.5
        ORDER BY wastedbytes DESC;
        """
        
        async with engine.begin() as conn:
            result = await conn.execute(text(table_bloat_query))
            bloated_tables = result.fetchall()
            
            if bloated_tables:
                print("\n🚨 Tables with significant bloat (>1.5x):")
                print(f"{'Table':<30} {'Bloat Ratio':<12} {'Wasted Space':<15}")
                print("-" * 60)
                
                for table in bloated_tables:
                    print(f"{table.tablename:<30} {table.tbloat:<12} {table.wastedsize:<15}")
                
                print("\n💡 Consider running VACUUM FULL on heavily bloated tables during maintenance windows")
            else:
                print("✅ No significant table bloat detected")
    
    async def get_database_size(self):
        """Get database size information"""
        print("💾 Database size information:")
        
        queries = {
            "Total database size": "SELECT pg_size_pretty(pg_database_size(current_database()))",
            "Total table size": "SELECT pg_size_pretty(sum(pg_total_relation_size(oid))) FROM pg_class WHERE relkind = 'r'",
            "Total index size": "SELECT pg_size_pretty(sum(pg_total_relation_size(oid))) FROM pg_class WHERE relkind = 'i'",
        }
        
        async with engine.begin() as conn:
            for description, query in queries.items():
                result = await conn.execute(text(query))
                size = result.scalar()
                print(f"  {description}: {size}")
    
    async def print_summary(self):
        """Print maintenance summary"""
        print("\n" + "="*60)
        print("🎉 Database Maintenance Summary")
        print("="*60)
        print(f"Tables vacuumed: {self.stats['tables_vacuumed']}")
        print(f"Tables analyzed: {self.stats['tables_analyzed']}")
        print(f"Indexes reindexed: {self.stats['indexes_reindexed']}")
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


async def main():
    """Main maintenance function"""
    parser = argparse.ArgumentParser(description="ChatSaaS Database Maintenance")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--vacuum", action="store_true", help="Vacuum all tables")
    parser.add_argument("--vacuum-full", action="store_true", help="Full vacuum all tables (locks tables)")
    parser.add_argument("--analyze", action="store_true", help="Analyze all tables")
    parser.add_argument("--reindex", action="store_true", help="Reindex all indexes")
    parser.add_argument("--bloat", action="store_true", help="Check for table bloat")
    parser.add_argument("--size", action="store_true", help="Show database size information")
    parser.add_argument("--all", action="store_true", help="Run all maintenance tasks")
    
    args = parser.parse_args()
    
    if not any(vars(args).values()):
        parser.print_help()
        return
    
    maintenance = DatabaseMaintenance()
    
    print("🔧 ChatSaaS Database Maintenance")
    print("=" * 50)
    
    try:
        if args.stats or args.all:
            await maintenance.get_table_stats()
        
        if args.size or args.all:
            await maintenance.get_database_size()
        
        if args.bloat or args.all:
            await maintenance.check_bloat()
        
        if args.vacuum or args.all:
            await maintenance.vacuum_tables(analyze=True)
        elif args.vacuum_full:
            await maintenance.vacuum_tables(analyze=True, full=True)
        elif args.analyze:
            await maintenance.analyze_tables()
        
        if args.reindex or args.all:
            await maintenance.reindex_tables()
        
        await maintenance.print_summary()
        
    except Exception as e:
        print(f"❌ Maintenance failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())