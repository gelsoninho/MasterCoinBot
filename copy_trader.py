import asyncio
import sqlite3
import time
from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger
from binance_ws_client import BinanceWebsocketClient
import os

class CopyTrader:
    """Gestionnaire de copy trading pour Binance Futures"""
    
    def __init__(self, master_api_key: str, master_api_secret: str, 
                 database_path: str, testnet: bool = False):
        self.master_api_key = master_api_key
        self.master_api_secret = master_api_secret
        self.database_path = database_path
        self.testnet = testnet
        
        # Vérifier explicitement si le mode test global est activé
        self.test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
        
        # Initialiser le client WebSocket pour le compte maître
        # Si en mode test, on force le test_mode à True dans le client WebSocket
        self.master_client = BinanceWebsocketClient(
            api_key=master_api_key,
            api_secret=master_api_secret,
            testnet=testnet
        )
        
        # S'assurer que le mode test est correctement propagé
        self.master_client.test_mode = self.test_mode
        
        # Configurer les callbacks du client WebSocket
        self.master_client.on_position_update = self._on_master_position_update
        self.master_client.on_order_update = self._on_master_order_update
        self.master_client.on_error = self._on_master_error
        
        # État de fonctionnement
        self.running = False
        self.follower_clients = {}  # Clients WebSocket pour les comptes d'abonnés
        
        logger.info("CopyTrader initialisé")
    
    def start(self):
        """Démarre le processus de copy trading"""
        if self.running:
            logger.warning("Copy Trader est déjà en cours d'exécution")
            return
            
        self.running = True
        
        # Démarrer le client WebSocket pour le compte maître
        self.master_client.start()
        
        # Charger les utilisateurs actifs et initialiser leurs clients
        self._load_active_users()
        
        logger.info("Copy Trader démarré")
    
    def stop(self):
        """Arrête le processus de copy trading"""
        self.running = False
        
        # Arrêter le client WebSocket du compte maître
        self.master_client.stop()
        
        # Arrêter les clients WebSocket des abonnés
        for client in self.follower_clients.values():
            client.stop()
        
        logger.info("Copy Trader arrêté")
    
    def _load_active_users(self):
        """Charge les utilisateurs actifs depuis la base de données"""
        
        if self.test_mode:
            logger.info("Mode test : pas de chargement d'utilisateurs réels")
            return
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT telegram_id, binance_api_key, binance_api_secret, 
                   risk_factor, max_position_size, take_profit, stop_loss
            FROM users
            WHERE is_active = 1
              AND binance_api_key IS NOT NULL
              AND binance_api_secret IS NOT NULL
        """)
        
        users = cursor.fetchall()
        conn.close()
        
        logger.info(f"Chargement de {len(users)} utilisateurs actifs")
        
        # Initialiser les clients pour chaque utilisateur actif
        for user in users:
            telegram_id, api_key, api_secret, risk_factor, max_position_size, take_profit, stop_loss = user
            self._init_follower_client(telegram_id, api_key, api_secret, risk_factor, max_position_size, take_profit, stop_loss)
    
    def _init_follower_client(self, telegram_id, api_key, api_secret, risk_factor, max_position_size, take_profit, stop_loss):
        """Initialise un client WebSocket pour un abonné"""
        if telegram_id in self.follower_clients:
            logger.warning(f"Le client pour l'utilisateur {telegram_id} existe déjà")
            return
        
        # Nettoyage des clés API pour éviter les erreurs de format
        try:
            # S'assurer que les clés sont en format string et sans espaces
            if api_key is not None:
                api_key = api_key.strip() if isinstance(api_key, str) else api_key.decode().strip()
            if api_secret is not None:
                api_secret = api_secret.strip() if isinstance(api_secret, str) else api_secret.decode().strip()
                
            logger.info(f"Clés API nettoyées pour l'utilisateur {telegram_id}")
        except Exception as e:
            logger.error(f"Erreur lors du nettoyage des clés API pour l'utilisateur {telegram_id}: {e}")
            return
        
        # Vérifier que les clés sont valides
        if not api_key or not api_secret or len(api_key) < 10 or len(api_secret) < 10:
            logger.error(f"Clés API invalides pour l'utilisateur {telegram_id}")
            return
            
        # Initialiser le client WebSocket pour l'abonné
        follower_client = BinanceWebsocketClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=self.testnet
        )
        
        # S'assurer que le mode test est correctement propagé au client follower
        follower_client.test_mode = self.test_mode
        
        # Si en mode test, pas besoin de vérifier les clés API - on utilise un client simulé
        if self.test_mode:
            logger.info(f"Mode test activé pour l'utilisateur {telegram_id} - utilisation d'un client simulé")
        
        self.follower_clients[telegram_id] = {
            "client": follower_client,
            "settings": {
                "risk_factor": risk_factor,
                "max_position_size": max_position_size,
                "take_profit": take_profit,
                "stop_loss": stop_loss
            }
        }
        
        # Démarrer le client WebSocket de l'abonné
        follower_client.start()
        logger.info(f"Client initialisé pour l'utilisateur {telegram_id}")
    
    def _on_master_position_update(self, positions, event_reason):
        """Callback lorsqu'une position est mise à jour sur le compte maître"""
        logger.info(f"Position du compte maître mise à jour: {event_reason}")
        
        for position in positions:
            symbol = position.get('s')  # Symbole
            position_amt = float(position.get('pa', 0))  # Quantité de la position
            entry_price = float(position.get('ep', 0))  # Prix d'entrée
            
            if position_amt == 0:
                logger.info(f"Position fermée sur {symbol}")
                self._copy_position_close(symbol)
            else:
                position_side = "LONG" if position_amt > 0 else "SHORT"
                logger.info(f"Position {position_side} sur {symbol}: {position_amt} @ {entry_price}")
                self._copy_position_open(symbol, position_side, position_amt, entry_price)
    
    def _copy_position_open(self, symbol, position_side, master_amount, entry_price):
        """Copie l'ouverture d'une position du compte maître vers les abonnés"""
        for telegram_id, follower_data in self.follower_clients.items():
            follower_client = follower_data["client"]
            settings = follower_data["settings"]
            
            # Calculer la taille de la position pour l'abonné en fonction de ses paramètres de risque
            risk_factor = settings["risk_factor"]
            max_position_size = settings["max_position_size"]
            take_profit = settings["take_profit"]
            stop_loss = settings["stop_loss"]
            
            # Calcul de base de la taille de la position en fonction du facteur de risque
            follower_amount = master_amount * risk_factor
            
            # Limiter la taille de la position au maximum configuré
            if abs(follower_amount * entry_price) > max_position_size:
                follower_amount = (max_position_size / entry_price) * (1 if follower_amount > 0 else -1)
                
            # Arrondir à la précision requise (cela devrait être ajusté en fonction des symboles)
            follower_amount = round(follower_amount, 3)
            
            # Placer l'ordre pour l'abonné
            side = "BUY" if position_side == "LONG" else "SELL"
            try:
                order = follower_client.place_order(
                    symbol=symbol,
                    side=side,
                    order_type="MARKET",
                    quantity=abs(follower_amount)
                )
                
                # Enregistrer le trade dans la base de données
                self._save_trade(telegram_id, symbol, position_side, entry_price, 
                               abs(follower_amount) * entry_price, "OPEN")
                
                # Si take_profit ou stop_loss sont configurés, placer des ordres respectifs
                if take_profit > 0:
                    tp_price = entry_price * (1 + take_profit/100) if position_side == "LONG" else entry_price * (1 - take_profit/100)
                    follower_client.place_order(
                        symbol=symbol,
                        side="SELL" if position_side == "LONG" else "BUY",
                        order_type="LIMIT",
                        price=tp_price,
                        quantity=abs(follower_amount)
                    )
                    
                if stop_loss > 0:
                    sl_price = entry_price * (1 - stop_loss/100) if position_side == "LONG" else entry_price * (1 + stop_loss/100)
                    follower_client.place_order(
                        symbol=symbol,
                        side="SELL" if position_side == "LONG" else "BUY",
                        order_type="STOP_MARKET",
                        stop_price=sl_price,
                        quantity=abs(follower_amount)
                    )
                    
                logger.info(f"Ordre {side} placé pour l'utilisateur {telegram_id} sur {symbol}: {follower_amount}")
            except Exception as e:
                logger.error(f"Erreur lors du placement d'ordre pour l'utilisateur {telegram_id}: {e}")
    
    def _copy_position_close(self, symbol):
        """Copie la fermeture d'une position du compte maître vers les abonnés"""
        for telegram_id, follower_data in self.follower_clients.items():
            follower_client = follower_data["client"]
            
            try:
                # Récupérer les positions ouvertes de l'abonné
                positions = follower_client.get_positions()
                
                # Trouver la position correspondant au symbole
                for position in positions:
                    if position["symbol"] == symbol:
                        position_side = "LONG" if float(position["positionAmt"]) > 0 else "SHORT"
                        
                        # Fermer la position
                        follower_client.close_position(symbol, position_side)
                        
                        # Annuler tous les ordres en attente sur ce symbole
                        follower_client.client.futures_cancel_all_open_orders(symbol=symbol)
                        
                        # Mettre à jour le trade dans la base de données
                        self._update_trade_status(telegram_id, symbol, "CLOSED")
                        
                        logger.info(f"Position fermée pour l'utilisateur {telegram_id} sur {symbol}")
            except Exception as e:
                logger.error(f"Erreur lors de la fermeture de position pour l'utilisateur {telegram_id}: {e}")
    
    def _on_master_order_update(self, order_data):
        """Callback lorsqu'un ordre est mis à jour sur le compte maître"""
        logger.debug(f"Ordre du compte maître mis à jour: {order_data}")
    
    def _on_master_error(self, error):
        """Callback en cas d'erreur sur le client WebSocket du compte maître"""
        logger.error(f"Erreur du client WebSocket maître: {error}")
    
    def _save_trade(self, telegram_id, symbol, position_side, entry_price, size, status):
        """Enregistre un trade dans la base de données"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO trades (
                    telegram_id, symbol, position_side, entry_price, size, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (telegram_id, symbol, position_side, entry_price, size, status))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Trade enregistré pour l'utilisateur {telegram_id}")
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du trade: {e}")
    
    def _update_trade_status(self, telegram_id, symbol, status, pnl=None, pnl_percent=None):
        """Met à jour le statut d'un trade dans la base de données"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            update_query = """
                UPDATE trades SET
                    status = ?,
                    closed_at = CURRENT_TIMESTAMP
            """
            
            params = [status]
            
            if pnl is not None:
                update_query += ", pnl = ?"
                params.append(pnl)
                
            if pnl_percent is not None:
                update_query += ", pnl_percent = ?"
                params.append(pnl_percent)
                
            update_query += """ WHERE telegram_id = ? AND symbol = ? AND status = 'OPEN'"""
            params.extend([telegram_id, symbol])
            
            cursor.execute(update_query, params)
            
            conn.commit()
            conn.close()
            
            logger.info(f"Statut du trade mis à jour pour l'utilisateur {telegram_id}")
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du statut du trade: {e}")
