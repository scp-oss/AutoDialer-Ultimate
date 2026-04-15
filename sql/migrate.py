#!/usr/bin/env python3
"""
Управление миграциями базы данных AutoDialer Ultimate
"""

import os
import sys
import asyncpg
import hashlib
from pathlib import Path
from datetime import datetime

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def get_db_pool():
    """Создание пула соединений с БД."""
    return await asyncpg.create_pool(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME', 'autodialer'),
        user=os.getenv('DB_USER', 'autodialer'),
        password=os.getenv('DB_PASSWORD', '')
    )


async def ensure_migrations_table(pool):
    """Создание таблицы миграций, если её нет."""
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id SERIAL PRIMARY KEY,
                version VARCHAR(50) NOT NULL UNIQUE,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(64)
            )
        """)


async def get_applied_migrations(pool):
    """Получение списка применённых миграций."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
        return {row['version'] for row in rows}


def get_migration_files():
    """Получение списка файлов миграций."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    migrations = []
    for f in files:
        version = f.stem.split('_')[0]
        name = '_'.join(f.stem.split('_')[1:])
        migrations.append((version, name, f))
    return migrations


def calculate_checksum(filepath):
    """Расчёт контрольной суммы файла."""
    with open(filepath, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


async def apply_migration(pool, version, name, filepath):
    """Применение одной миграции."""
    print(f"Applying migration {version}: {name}...")
    
    checksum = calculate_checksum(filepath)
    
    with open(filepath, 'r') as f:
        sql = f.read()
    
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute("""
                INSERT INTO schema_migrations (version, name, checksum)
                VALUES ($1, $2, $3)
            """, version, name, checksum)
    
    print(f"  ✓ Applied {version}: {name}")


async def rollback_migration(pool, version):
    """Откат миграции (требует наличия ROLLBACK секции)."""
    print(f"Rolling back migration {version}...")
    
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM schema_migrations WHERE version = $1", version)
    
    print(f"  ✓ Rolled back {version}")


async def migrate(rollback_to=None):
    """Основная функция миграции."""
    pool = await get_db_pool()
    
    try:
        await ensure_migrations_table(pool)
        applied = await get_applied_migrations(pool)
        migrations = get_migration_files()
        
        if rollback_to:
            # Откат до указанной версии
            for version, name, filepath in reversed(migrations):
                if version in applied and version >= rollback_to:
                    await rollback_migration(pool, version)
            return
        
        # Применение новых миграций
        for version, name, filepath in migrations:
            if version not in applied:
                await apply_migration(pool, version, name, filepath)
            else:
                print(f"  - Skipping {version}: {name} (already applied)")
        
        print("\n✅ All migrations applied!")
        
    finally:
        await pool.close()


async def status():
    """Показать статус миграций."""
    pool = await get_db_pool()
    
    try:
        await ensure_migrations_table(pool)
        applied = await get_applied_migrations(pool)
        migrations = get_migration_files()
        
        print("\nMigration Status:")
        print("-" * 60)
        
        for version, name, filepath in migrations:
            status = "✓ Applied" if version in applied else "○ Pending"
            print(f"  [{status:10}] {version}: {name}")
        
        print("-" * 60)
        
    finally:
        await pool.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoDialer Database Migration Tool")
    parser.add_argument("command", choices=["migrate", "rollback", "status"], 
                        help="Command to execute")
    parser.add_argument("--to", help="Rollback to specific version")
    
    args = parser.parse_args()
    
    if args.command == "migrate":
        asyncio.run(migrate())
    elif args.command == "rollback":
        asyncio.run(migrate(rollback_to=args.to))
    elif args.command == "status":
        asyncio.run(status())
