import asyncio
import json
from typing import Dict, List, Optional, Union, Any
from datetime import datetime

from loguru import logger

from src.binance_client import BinanceClient
from src.database import Database

class CopyTrader:
    """Core functionality for copy trading Binance Futures"""
    
    def __init__(self, master_client: BinanceClient, db: Database):
        """Initialize copy trader
        
        Args:
            master_client: Binance client for the master account
            db: Database instance
        """
        self.master_client = master_client
        self.db = db
        self.user_clients = {}  # Mapping of telegram_id -> BinanceClient
        self.initialized = False
        self.running = False
        self.websocket_task = None
        
    async def initialize(self):
        """Initialize the copy trader system"""
        if self.initialized:
            return
            
        # Load active users and create clients for them
        active_users = await self.db.get_active_users()
        for telegram_id in active_users:
            await self.add_user_client(telegram_id)
            
        self.initialized = True
        logger.info("Copy trader initialized")
        
    async def start(self):
        """Start the copy trading system"""
        if not self.initialized:
            await self.initialize()
            
        if self.running:
            logger.warning("Copy trader is already running")
            return
            
        # Start user data stream
        self.running = True
        self.websocket_task = asyncio.create_task(self.listen_for_master_trades())
        logger.info("Copy trading system started")
        
    async def stop(self):
        """Stop the copy trading system"""
        if not self.running:
            logger.warning("Copy trader is not running")
            return
            
        self.running = False
        if self.websocket_task:
            self.websocket_task.cancel()
            try:
                await self.websocket_task
            except asyncio.CancelledError:
                pass
            self.websocket_task = None
            
        logger.info("Copy trading system stopped")
        
    async def add_user_client(self, telegram_id: int) -> bool:
        """Add a new user client
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            True if successful, False otherwise
        """
        # Check if user is already added
        if telegram_id in self.user_clients:
            return True
            
        # Get user's API keys from database
        api_key, api_secret = await self.db.get_user_api_keys(telegram_id)
        if not api_key or not api_secret:
            logger.warning(f"No API keys found for user {telegram_id}")
            return False
            
        # Create Binance client for user
        try:
            client = BinanceClient(
                api_key=api_key,
                api_secret=api_secret,
                testnet=self.master_client.testnet
            )
            
            # Test connection
            await client.get_account()
            
            self.user_clients[telegram_id] = client
            logger.info(f"Added client for user {telegram_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding client for user {telegram_id}: {e}")
            return False
    
    async def remove_user_client(self, telegram_id: int) -> bool:
        """Remove a user client
        
        Args:
            telegram_id: Telegram user ID
            
        Returns:
            True if successful, False if user not found
        """
        if telegram_id not in self.user_clients:
            logger.warning(f"User {telegram_id} not found")
            return False
            
        # Close the client session
        await self.user_clients[telegram_id].close()
        
        # Remove from user clients
        del self.user_clients[telegram_id]
        logger.info(f"Removed client for user {telegram_id}")
        return True
    
    async def listen_for_master_trades(self):
        """Listen for trades from the master account using user data stream"""
        try:
            # Start user data stream
            listen_key = await self.master_client.start_user_data_stream()
            logger.info(f"Started user data stream with listen key: {listen_key}")
            
            # WebSocket URL for user data stream
            ws_url = f"wss://{'testnet.' if self.master_client.testnet else ''}fstream.binance.com/ws/{listen_key}"
            
            # Keep track of keep-alive time
            last_keepalive = datetime.now()
            
            # Connect to WebSocket
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url) as websocket:
                    logger.info("Connected to Binance WebSocket")
                    
                    while self.running:
                        # Keep listen key alive every 30 minutes
                        now = datetime.now()
                        if (now - last_keepalive).total_seconds() > 1800:  # 30 minutes
                            await self.master_client.keep_alive_user_data_stream()
                            last_keepalive = now
                            logger.debug("Kept user data stream alive")
                        
                        # Wait for message with 30-second timeout
                        try:
                            message = await asyncio.wait_for(websocket.receive_json(), timeout=30)
                            await self.process_master_account_message(message)
                        except asyncio.TimeoutError:
                            continue
                        except Exception as e:
                            logger.error(f"Error receiving WebSocket message: {e}")
                            # Try to reconnect after a delay
                            await asyncio.sleep(5)
                            break
                            
            # If the loop exits normally, try to reconnect
            if self.running:
                logger.info("WebSocket connection closed, reconnecting...")
                await asyncio.sleep(5)  # Wait before reconnecting
                asyncio.create_task(self.listen_for_master_trades())
                
        except Exception as e:
            logger.exception(f"Error in WebSocket connection: {e}")
            if self.running:
                logger.info("Attempting to reconnect in 10 seconds...")
                await asyncio.sleep(10)  # Wait longer before reconnecting after an error
                asyncio.create_task(self.listen_for_master_trades())
                
    async def process_master_account_message(self, message: Dict):
        """Process a message from the master account WebSocket
        
        Args:
            message: WebSocket message
        """
        try:
            event_type = message.get('e')
            
            if event_type == 'ORDER_TRADE_UPDATE':
                # Extract order information
                order_data = message.get('o', {})
                symbol = order_data.get('s')  # Symbol
                side = order_data.get('S')  # Side (BUY/SELL)
                order_type = order_data.get('o')  # Order type
                order_status = order_data.get('X')  # Order status
                execution_type = order_data.get('x')  # Execution type
                position_side = order_data.get('ps', 'BOTH')  # Position side
                order_id = order_data.get('i')  # Order ID
                client_order_id = order_data.get('c')  # Client order ID
                order_price = float(order_data.get('p', 0))  # Order price
                order_qty = float(order_data.get('q', 0))  # Order quantity
                executed_qty = float(order_data.get('z', 0))  # Executed quantity
                avg_price = float(order_data.get('ap', 0))  # Average fill price
                
                # Log the order update
                logger.info(f"Order update: {symbol} {side} {order_type} {order_status} {execution_type}")
                
                # Handle new orders
                if execution_type == 'NEW' and order_status == 'NEW':
                    await self.handle_new_master_order(symbol, side, order_type, order_qty, order_price, position_side, order_id)
                
                # Handle filled orders
                elif execution_type == 'TRADE' and order_status == 'FILLED':
                    await self.handle_filled_master_order(symbol, side, order_id, avg_price, executed_qty)
                
                # Handle canceled orders
                elif execution_type == 'CANCELED' and order_status == 'CANCELED':
                    await self.handle_canceled_master_order(symbol, order_id)
                    
            elif event_type == 'ACCOUNT_UPDATE':
                # Handle account updates (balance changes, position changes)
                account_data = message.get('a', {})
                positions = account_data.get('P', [])
                
                for position in positions:
                    symbol = position.get('s')  # Symbol
                    position_amount = float(position.get('pa', 0))  # Position amount
                    entry_price = float(position.get('ep', 0))  # Entry price
                    unrealized_pnl = float(position.get('up', 0))  # Unrealized PNL
                    position_side = position.get('ps', 'BOTH')  # Position side
                    
                    # Log position update
                    logger.info(f"Position update: {symbol} {position_side} {position_amount} @ {entry_price} (PNL: {unrealized_pnl})")
                    
        except Exception as e:
            logger.exception(f"Error processing master account message: {e}")
    
    async def handle_new_master_order(self, 
                                   symbol: str, 
                                   side: str, 
                                   order_type: str, 
                                   quantity: float, 
                                   price: float, 
                                   position_side: str, 
                                   order_id: int):
        """Handle a new order from the master account
        
        Args:
            symbol: Trading pair symbol
            side: Order side (BUY/SELL)
            order_type: Order type
            quantity: Order quantity
            price: Order price
            position_side: Position side (LONG/SHORT/BOTH)
            order_id: Order ID
        """
        try:
            # Store master trade in database
            trade_data = {
                'symbol': symbol,
                'order_id': str(order_id),
                'position_side': 'LONG' if (side == 'BUY' and position_side in ['LONG', 'BOTH']) else 'SHORT',
                'entry_price': price if price > 0 else None,
                'size': quantity,
                'status': 'OPEN'
            }
            
            # Get leverage from the position
            positions = await self.master_client.get_positions()
            position = next((p for p in positions if p['symbol'] == symbol), None)
            if position:
                trade_data['leverage'] = int(position['leverage'])
            
            # Save to database
            master_trade_id = await self.db.add_master_trade(trade_data)
            
            # Copy trade to all active users
            await self.copy_trade_to_users(master_trade_id, trade_data)
            
        except Exception as e:
            logger.exception(f"Error handling new master order: {e}")
    
    async def handle_filled_master_order(self, 
                                      symbol: str, 
                                      side: str, 
                                      order_id: int, 
                                      avg_price: float, 
                                      executed_qty: float):
        """Handle a filled order from the master account
        
        Args:
            symbol: Trading pair symbol
            side: Order side (BUY/SELL)
            order_id: Order ID
            avg_price: Average fill price
            executed_qty: Executed quantity
        """
        try:
            # Update master trade in database
            # For filled orders, we need to check if it's closing a position
            open_trades = await self.db.get_master_open_trades()
            
            # Find the trade being closed (if this is a closing order)
            for trade in open_trades:
                if trade['symbol'] == symbol:
                    position_side = trade['position_side']
                    is_closing_order = (position_side == 'LONG' and side == 'SELL') or (position_side == 'SHORT' and side == 'BUY')
                    
                    if is_closing_order:
                        # This is a closing order, update the trade as closed
                        update_data = {
                            'status': 'CLOSED',
                            'closed_at': datetime.now().isoformat()
                        }
                        
                        # Calculate PNL
                        entry_price = trade['entry_price']
                        if position_side == 'LONG':
                            pnl = executed_qty * (avg_price - entry_price)
                            pnl_percent = ((avg_price / entry_price) - 1) * 100
                        else:  # SHORT
                            pnl = executed_qty * (entry_price - avg_price)
                            pnl_percent = ((entry_price / avg_price) - 1) * 100
                            
                        update_data['pnl'] = pnl
                        update_data['pnl_percent'] = pnl_percent
                        
                        await self.db.update_master_trade(trade['id'], update_data)
                        logger.info(f"Closed master trade {trade['id']} with PNL: {pnl:.2f} USDT ({pnl_percent:.2f}%)")
                        
                        # Close the corresponding user trades
                        await self.close_user_trades(trade['id'], avg_price)
                        
        except Exception as e:
            logger.exception(f"Error handling filled master order: {e}")
    
    async def handle_canceled_master_order(self, symbol: str, order_id: int):
        """Handle a canceled order from the master account
        
        Args:
            symbol: Trading pair symbol
            order_id: Order ID
        """
        try:
            # Find the trade in the database
            # Note: Canceled orders might be limit orders that were never filled,
            # so we might not have a trade for them in the database
            pass
            
        except Exception as e:
            logger.exception(f"Error handling canceled master order: {e}")
    
