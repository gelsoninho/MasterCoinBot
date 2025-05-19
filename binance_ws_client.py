import asyncio
import json
import time
import hmac
import hashlib
import websocket
import threading
import os
import requests  # Ajout de l'import manquant pour les appels HTTP
from typing import Dict, List, Callable, Optional
from datetime import datetime
from loguru import logger
from binance.client import Client
from binance.enums import *

class BinanceWebsocketClient:
    """Client WebSocket pour surveiller les positions et les trades sur Binance Futures"""
    
    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
        
        # URL WebSocket - Mise à jour selon la documentation officielle (2025)
        if testnet:
            # URLs pour testnet
            self.ws_url = "wss://testnet.binance.vision/ws-api/v3"  # WebSocket API URL
            self.base_url = "https://testnet.binance.vision"
            self.futures_url = "https://testnet.binance.vision/fapi"
        else:
            # URLs pour production (selon docs: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-api-general-info)
            self.ws_url = "wss://ws-fapi.binance.com/ws-fapi/v1"  # Nouvelle URL WebSocket API
            self.base_url = "https://fapi.binance.com"
            self.futures_url = "https://fapi.binance.com"
            
        # Client REST API
        if not self.test_mode:
            self.client = Client(api_key, api_secret, testnet=testnet)
            
            # Configuration explicite des URLs pour éviter les erreurs "API-key format invalid"
            if testnet:
                # URLs pour le testnet selon la documentation officielle
                self.client.API_URL = 'https://testnet.binance.vision/api'
                self.client.FUTURES_URL = 'https://testnet.binancefuture.com'
            else:
                # URLs pour la production selon la documentation officielle
                self.client.API_URL = 'https://api.binance.com/api'
                self.client.FUTURES_URL = 'https://fapi.binance.com'
            
            logger.info(f"Client Binance WebSocket configuré avec URL Futures: {self.client.FUTURES_URL}")
        else:
            # En mode test, pas besoin d'initialiser le client
            self.client = None
        
        # WebSocket
        self.ws = None
        self.keep_running = False
        self.ws_thread = None
        
        # Callbacks
        self.on_position_update = None
        self.on_order_update = None
        self.on_balance_update = None
        self.on_error = None
        
        logger.info("BinanceWebsocketClient initialisé")
    
    def start(self):
        """Démarre la connexion WebSocket"""
        if self.ws_thread and self.ws_thread.is_alive():
            logger.warning("WebSocket déjà en cours d'exécution")
            return
            
        # Vérification globale du mode test - en priorité absolue
        self.test_mode = self.test_mode or os.getenv("TEST_MODE", "False").lower() == "true"
        if self.test_mode:
            logger.info("Mode test activé - utilisation d'une connexion WebSocket simulée")
        
        self.keep_running = True
        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()
        logger.info("WebSocket démarré")
    
    def stop(self):
        """Arrête la connexion WebSocket"""
        self.keep_running = False
        if self.ws:
            self.ws.close()
        logger.info("WebSocket arrêté")
    
    def _run_websocket(self):
        """Gestion de la boucle WebSocket"""
        # Double vérification du mode test - aucune tentative de connexion à Binance en mode test
        if self.test_mode or os.getenv("TEST_MODE", "False").lower() == "true":
            logger.info("Mode test : WebSocket simulé en cours d'exécution")
            # Simuler les callbacks de WebSocket pour que le bot fonctionne comme prévu
            if self.on_position_update:
                logger.info("Simulation de mises à jour de position en mode test")
                # Simulation de données seulement pour le log
            
            # Simuler une connexion active sans jamais tenter de se connecter à Binance
            while self.keep_running:
                time.sleep(5)
            return
        
        # Code exécuté uniquement en mode non-test
        logger.info("Mode normal : Tentative de connexion réelle à Binance")
            
        while self.keep_running:
            try:
                self._connect_and_subscribe()
            except Exception as e:
                logger.error(f"Erreur WebSocket: {e}")
                if self.on_error:
                    self.on_error(str(e))
            
            if self.keep_running:
                logger.info("Reconnexion au WebSocket dans 5 secondes...")
                time.sleep(5)
    
    def _connect_and_subscribe(self):
        """Établit la connexion WebSocket et s'abonne aux flux selon le nouveau format API WebSocket"""
        # Ne pas essayer de se connecter en mode test
        if self.test_mode:
            logger.info("Mode test: connexion WebSocket simulée")
            time.sleep(5)
            return
        
        # Log pour indiquer l'utilisation du nouveau format d'API WebSocket    
        logger.info(f"Tentative de connexion au WebSocket API ({self.ws_url})")
        
        # La nouvelle API WebSocket Binance utilise un processus d'authentification différent
        # L'authentification se fait après établissement de la connexion, pas dans l'en-tête
        
        # Configurer les événements WebSocket avec le nouveau format d'API
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_ws_error,
            on_close=self._on_close
            # Plus besoin d'en-tête d'authentification selon la nouvelle documentation Binance
            # L'authentification se fait via une requête JSON après connexion
        )
        
        # Si besoin de headers spécifiques (autre que l'authentification)
        # self.ws.header = [
        #    "Content-Type: application/json"
        # ]
        
        # Démarrer la connexion WebSocket
        self.ws.run_forever()
    
    def _on_open(self, ws):
        """Appelé quand le WebSocket est ouvert"""
        logger.info("WebSocket connecté")
        
        # Vérification stricte du mode test - éviter toute connexion à Binance en mode test
        if self.test_mode or os.getenv("TEST_MODE", "False").lower() == "true":
            logger.info("Mode test activé: aucune connexion à Binance ne sera tentée")
            return
        
        # S'abonner au flux utilisateur (positions, ordres, etc.) uniquement en mode normal
        try:
            listen_key = self._get_listen_key()
            if listen_key:
                self._subscribe_user_data(listen_key)
        except Exception as e:
            logger.error(f"Erreur lors de l'obtention/abonnement à la clé d'écoute: {e}")
            # Ne pas propager l'erreur pour éviter de couper la connexion WebSocket
    
    def _get_listen_key(self) -> Optional[str]:
        """Obtient une clé d'écoute pour le flux utilisateur en utilisant le nouveau format API WebSocket"""
        # TRIPLE VÉRIFICATION du mode test pour éviter toute connexion à Binance
        if self.test_mode or os.getenv("TEST_MODE", "False").lower() == "true":
            logger.info("Mode test : utilisation d'une clé d'écoute fictive")
            return "test_listen_key_123456789"
        
        # Si nous sommes ici, c'est que nous sommes certains de ne PAS être en mode test
        try:
            # Vérification des clés API avant de faire l'appel
            if not self.api_key or not self.api_secret:
                logger.error("Clés API manquantes pour obtenir la clé d'écoute")
                return None
            
            # Utiliser directement l'API REST pour obtenir une clé d'écoute (plus fiable que le WebSocket)
            # Méthode recommandée dans la documentation Binance
            timestamp = int(time.time() * 1000)
            query_string = f"timestamp={timestamp}"
            
            # Calculer la signature pour l'authentification
            signature = hmac.new(
                self.api_secret.encode() if isinstance(self.api_secret, str) else self.api_secret,
                query_string.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Construire l'URL avec la signature
            url = f"{self.futures_url}/v1/listenKey?{query_string}&signature={signature}"
            
            # Effectuer la requête HTTP pour obtenir la clé d'écoute
            headers = {"X-MBX-APIKEY": self.api_key}
            response = requests.post(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                listen_key = data.get('listenKey')
                if listen_key:
                    logger.info(f"Clé d'écoute obtenue avec succès: {listen_key[:8]}...")
                    return listen_key
                else:
                    logger.error(f"Réponse Binance sans listenKey: {data}")
            else:
                logger.error(f"Erreur API Binance ({response.status_code}): {response.text}")
            
            return None
        except Exception as e:
            logger.error(f"Erreur lors de l'obtention de la clé d'écoute: {e}")
            return None
    
    def _subscribe_user_data(self, listen_key: str):
        """S'abonne au flux de données utilisateur selon le nouveau format de l'API WebSocket Binance"""
        # Format de requête WebSocket API selon la documentation Binance 2025
        # Doc: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-api-general-info
        
        # Générer un ID unique pour la requête
        request_id = str(int(time.time() * 1000))
        
        # Créer une signature pour l'authentification
        timestamp = int(time.time() * 1000)
        signature_payload = f"listenKey={listen_key}&timestamp={timestamp}"
        
        # Calculer la signature HMAC-SHA256
        signature = hmac.new(
            self.api_secret.encode() if isinstance(self.api_secret, str) else self.api_secret,
            signature_payload.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Construction de la requête au format WebSocket API
        subscribe_request = {
            "id": request_id,
            "method": "userDataStream.start",
            "params": {
                "apiKey": self.api_key,
                "signature": signature,
                "timestamp": timestamp,
                "listenKey": listen_key
            }
        }
        
        self.ws.send(json.dumps(subscribe_request))
        logger.info(f"Abonnement au flux utilisateur avec le nouveau format WebSocket API (id: {request_id})")

    
    def _on_message(self, ws, message):
        """Appelé quand un message est reçu du WebSocket"""
        try:
            data = json.loads(message)
            event_type = data.get('e')
            
            if event_type == 'ACCOUNT_UPDATE':
                self._handle_account_update(data)
            elif event_type == 'ORDER_TRADE_UPDATE':
                self._handle_order_update(data)
            elif event_type == 'MARGIN_CALL':
                self._handle_margin_call(data)
            elif event_type == 'ACCOUNT_CONFIG_UPDATE':
                self._handle_config_update(data)
            else:
                logger.debug(f"Message non traité: {message[:100]}...")
        except json.JSONDecodeError:
            logger.error(f"Message JSON invalide: {message[:100]}...")
        except Exception as e:
            logger.error(f"Erreur lors du traitement du message: {e}")
    
    def _handle_account_update(self, data):
        """Traite les mises à jour de compte (positions, soldes)"""
        update_data = data.get('a', {})
        event_reason = update_data.get('m')  # DEPOSIT, WITHDRAW, ORDER, FUNDING_FEE, etc.
        
        # Mise à jour des soldes
        balances = update_data.get('B', [])
        if balances and self.on_balance_update:
            self.on_balance_update(balances, event_reason)
            
        # Mise à jour des positions
        positions = update_data.get('P', [])
        if positions and self.on_position_update:
            self.on_position_update(positions, event_reason)
    
    def _handle_order_update(self, data):
        """Traite les mises à jour d'ordres"""
        order_data = data.get('o', {})
        if self.on_order_update:
            self.on_order_update(order_data)
    
    def _handle_margin_call(self, data):
        """Traite les appels de marge"""
        logger.warning(f"Appel de marge: {data}")
    
    def _handle_config_update(self, data):
        """Traite les mises à jour de configuration du compte"""
        logger.info(f"Mise à jour de configuration: {data}")
    
    def _on_ws_error(self, ws, error):
        """Appelé quand une erreur se produit dans le WebSocket"""
        logger.error(f"Erreur WebSocket: {error}")
        if self.on_error:
            self.on_error(str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Appelé quand le WebSocket est fermé"""
        logger.info(f"WebSocket fermé: {close_status_code} {close_msg}")
    
    def get_positions(self) -> List[Dict]:
        """Récupère les positions ouvertes"""
        try:
            positions = self.client.futures_position_information()
            return [p for p in positions if float(p['positionAmt']) != 0]
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des positions: {e}")
            return []
    
    def get_open_orders(self) -> List[Dict]:
        """Récupère les ordres ouverts"""
        try:
            return self.client.futures_get_open_orders()
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des ordres ouverts: {e}")
            return []
    
    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, 
                    price: Optional[float] = None, stop_price: Optional[float] = None,
                    time_in_force: str = TIME_IN_FORCE_GTC) -> Dict:
        """Place un ordre sur Binance Futures"""
        try:
            params = {
                'symbol': symbol,
                'side': side,
                'type': order_type,
                'quantity': quantity,
                'timeInForce': time_in_force,
            }
            
            if price is not None:
                params['price'] = price
                
            if stop_price is not None:
                params['stopPrice'] = stop_price
                
            return self.client.futures_create_order(**params)
        except Exception as e:
            logger.error(f"Erreur lors du placement d'un ordre: {e}")
            raise

    def close_position(self, symbol: str, position_side: str) -> Dict:
        """Ferme une position ouverte"""
        try:
            # Récupérer la position actuelle
            positions = self.get_positions()
            position = next((p for p in positions if p['symbol'] == symbol and p['positionSide'] == position_side), None)
            
            if not position:
                logger.warning(f"Aucune position trouvée pour {symbol} {position_side}")
                return {"status": "error", "message": "Position not found"}
            
            # Calculer la quantité pour fermer la position
            amount = float(position['positionAmt'])
            if amount == 0:
                logger.warning(f"Position vide pour {symbol} {position_side}")
                return {"status": "error", "message": "Empty position"}
            
            # Déterminer le côté pour fermer la position
            close_side = SIDE_SELL if amount > 0 else SIDE_BUY
            close_qty = abs(amount)
            
            # Placer un ordre de marché pour fermer la position
            return self.place_order(
                symbol=symbol,
                side=close_side,
                order_type=ORDER_TYPE_MARKET,
                quantity=close_qty
            )
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture d'une position: {e}")
            raise
