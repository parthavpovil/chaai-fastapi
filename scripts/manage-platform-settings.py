#!/usr/bin/env python3
"""
Platform Settings Management Script
Allows administrators to manage platform-wide settings from command line.
"""
import asyncio
import sys
import argparse
from pathlib import Path

# Add the backend directory to the Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.database import get_async_session
from app.models.platform_setting import PlatformSetting


async def list_settings():
    """List all platform settings"""
    print("📋 Current Platform Settings:")
    print("-" * 50)
    
    async with get_async_session() as session:
        result = await session.execute(
            "SELECT key, value, updated_at FROM platform_settings ORDER BY key"
        )
        settings = result.fetchall()
        
        if not settings:
            print("No settings found.")
            return
        
        for key, value, updated_at in settings:
            print(f"{key:30} = {value}")
            print(f"{'':30}   (updated: {updated_at})")
            print()


async def get_setting(key: str):
    """Get a specific platform setting"""
    async with get_async_session() as session:
        setting = await session.get(PlatformSetting, key)
        if setting:
            print(f"{key} = {setting.value}")
            print(f"Last updated: {setting.updated_at}")
        else:
            print(f"Setting '{key}' not found.")
            sys.exit(1)


async def set_setting(key: str, value: str):
    """Set a platform setting"""
    async with get_async_session() as session:
        setting = await session.get(PlatformSetting, key)
        if setting:
            old_value = setting.value
            setting.value = value
            print(f"Updated '{key}': {old_value} → {value}")
        else:
            setting = PlatformSetting(key=key, value=value)
            session.add(setting)
            print(f"Created '{key}' = {value}")
        
        await session.commit()


async def delete_setting(key: str):
    """Delete a platform setting"""
    async with get_async_session() as session:
        setting = await session.get(PlatformSetting, key)
        if setting:
            await session.delete(setting)
            await session.commit()
            print(f"Deleted setting '{key}'")
        else:
            print(f"Setting '{key}' not found.")
            sys.exit(1)


async def toggle_maintenance_mode():
    """Toggle maintenance mode on/off"""
    async with get_async_session() as session:
        setting = await session.get(PlatformSetting, "maintenance_mode")
        if not setting:
            setting = PlatformSetting(key="maintenance_mode", value="false")
            session.add(setting)
        
        current_value = setting.value.lower()
        new_value = "false" if current_value == "true" else "true"
        setting.value = new_value
        
        await session.commit()
        
        status = "ENABLED" if new_value == "true" else "DISABLED"
        print(f"🔧 Maintenance mode {status}")
        
        if new_value == "true":
            print("⚠️  System is now in maintenance mode - customer messages will receive maintenance message")
        else:
            print("✅ System is now operational - normal message processing resumed")


def main():
    """Main CLI function"""
    parser = argparse.ArgumentParser(description="Manage ChatSaaS platform settings")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List command
    subparsers.add_parser("list", help="List all platform settings")
    
    # Get command
    get_parser = subparsers.add_parser("get", help="Get a specific setting")
    get_parser.add_argument("key", help="Setting key to retrieve")
    
    # Set command
    set_parser = subparsers.add_parser("set", help="Set a platform setting")
    set_parser.add_argument("key", help="Setting key")
    set_parser.add_argument("value", help="Setting value")
    
    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a platform setting")
    delete_parser.add_argument("key", help="Setting key to delete")
    
    # Maintenance mode toggle
    subparsers.add_parser("maintenance", help="Toggle maintenance mode")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        if args.command == "list":
            asyncio.run(list_settings())
        elif args.command == "get":
            asyncio.run(get_setting(args.key))
        elif args.command == "set":
            asyncio.run(set_setting(args.key, args.value))
        elif args.command == "delete":
            asyncio.run(delete_setting(args.key))
        elif args.command == "maintenance":
            asyncio.run(toggle_maintenance_mode())
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()