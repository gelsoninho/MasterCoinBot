import os
import time
import hmac
import hashlib
import json
import asyncio
from urllib.parse import urlencode
from typing import Dict, List, Optional, Union, Any

import aiohttp
from loguru import logger

class BinanceClient:
    """Client for interacting with Binance Futures API"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        """Initialize Binance Futures client
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            testnet: Whether to use testnet (default: False)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        
        # API URLs
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
        else:
            self.base_url = "https://fapi.binance.com"
        
        # API endpoints
        self.endpoints = {
            # Account endpoints
            "account": "/fapi/v2/account",
            "balance": "/fapi/v2/balance",
            "position_risk": "/fapi/v2/positionRisk",
            "leverage": "/fapi/v1/leverage",
            "margin_type": "/fapi/v1/marginType",
            
            # Market data endpoints
            "exchange_info": "/fapi/v1/exchangeInfo",
            "ticker": "/fapi/v1/ticker/price",
            "ticker_24h": "/fapi/v1/ticker/24hr",
            "klines": "/fapi/v1/klines",
            
            # Order endpoints
            "order": "/fapi/v1/order",
            "open_orders": "/fapi/v1/openOrders",
            "all_orders": "/fapi/v1/allOrders",
            "user_trades": "/fapi/v1/userTrades",
            
            # User stream endpoints
            "user_data_stream": "/fapi/v1/listenKey",
        }
        
        # Initialize session
        self._session = None
        self.listenKey = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
        
    async def close(self):
        """Close the session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _generate_signature(self, data: Dict) -> str:
        """Generate the signature for authenticated requests"""
        query_string = urlencode(data)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
    async def _make_request(self, 
                           method: str, 
                           endpoint: str, 
                           params: Optional[Dict] = None, 
                           data: Optional[Dict] = None, 
                           signed: bool = False) -> Dict:
        """Make an API request to Binance Futures
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            params: Query parameters
            data: Request body for POST requests
            signed: Whether the request needs to be signed
            
        Returns:
            API response as dictionary
        """
        url = self.base_url + endpoint
        session = await self._get_session()
        headers = {"X-MBX-APIKEY": self.api_key}
        
        # Prepare request parameters
        params = params or {}
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        try:
            # Make the request
            if method == "GET":
                response = await session.get(url, params=params, headers=headers)
            elif method == "POST":
                response = await session.post(url, params=params, headers=headers, json=data)
            elif method == "DELETE":
                response = await session.delete(url, params=params, headers=headers)
            elif method == "PUT":
                response = await session.put(url, params=params, headers=headers, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            # Handle response
            response_json = await response.json()
            
            if response.status >= 400:
                logger.error(f"Binance API error: {response.status} - {response_json}")
                raise Exception(f"Binance API error: {response.status} - {response_json}")
                
            return response_json
            
        except aiohttp.ClientError as e:
            logger.error(f"Request error: {e}")
            raise
    
    # Account endpoints
    async def get_account(self) -> Dict:
        """Get account information"""
        return await self._make_request("GET", self.endpoints["account"], signed=True)
    
    async def get_balance(self) -> List[Dict]:
        """Get account balance"""
        return await self._make_request("GET", self.endpoints["balance"], signed=True)
        
    async def get_positions(self) -> List[Dict]:
        """Get current positions"""
        return await self._make_request("GET", self.endpoints["position_risk"], signed=True)
    
    async def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """Set leverage for a symbol
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            leverage: Leverage level (1-125)
            
        Returns:
            Response from the API
        """
        params = {
            "symbol": symbol,
            "leverage": leverage
        }
        return await self._make_request("POST", self.endpoints["leverage"], params=params, signed=True)
    
    async def set_margin_type(self, symbol: str, margin_type: str) -> Dict:
        """Set margin type for a symbol
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            margin_type: Margin type ('ISOLATED', 'CROSSED')
            
        Returns:
            Response from the API
        """
        params = {
            "symbol": symbol,
            "marginType": margin_type
        }
        return await self._make_request("POST", self.endpoints["margin_type"], params=params, signed=True)
    
    # Market data endpoints
    async def get_exchange_info(self) -> Dict:
        """Get exchange information"""
        return await self._make_request("GET", self.endpoints["exchange_info"])
    
    async def get_ticker_price(self, symbol: Optional[str] = None) -> Union[Dict, List[Dict]]:
        """Get current price for a symbol or all symbols
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT), or None for all symbols
            
        Returns:
            Current price(s)
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._make_request("GET", self.endpoints["ticker"], params=params)
    
    async def get_ticker_24h(self, symbol: Optional[str] = None) -> Union[Dict, List[Dict]]:
        """Get 24-hour statistics for a symbol or all symbols
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT), or None for all symbols
            
        Returns:
            24-hour statistics
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._make_request("GET", self.endpoints["ticker_24h"], params=params)
    
    # Order endpoints
    async def create_order(self, 
                         symbol: str, 
                         side: str, 
                         order_type: str, 
                         quantity: Optional[float] = None,
                         price: Optional[float] = None,
                         time_in_force: Optional[str] = "GTC",
                         stop_price: Optional[float] = None,
                         close_position: Optional[bool] = None,
                         reduce_only: Optional[bool] = None,
                         **kwargs) -> Dict:
        """Create a new order
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            side: Order side (BUY, SELL)
            order_type: Order type (LIMIT, MARKET, STOP, TAKE_PROFIT, etc.)
            quantity: Order quantity
            price: Order price, required for LIMIT orders
            time_in_force: Time in force, default GTC (Good Till Cancelled)
            stop_price: Stop price, required for STOP orders
            close_position: Whether to close the position, default False
            reduce_only: Whether the order is reduce-only, default False
            **kwargs: Additional parameters
            
        Returns:
            Order details
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        
        if quantity is not None:
            params["quantity"] = quantity
            
        if price is not None:
            params["price"] = price
            
        if time_in_force is not None:
            params["timeInForce"] = time_in_force
            
        if stop_price is not None:
            params["stopPrice"] = stop_price
            
        if close_position is not None:
            params["closePosition"] = "true" if close_position else "false"
            
        if reduce_only is not None:
            params["reduceOnly"] = "true" if reduce_only else "false"
            
        # Add any additional parameters
        params.update(kwargs)
        
        return await self._make_request("POST", self.endpoints["order"], params=params, signed=True)
    
    async def cancel_order(self, symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None) -> Dict:
        """Cancel an existing order
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            order_id: Order ID
            orig_client_order_id: Original client order ID
            
        Returns:
            Cancellation result
        """
        params = {"symbol": symbol}
        
        if order_id:
            params["orderId"] = order_id
        elif orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        else:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
            
        return await self._make_request("DELETE", self.endpoints["order"], params=params, signed=True)
    
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Get all open orders for a symbol or all symbols
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT), or None for all symbols
            
        Returns:
            List of open orders
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._make_request("GET", self.endpoints["open_orders"], params=params, signed=True)
    
    async def get_order(self, symbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None) -> Dict:
        """Get order details
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            order_id: Order ID
            orig_client_order_id: Original client order ID
            
        Returns:
            Order details
        """
        params = {"symbol": symbol}
        
        if order_id:
            params["orderId"] = order_id
        elif orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        else:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
            
        return await self._make_request("GET", self.endpoints["order"], params=params, signed=True)
    
    async def get_user_trades(self, symbol: str, limit: Optional[int] = 500) -> List[Dict]:
        """Get user's trade history for a symbol
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            limit: Maximum number of trades to return (default 500, max 1000)
            
        Returns:
            List of trades
        """
        params = {
            "symbol": symbol,
            "limit": limit
        }
        return await self._make_request("GET", self.endpoints["user_trades"], params=params, signed=True)
    
    # User data stream endpoints
    async def start_user_data_stream(self) -> str:
        """Start a new user data stream and return the listen key"""
        response = await self._make_request("POST", self.endpoints["user_data_stream"])
        self.listenKey = response['listenKey']
        return self.listenKey
    
    async def keep_alive_user_data_stream(self, listen_key: Optional[str] = None) -> Dict:
        """Keep a user data stream alive
        
        Args:
            listen_key: Listen key to keep alive, or None to use the current one
            
        Returns:
            API response
        """
        params = {"listenKey": listen_key or self.listenKey}
        return await self._make_request("PUT", self.endpoints["user_data_stream"], params=params)
    
    async def close_user_data_stream(self, listen_key: Optional[str] = None) -> Dict:
        """Close a user data stream
        
        Args:
            listen_key: Listen key to close, or None to use the current one
            
        Returns:
            API response
        """
        params = {"listenKey": listen_key or self.listenKey}
        return await self._make_request("DELETE", self.endpoints["user_data_stream"], params=params)
    
    # Utility methods
    async def calculate_order_quantity(self, symbol: str, usdt_amount: float, position_side: str = "LONG") -> float:
        """Calculate the order quantity based on USDT amount
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            usdt_amount: Amount in USDT to use for the order
            position_side: Position side (LONG or SHORT)
            
        Returns:
            Order quantity
        """
        try:
            # Get current price
            ticker = await self.get_ticker_price(symbol)
            current_price = float(ticker["price"] if isinstance(ticker, dict) else ticker[0]["price"])
            
            # Calculate quantity (USDT amount / current price)
            quantity = usdt_amount / current_price
            
            # Get symbol info to format the quantity according to the symbol's quantity precision
            exchange_info = await self.get_exchange_info()
            symbol_info = next((s for s in exchange_info["symbols"] if s["symbol"] == symbol), None)
            
            if symbol_info:
                quantity_precision = symbol_info.get("quantityPrecision", 8)
                quantity = round(quantity, quantity_precision)
            else:
                # Default to 8 decimal places if symbol info not found
                quantity = round(quantity, 8)
                
            return quantity
            
        except Exception as e:
            logger.error(f"Error calculating order quantity: {e}")
            raise
