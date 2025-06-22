# app/database.py
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
import aiosqlite

class DatabaseManager:
    def __init__(self, db_path: str = "shopify_prices.db"):
        self.db_path = db_path
        
    async def initialize(self):
        """Ініціалізуємо базу даних з таблицями"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблиця товарів
            await db.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY,
                    shopify_product_id BIGINT UNIQUE NOT NULL,
                    shopify_variant_id BIGINT UNIQUE,
                    title TEXT NOT NULL,
                    sku TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Таблиця змін цін
            await db.execute("""
                CREATE TABLE IF NOT EXISTS price_changes (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    variant_id BIGINT NOT NULL,
                    old_price DECIMAL(10,2),
                    new_price DECIMAL(10,2) NOT NULL,
                    old_compare_at_price DECIMAL(10,2),
                    new_compare_at_price DECIMAL(10,2),
                    change_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    session_id TEXT,
                    notes TEXT,
                    rollback_data JSON,
                    FOREIGN KEY (product_id) REFERENCES products(id)
                )
            """)
            
            # Таблиця сесій для відкату
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rollback_sessions (
                    id INTEGER PRIMARY KEY,
                    session_id TEXT UNIQUE NOT NULL,
                    operation_type TEXT NOT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    status TEXT DEFAULT 'PENDING',
                    total_changes INTEGER DEFAULT 0,
                    description TEXT
                )
            """)
            
            await db.commit()
    
    async def create_rollback_session(self, operation_type: str, description: str) -> str:
        """Створюємо нову сесію для можливості відкату"""
        import uuid
        session_id = str(uuid.uuid4())
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO rollback_sessions (session_id, operation_type, description)
                VALUES (?, ?, ?)
            """, (session_id, operation_type, description))
            await db.commit()
        
        return session_id
    
    async def log_price_change(self, change_data: Dict):
        """Зберігаємо зміну ціни в історію"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO price_changes 
                (product_id, variant_id, old_price, new_price, old_compare_at_price, 
                 new_compare_at_price, change_type, session_id, notes, rollback_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                change_data['product_id'],
                change_data['variant_id'],
                change_data.get('old_price'),
                change_data['new_price'],
                change_data.get('old_compare_at_price'),
                change_data.get('new_compare_at_price'),
                change_data['change_type'],
                change_data.get('session_id'),
                change_data.get('notes'),
                json.dumps(change_data.get('rollback_data', {}))
            ))
            await db.commit()
    
    async def get_recent_price_changes(self, limit: int = 10) -> List[Dict]:
        """Отримуємо останні зміни цін для відображення"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT pc.*, p.title as product_title
                FROM price_changes pc
                JOIN products p ON pc.product_id = p.id
                ORDER BY pc.created_at DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]