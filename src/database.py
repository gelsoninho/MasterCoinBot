import sqlite3
import asyncio
import json
import os
from datetime import datetime
from loguru import logger
from cryptography.fernet import Fernet
from typing import List, Dict

class Database:
    """Database handler for the copy trading bot"""
    
    def __init__(self, db_path=None):
        """Initialize database connection"""
        self.db_path = db_path or os.getenv("DATABASE_URL", "sqlite:///copy_trader.db")
        
        # Extract SQLite path from connection string
        if self.db_path.startswith("sqlite:///"):
            self.db_path = self.db_path[len("sqlite:///"):]
            
        self.conn = None
        self.lock = asyncio.Lock()
        
        # Initialize encryption key for API credentials
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            logger.warning("No encryption key found. Generating a random one.")
            encryption_key = Fernet.generate_key().decode()
            logger.warning(f"Generated encryption key: {encryption_key}")
            logger.warning("Please add this key to your .env file as ENCRYPTION_KEY=")
        
        self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
        
    async def init_db(self):
        """Initialize the database and create tables if they don't exist"""
        async with self.lock:
            self.conn = sqlite3.connect(self.db_path)
            cursor = self.conn.cursor()
            
            # Create users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    binance_api_key TEXT,
                    binance_api_secret TEXT,
                    is_active BOOLEAN DEFAULT 0,
                    is_admin BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create trading_settings table for user configuration
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_settings (
                    telegram_id INTEGER PRIMARY KEY,
                    risk_factor REAL DEFAULT 1.0, -- Multiplier for position sizes
                    max_position_size REAL, -- Maximum position size in USDT
                    enable_tp BOOLEAN DEFAULT 1, -- Enable Take Profit
                    enable_sl BOOLEAN DEFAULT 1, -- Enable Stop Loss
                    custom_tp_percent REAL, -- Custom Take Profit percentage
                    custom_sl_percent REAL, -- Custom Stop Loss percentage
                    leverage_mode TEXT DEFAULT 'copy', -- 'copy', 'fixed', 'custom'
                    custom_leverage INTEGER, -- Custom leverage value if not copying
                    settings_json TEXT, -- Additional settings as JSON
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Create trades table for tracking copied trades
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    symbol TEXT,
                    order_id TEXT,
                    position_side TEXT, -- LONG, SHORT
                    entry_price REAL,
                    size REAL,
                    leverage INTEGER,
                    take_profit REAL,
                    stop_loss REAL,
                    status TEXT, -- OPEN, CLOSED, CANCELED
                    pnl REAL,
                    pnl_percent REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP,
                    master_trade_id INTEGER, -- Reference to the master trader's order ID
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Create master_trades table for tracking main account trades
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS master_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    order_id TEXT,
                    position_side TEXT, -- LONG, SHORT
                    entry_price REAL,
                    size REAL,
                    leverage INTEGER,
                    take_profit REAL,
                    stop_loss REAL,
                    status TEXT, -- OPEN, CLOSED, CANCELED
                    pnl REAL,
                    pnl_percent REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP
                )
            """)
            
            # Create audit_log table for important events
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    event_type TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                )
            """)
            
            # Create notifications table for storing notifications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent_at TIMESTAMP
                )
            """)
            
            self.conn.commit()
            logger.info("Database tables initialized")
    
    async def close(self):
        """Close the database connection"""
        if self.conn:
            self.conn.close()
            
    async def add_user(self, telegram_id, username=None, first_name=None, last_name=None, is_admin=False):
        """Add a new user to the database"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            # Check if user already exists
            cursor.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
            if cursor.fetchone():
                cursor.execute("""
                    UPDATE users SET 
                        username = ?,
                        first_name = ?,
                        last_name = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                """, (username, first_name, last_name, telegram_id))
                logger.info(f"Updated user information for Telegram ID: {telegram_id}")
            else:
                cursor.execute("""
                    INSERT INTO users 
                        (telegram_id, username, first_name, last_name, is_admin)
                    VALUES (?, ?, ?, ?, ?)
                """, (telegram_id, username, first_name, last_name, is_admin))
                
                # Initialize default trading settings
                cursor.execute("""
                    INSERT INTO trading_settings 
                        (telegram_id, risk_factor, max_position_size, custom_tp_percent, custom_sl_percent)
                    VALUES (?, 1.0, 100.0, 5.0, 3.0)
                """, (telegram_id,))
                
                logger.info(f"Added new user with Telegram ID: {telegram_id}")
                
            self.conn.commit()
            
            # Add audit log entry
            await self.add_audit_log(telegram_id, "USER_REGISTRATION", "User registered with the system")
            
            return True
    
    async def get_user(self, telegram_id):
        """Get user information from the database"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = cursor.fetchone()
            if user:
                # Create a dict from the result
                columns = [col[0] for col in cursor.description]
                user_dict = dict(zip(columns, user))
                return user_dict
            return None
    
    async def set_user_api_keys(self, telegram_id, api_key, api_secret):
        """Set user's Binance API keys"""
        try:
            # Encrypt API credentials before storing
            encrypted_key = self.cipher.encrypt(api_key.encode()).decode()
            encrypted_secret = self.cipher.encrypt(api_secret.encode()).decode()
            
            async with self.lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    UPDATE users SET 
                        binance_api_key = ?,
                        binance_api_secret = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE telegram_id = ?
                """, (encrypted_key, encrypted_secret, telegram_id))
                self.conn.commit()
                
            await self.add_audit_log(telegram_id, "API_KEY_UPDATE", "User updated API keys")
            return True
        except Exception as e:
            logger.error(f"Error setting API keys: {e}")
            return False
    
    async def get_user_api_keys(self, telegram_id):
        """Get user's Binance API keys (decrypted)"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT binance_api_key, binance_api_secret FROM users WHERE telegram_id = ?", (telegram_id,))
            result = cursor.fetchone()
            if result and result[0] and result[1]:
                try:
                    api_key = self.cipher.decrypt(result[0].encode()).decode()
                    api_secret = self.cipher.decrypt(result[1].encode()).decode()
                    return api_key, api_secret
                except Exception as e:
                    logger.error(f"Error decrypting API keys: {e}")
            return None, None
    
    async def update_user_status(self, telegram_id, is_active):
        """Update user's active status for copy trading"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE users SET 
                    is_active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ?
            """, (is_active, telegram_id))
            self.conn.commit()
            
            status = "activated" if is_active else "deactivated"
            await self.add_audit_log(telegram_id, "STATUS_CHANGE", f"User {status} copy trading")
            return True
    
    async def get_active_users(self):
        """Get all active users for copy trading"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT telegram_id FROM users WHERE is_active = 1")
            users = cursor.fetchall()
            return [user[0] for user in users]
    
    async def update_trading_settings(self, telegram_id, settings):
        """Update user's trading settings"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            # Convert settings dict to SQL update statement
            update_fields = []
            values = []
            
            for key, value in settings.items():
                update_fields.append(f"{key} = ?")
                values.append(value)
            
            update_fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(telegram_id)  # For WHERE clause
            
            query = f"UPDATE trading_settings SET {', '.join(update_fields)} WHERE telegram_id = ?"
            cursor.execute(query, values)
            self.conn.commit()
            
            await self.add_audit_log(telegram_id, "SETTINGS_UPDATE", "User updated trading settings")
            return True
    
    async def get_trading_settings(self, telegram_id):
        """Get user's trading settings"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM trading_settings WHERE telegram_id = ?", (telegram_id,))
            settings = cursor.fetchone()
            if settings:
                # Create a dict from the result
                columns = [col[0] for col in cursor.description]
                settings_dict = dict(zip(columns, settings))
                
                # Parse JSON settings field if it exists
                if settings_dict.get('settings_json'):
                    try:
                        settings_dict['settings_json'] = json.loads(settings_dict['settings_json'])
                    except json.JSONDecodeError:
                        settings_dict['settings_json'] = {}
                else:
                    settings_dict['settings_json'] = {}
                    
                return settings_dict
            return None
    
    async def add_master_trade(self, trade_data):
        """Add a new trade from the master account"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            columns = ', '.join(trade_data.keys())
            placeholders = ', '.join(['?' for _ in trade_data])
            values = list(trade_data.values())
            
            query = f"INSERT INTO master_trades ({columns}) VALUES ({placeholders})"
            cursor.execute(query, values)
            self.conn.commit()
            
            # Get the ID of the inserted trade
            trade_id = cursor.lastrowid
            logger.info(f"Added master trade with ID: {trade_id}")
            return trade_id
    
    async def update_master_trade(self, trade_id, update_data):
        """Update an existing master trade"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            # Convert update_data dict to SQL update statement
            update_fields = []
            values = []
            
            for key, value in update_data.items():
                update_fields.append(f"{key} = ?")
                values.append(value)
            
            values.append(trade_id)  # For WHERE clause
            
            query = f"UPDATE master_trades SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, values)
            self.conn.commit()
            
            logger.info(f"Updated master trade with ID: {trade_id}")
            return True
    
    async def add_user_trade(self, trade_data):
        """Add a new trade for a follower user"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            columns = ', '.join(trade_data.keys())
            placeholders = ', '.join(['?' for _ in trade_data])
            values = list(trade_data.values())
            
            query = f"INSERT INTO trades ({columns}) VALUES ({placeholders})"
            cursor.execute(query, values)
            self.conn.commit()
            
            # Get the ID of the inserted trade
            trade_id = cursor.lastrowid
            logger.info(f"Added user trade with ID: {trade_id}")
            
            # Add audit log
            await self.add_audit_log(
                trade_data['telegram_id'],
                "TRADE_EXECUTED",
                f"Copied trade for {trade_data['symbol']} {trade_data['position_side']}"
            )
            
            return trade_id
    
    async def update_user_trade(self, trade_id, update_data):
        """Update an existing user trade"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            # Convert update_data dict to SQL update statement
            update_fields = []
            values = []
            
            for key, value in update_data.items():
                update_fields.append(f"{key} = ?")
                values.append(value)
            
            values.append(trade_id)  # For WHERE clause
            
            query = f"UPDATE trades SET {', '.join(update_fields)} WHERE id = ?"
            cursor.execute(query, values)
            self.conn.commit()
            
            logger.info(f"Updated user trade with ID: {trade_id}")
            
            # Add audit log if trade is closed
            if update_data.get('status') == 'CLOSED' and update_data.get('pnl') is not None:
                # Get the telegram_id for this trade
                cursor.execute("SELECT telegram_id, symbol, position_side FROM trades WHERE id = ?", (trade_id,))
                result = cursor.fetchone()
                if result:
                    telegram_id, symbol, position_side = result
                    pnl = update_data.get('pnl', 0)
                    pnl_percent = update_data.get('pnl_percent', 0)
                    
                    pnl_text = f"{pnl:.2f} USDT ({pnl_percent:.2f}%)"
                    result_type = "PROFIT" if pnl > 0 else "LOSS"
                    
                    await self.add_audit_log(
                        telegram_id,
                        f"TRADE_{result_type}",
                        f"Closed {symbol} {position_side} with {pnl_text}"
                    )
            
            return True
    
    async def get_user_open_trades(self, telegram_id):
        """Get all open trades for a user"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE telegram_id = ? AND status = 'OPEN'", (telegram_id,))
            trades = cursor.fetchall()
            
            if trades:
                # Create a list of dicts from the results
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, trade)) for trade in trades]
            return []
    
    async def get_user_trade_history(self, telegram_id, limit=10):
        """Get trade history for a user"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM trades 
                WHERE telegram_id = ? AND status != 'OPEN' 
                ORDER BY closed_at DESC LIMIT ?
            """, (telegram_id, limit))
            trades = cursor.fetchall()
            
            if trades:
                # Create a list of dicts from the results
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, trade)) for trade in trades]
            return []
    
    async def get_master_open_trades(self):
        """Get all open trades for the master account"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM master_trades WHERE status = 'OPEN'")
            trades = cursor.fetchall()
            
            if trades:
                # Create a list of dicts from the results
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, trade)) for trade in trades]
            return []
    
    async def add_audit_log(self, telegram_id, event_type, description):
        """Add an entry to the audit log"""
        async with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO audit_log 
                    (telegram_id, event_type, description)
                VALUES (?, ?, ?)
            """, (telegram_id, event_type, description))
            self.conn.commit()
            return True
    
    async def get_user_statistics(self, telegram_id):
        """Get trading statistics for a user"""
        async with self.lock:
            cursor = self.conn.cursor()
            
            # Total number of trades
            cursor.execute("SELECT COUNT(*) FROM trades WHERE telegram_id = ?", (telegram_id,))
            total_trades = cursor.fetchone()[0]
            
            # Number of winning trades
            cursor.execute("SELECT COUNT(*) FROM trades WHERE telegram_id = ? AND pnl > 0", (telegram_id,))
            winning_trades = cursor.fetchone()[0]
            
            # Win rate
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            # Total profit
            cursor.execute("SELECT SUM(pnl) FROM trades WHERE telegram_id = ?", (telegram_id,))
            total_profit = cursor.fetchone()[0] or 0
            
            # Average profit per trade
            avg_profit = total_profit / total_trades if total_trades > 0 else 0
            
            # Best trade
            cursor.execute("""
                SELECT symbol, position_side, pnl, pnl_percent 
                FROM trades 
                WHERE telegram_id = ? 
                ORDER BY pnl DESC LIMIT 1
            """, (telegram_id,))
            best_trade = cursor.fetchone()
            
            # Worst trade
            cursor.execute("""
                SELECT symbol, position_side, pnl, pnl_percent 
                FROM trades 
                WHERE telegram_id = ? 
                ORDER BY pnl ASC LIMIT 1
            """, (telegram_id,))
            worst_trade = cursor.fetchone()
            
            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'win_rate': win_rate,
                'total_profit': total_profit,
                'avg_profit': avg_profit,
                'best_trade': best_trade,
                'worst_trade': worst_trade
            }
    
    # Notification methods
    async def add_notification(self, telegram_id: int, message: str) -> int:
        """Add a notification to the database
        
        Args:
            telegram_id: Telegram user ID to notify
            message: Notification message
            
        Returns:
            Notification ID
        """
        # Use a synchronous approach but wrap in a thread executor
        def _execute():
            # Create a new connection for this thread
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """INSERT INTO notifications (telegram_id, message, created_at) 
                       VALUES (?, ?, datetime('now')) RETURNING id""", 
                    (telegram_id, message)
                )
                result = cursor.fetchone()
                conn.commit()
                return result[0] if result else None
            finally:
                conn.close()
            
        # Run in thread pool
        return await asyncio.get_event_loop().run_in_executor(None, _execute)
        
    async def get_pending_notifications(self) -> List[Dict]:
        """Get pending notifications to be sent
        
        Returns:
            List of notification dictionaries
        """
        # Use a synchronous approach but wrap in a thread executor
        def _execute():
            # Create a new connection for this thread
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """SELECT id, telegram_id, message, created_at 
                       FROM notifications 
                       WHERE sent_at IS NULL"""
                )
                rows = cursor.fetchall()
                return [
                    {
                        'id': row[0],
                        'telegram_id': row[1],
                        'message': row[2],
                        'created_at': row[3]
                    } for row in rows
                ]
            finally:
                conn.close()
            
        # Run in thread pool
        return await asyncio.get_event_loop().run_in_executor(None, _execute)
        
    async def mark_notification_sent(self, notification_id: int) -> None:
        """Mark a notification as sent
        
        Args:
            notification_id: ID of the notification
        """
        # Use a synchronous approach but wrap in a thread executor
        def _execute():
            # Create a new connection for this thread
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE notifications SET sent_at = datetime('now') WHERE id = ?", 
                    (notification_id,)
                )
                conn.commit()
            finally:
                conn.close()
            
        # Run in thread pool
        await asyncio.get_event_loop().run_in_executor(None, _execute)
