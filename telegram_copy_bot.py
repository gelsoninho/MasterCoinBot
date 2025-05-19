# Support pour les clés API Binance
import time
import json
import os
import sqlite3
import sys
import hmac
import hashlib
import base64
import asyncio
import requests
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Charger les variables d'environnement avant toute autre initialisation
load_dotenv()

# Détection du mode (test ou production)
is_test_mode = os.getenv("TEST_MODE", "False").lower() == "true"

# Afficher clairement le mode actuel
if is_test_mode:
    print("⚠️ Mode TEST activé - Aucune connexion à Binance ne sera tentée")
    print("   Pour activer le mode production, modifiez TEST_MODE=False dans le fichier .env")
else:
    print("💰 Mode PRODUCTION activé - Connexion réelle à Binance")


from loguru import logger
from cryptography.fernet import Fernet

# Charger les variables d'environnement
load_dotenv()

# Récupérer les variables d'environnement
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", 0))
DATABASE_PATH = os.getenv("DATABASE_URL", "sqlite:///copy_trader.db")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

# Extraire le chemin SQLite si nécessaire
if DATABASE_PATH.startswith("sqlite:///"):
    DATABASE_PATH = DATABASE_PATH[len("sqlite:///"):]

# Dictionnaire pour stocker l'état des utilisateurs (pour les commandes interactives)
user_states = {}

# Initialisation du chiffrement
try:
    # Si une clé est fournie, l'utiliser ; sinon, en générer une nouvelle
    if ENCRYPTION_KEY:
        fernet = Fernet(ENCRYPTION_KEY.encode())
    else:
        # Générer une clé (seulement pour le développement, pour la production, utilisez une clé fixe)
        key = Fernet.generate_key()
        fernet = Fernet(key)
        logger.warning(f"Aucune clé de chiffrement fournie, utilisation d'une clé temporaire : {key.decode()}")
    logger.info("Chiffrement initialisé avec succès")
except Exception as e:
    logger.error(f"Erreur lors de l'initialisation du chiffrement : {e}")
    fernet = None

# Variables globales
copy_trader = None

# Cache pour les données de marché
market_data_cache = {}
market_data_timestamp = {}
CACHE_DURATION = 300  # 5 minutes en secondes

# Client Binance
async def get_binance_client(api_key=None, api_secret=None):
    """Initialises et retourne un client Binance Futures"""
    # Si en mode test, retourner directement un client mocké
    if os.getenv("TEST_MODE", "False").lower() == "true":
        logger.info("Mode test activé, utilisation d'un client Binance mocké")
        return MockBinanceClient()
    
    from binance.client import Client
    
    # Si aucune clé fournie, utiliser les clés master
    if not api_key or not api_secret:
        api_key = os.getenv("MASTER_BINANCE_API_KEY")
        api_secret = os.getenv("MASTER_BINANCE_API_SECRET")
    
    # Vérifier si on utilise le testnet
    testnet = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
    
    # Créer le client avec configuration explicite des URLs
    client = Client(api_key, api_secret, testnet=testnet)
    
    # Configuration explicite des URLs pour éviter les erreurs "API-key format invalid"
    if testnet:
        # URLs pour le testnet selon la documentation officielle
        client.API_URL = 'https://testnet.binance.vision/api'
        client.FUTURES_URL = 'https://testnet.binancefuture.com'
    else:
        # URLs pour la production selon la documentation officielle
        client.API_URL = 'https://api.binance.com/api'
        client.FUTURES_URL = 'https://fapi.binance.com'
    
    logger.info(f"Client Binance configuré avec URL Futures: {client.FUTURES_URL}")
    
    return client

# Client mocké pour le mode test
class MockBinanceClient:
    """Client Binance mocké pour le mode test"""
    
    async def futures_account(self):
        """Simule le compte futures"""
        return {
            "totalWalletBalance": "10000.00",
            "totalUnrealizedProfit": "250.00",
            "availableBalance": "9750.00",
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "positionAmt": "0.01",
                    "entryPrice": "50000",
                    "markPrice": "50600",
                    "unRealizedProfit": "60"
                },
                {
                    "symbol": "ETHUSDT",
                    "positionAmt": "-0.2",
                    "entryPrice": "2500",
                    "markPrice": "2487.5",
                    "unRealizedProfit": "2.5"
                }
            ]
        }
    
    async def futures_position_information(self, symbol=None):
        """Simule les informations de position"""
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.01",
                "entryPrice": "50000",
                "markPrice": "50600",
                "unRealizedProfit": "60",
                "liquidationPrice": "0",
                "leverage": "10",
                "maxNotionalValue": "1000000",
                "marginType": "isolated",
                "isolatedMargin": "500",
                "isAutoAddMargin": "false",
                "positionSide": "BOTH"
            },
            {
                "symbol": "ETHUSDT",
                "positionAmt": "-0.2",
                "entryPrice": "2500",
                "markPrice": "2487.5",
                "unRealizedProfit": "2.5",
                "liquidationPrice": "0",
                "leverage": "10",
                "maxNotionalValue": "1000000",
                "marginType": "isolated",
                "isolatedMargin": "500",
                "isAutoAddMargin": "false",
                "positionSide": "BOTH"
            }
        ]
        
        if symbol:
            return [p for p in positions if p["symbol"] == symbol]
        
        return positions
    
    async def futures_ticker(self, symbol=None):
        """Simule le ticker futures"""
        tickers = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "lastPrice": "50600",
                "volume": "1000000",
                "priceChangePercent": "1.2",
                "highPrice": "51000",
                "lowPrice": "49500"
            },
            "ETHUSDT": {
                "symbol": "ETHUSDT",
                "lastPrice": "2487.5",
                "volume": "500000",
                "priceChangePercent": "-0.5",
                "highPrice": "2550",
                "lowPrice": "2450"
            }
        }
        
        if symbol and symbol in tickers:
            return tickers[symbol]
        elif symbol:
            return {
                "symbol": symbol,
                "lastPrice": "100",
                "volume": "10000",
                "priceChangePercent": "0",
                "highPrice": "105",
                "lowPrice": "95"
            }
        
        return list(tickers.values())
    
    async def futures_klines(self, symbol=None, interval=None, limit=None):
        """Simule les klines futures"""
        return [[0, 100, 105, 95, 102, 10000, 0, 0, 0, 0, 0]]

# Fonction pour initialiser la base de données
async def init_db():
    """Initialise la base de données avec les tables nécessaires"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Création de la table des utilisateurs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            binance_api_key BLOB,
            binance_api_secret BLOB,
            is_active INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            risk_factor REAL DEFAULT 1.0,
            max_position_size REAL DEFAULT 100.0,
            take_profit REAL DEFAULT 0,
            stop_loss REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Vérifier si les colonnes de risque existent, sinon les ajouter
    # Cette partie corrige l'erreur "no such column: risk_factor"
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Ajouter les colonnes manquantes si nécessaire
    if 'risk_factor' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN risk_factor REAL DEFAULT 1.0")
    
    if 'max_position_size' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN max_position_size REAL DEFAULT 100.0")
    
    if 'take_profit' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN take_profit REAL DEFAULT 0")
    
    if 'stop_loss' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN stop_loss REAL DEFAULT 0")
    
    # Créer la table des trades
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            symbol TEXT,
            side TEXT,
            position_side TEXT,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            pnl REAL,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    conn.commit()
    conn.close()
    
    logger.info("Database initialized")

# Fonctions d'aide pour la base de données
async def add_user(telegram_id, username=None, first_name=None, last_name=None, is_admin=False):
    """Ajoute un utilisateur à la base de données ou le met à jour s'il existe déjà"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Vérifier si l'utilisateur existe déjà
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    
    if user:
        # Mettre à jour l'utilisateur existant
        cursor.execute("""
            UPDATE users SET 
                username = COALESCE(?, username),
                first_name = COALESCE(?, first_name),
                last_name = COALESCE(?, last_name),
                is_admin = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        """, (username, first_name, last_name, 1 if is_admin else 0, telegram_id))
    else:
        # Créer un nouvel utilisateur
        cursor.execute("""
            INSERT INTO users (
                telegram_id, username, first_name, last_name, is_admin
            ) VALUES (?, ?, ?, ?, ?)
        """, (telegram_id, username, first_name, last_name, 1 if is_admin else 0))
    
    conn.commit()
    conn.close()

async def get_user(telegram_id):
    """Récupère les informations d'un utilisateur depuis la base de données"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT telegram_id, username, first_name, last_name, binance_api_key, binance_api_secret, " +
        "is_active, is_admin, risk_factor, max_position_size, take_profit, stop_loss " +
        "FROM users WHERE telegram_id = ?", 
        (telegram_id,)
    )
    
    user = cursor.fetchone()
    
    conn.close()
    
    if user:
        return {
            "id": user[0],
            "username": user[1],
            "first_name": user[2],
            "last_name": user[3],
            "is_active": bool(user[6]),
            "is_admin": bool(user[7]),
            "risk_factor": user[8] if user[8] is not None else 1.0,
            "max_position_size": user[9] if user[9] is not None else 100.0,
            "take_profit": user[10] if user[10] is not None else 0.0,
            "stop_loss": user[11] if user[11] is not None else 0.0
        }
    return None

# Fonctions de chiffrement
def encrypt_api_key(api_key):
    """Chiffre une clé API"""
    if isinstance(api_key, str):
        api_key = api_key.encode()
    return fernet.encrypt(api_key)

def decrypt_api_key(encrypted_key):
    """Déchiffre une clé API"""
    if encrypted_key:
        try:
            decrypted = fernet.decrypt(encrypted_key)
            result = decrypted.decode().strip()
            return result
        except Exception as e:
            logger.error(f"Erreur lors du déchiffrement de la clé API: {e}")
    return None

async def add_binance_keys(telegram_id, api_key, api_secret):
    """Ajoute ou met à jour les clés API Binance d'un utilisateur"""
    encrypted_api_key = encrypt_api_key(api_key)
    encrypted_api_secret = encrypt_api_key(api_secret)
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users SET 
            binance_api_key = ?,
            binance_api_secret = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_id = ?
    """, (encrypted_api_key, encrypted_api_secret, telegram_id))
    
    conn.commit()
    conn.close()

async def get_binance_keys(telegram_id):
    """Récupère les clés API Binance d'un utilisateur"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT binance_api_key, binance_api_secret FROM users WHERE telegram_id = ?", (telegram_id,))
    keys = cursor.fetchone()
    
    conn.close()
    
    if keys and keys[0] and keys[1]:
        return decrypt_api_key(keys[0]), decrypt_api_key(keys[1])
    return None, None

async def handle_api_command(chat_id, user, args=None):
    """Gestion de la commande /api pour enregistrer les clés API"""
    # Si c'est une commande sans arguments, on explique comment l'utiliser
    if not args:
        send_telegram_message(chat_id, "Format incorrect. Utilisez /api VOTRE_CLE_API VOTRE_CLE_SECRETE")
        return
    
    # Si l'utilisateur est en attente d'une clé API secrète
    if len(args) == 1 and user_states.get(chat_id, {}).get('state') == 'waiting_for_api_secret':
        api_key = user_states[chat_id]['api_key']
        api_secret = args[0]
        
        # Supprimer l'état
        if chat_id in user_states:
            del user_states[chat_id]
            
        # Enregistrer les clés
        await add_binance_keys(user["id"], api_key, api_secret)
        
        # Définir les paramètres de risque par défaut s'ils n'existent pas
        await update_risk_settings(user["id"])
        
        confirmation = """<b>À Vos clés API ont été enregistrées avec succès!</b>

La copie des trades est maintenant activée pour votre compte.

Utilisez /risk pour configurer vos paramètres de risque.
Utilisez /status pour voir l'état actuel de vos positions."""

        send_telegram_message(chat_id, confirmation)
        
        # Notifier l'administrateur
        if user["id"] != ADMIN_ID:
            admin_msg = f"Nouvel utilisateur enregistré: {user.get('first_name')} (@{user.get('username')}) - ID: {user['id']}"
            send_telegram_message(ADMIN_ID, admin_msg)
        return
    
    # Si l'utilisateur envoie juste la clé API, on lui demande la clé secrète
    if len(args) == 1:
        api_key = args[0]
        
        # Stockage temporaire de la clé API
        user_states[chat_id] = {
            'state': 'waiting_for_api_secret',
            'api_key': api_key
        }
        
        send_telegram_message(chat_id, "Veuillez maintenant envoyer votre clé secrète Binance.")
        return
    
    # Si l'utilisateur envoie les deux clés dans la même commande
    if len(args) >= 2:
        api_key = args[0]
        api_secret = args[1]
        
        # Vérification basique de la validité des clés
        if len(api_key) < 10 or len(api_secret) < 10:
            send_telegram_message(chat_id, "Les clés API semblent invalides. Veuillez vérifier et réessayer.")
            return
        
        # Enregistrer les clés
        await add_binance_keys(user["id"], api_key, api_secret)
        
        # Définir les paramètres de risque par défaut s'ils n'existent pas
        await update_risk_settings(user["id"])
        
        confirmation = """<b>À Vos clés API ont été enregistrées avec succès!</b>

La copie des trades est maintenant activée pour votre compte.

Utilisez /risk pour configurer vos paramètres de risque.
Utilisez /status pour voir l'état actuel de vos positions."""

        send_telegram_message(chat_id, confirmation)
        
        # Notifier l'administrateur
        if user["id"] != ADMIN_ID:
            admin_msg = f"Nouvel utilisateur enregistré: {user.get('first_name')} (@{user.get('username')}) - ID: {user['id']}"
            send_telegram_message(ADMIN_ID, admin_msg)

# Fonction pour mettre à jour les paramètres de risque
async def update_risk_settings(telegram_id, risk_factor=None, max_position_size=None, take_profit=None, stop_loss=None):
    """Met à jour les paramètres de risque d'un utilisateur"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Vérifier d'abord si les paramètres existent déjà
    cursor.execute('SELECT risk_factor, max_position_size, take_profit, stop_loss FROM users WHERE telegram_id = ?', (telegram_id,))
    current_settings = cursor.fetchone()
    
    # Si aucun paramètre n'est fourni, utiliser les valeurs par défaut ou conserver les valeurs actuelles
    if risk_factor is None:
        risk_factor = current_settings[0] if current_settings and current_settings[0] else 1.0
    
    if max_position_size is None:
        max_position_size = current_settings[1] if current_settings and current_settings[1] else 100.0
    
    if take_profit is None:
        take_profit = current_settings[2] if current_settings and current_settings[2] else 0.0
    
    if stop_loss is None:
        stop_loss = current_settings[3] if current_settings and current_settings[3] else 0.0
    
    # Mettre à jour les paramètres
    cursor.execute("""
        UPDATE users SET 
            risk_factor = ?,
            max_position_size = ?,
            take_profit = ?,
            stop_loss = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_id = ?
    """, (risk_factor, max_position_size, take_profit, stop_loss, telegram_id))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Paramètres de risque mis à jour pour l'utilisateur {telegram_id}")
    return True

# Fonctions pour l'API Telegram
def send_telegram_message(chat_id, text, parse_mode="HTML", reply_markup=None):
    """Envoie un message via l'API Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Préparer les données
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    
    # Ajouter les boutons si spécifiés
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    
    # Envoyer la requête
    try:
        response = requests.post(url, data=data)
        response.raise_for_status()
        logger.info(f"Message sent to {chat_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi du message Telegram: {e}")
        return None

async def get_telegram_updates(offset=None, timeout=30):
    """Récupère les mises à jour de l'API Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": timeout}
    
    if offset:
        params["offset"] = offset
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to get updates: {response.text}")
            return {"ok": False, "result": []}
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return {"ok": False, "result": []}

# Fonction pour démarrer le copy trader
async def start_copy_trader():
    """Démarrer le système de copy trading s'il n'est pas déjà en cours d'exécution"""
    global copy_trader
    
    # Vérifier si le copy trader est déjà en cours d'exécution
    if copy_trader and copy_trader.running:
        logger.info("Copy trader est déjà en cours d'exécution")
        return
    
    # Mode test (ignorer les erreurs de connexion Binance)
    test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
    # En mode test, utiliser un copy trader simulé
    if test_mode:
        logger.warning("Mode test activé: le copy trader fonctionne en mode simulé sans connexion réelle à Binance")
        
        # Créer une classe simulée avec les mêmes méthodes que le vrai copy trader
        class MockCopyTrader:
            def __init__(self):
                self.running = True
                self.active_users = {}  # Utilisateurs actifs simulés
                self.master_client = None  # Client simulé
                self.follower_clients = {}  # Clients d'abonnés simulés
                self.master_positions = []  # Positions simulées
                self.user_positions = {}  # Positions des utilisateurs simulées
                logger.info("MockCopyTrader initialisé")
                
            def start(self):
                logger.info("MockCopyTrader démarré")
                
            def stop(self):
                self.running = False
                logger.info("MockCopyTrader arrêté")
            
            def reload_users(self):
                # Simule le rechargement des utilisateurs depuis la base de données
                logger.info("Mode test: rechargement simulé des utilisateurs")
                
                # Charger les utilisateurs actifs depuis la base de données réelle
                conn = sqlite3.connect(DATABASE_PATH)
                cursor = conn.cursor()
                cursor.execute("SELECT telegram_id FROM users WHERE is_active = 1")
                users = cursor.fetchall()
                conn.close()
                
                # Simuler l'ajout des utilisateurs actifs
                for user in users:
                    telegram_id = user[0]
                    self.active_users[telegram_id] = {
                        'telegram_id': telegram_id,
                        'risk_factor': 1.0,
                        'max_position_size': 100.0,
                        'client': None  # Pas de vrai client en mode test
                    }
                    
                logger.info(f"Mode test: {len(self.active_users)} utilisateurs actifs chargés")
                return True
                
            def get_master_positions(self):
                # Retourne des positions simulées pour le compte maître
                return [
                    {"symbol": "BTCUSDT", "positionAmt": "0.01", "entryPrice": "50000", "markPrice": "50500", "unRealizedProfit": "5.0"},
                    {"symbol": "ETHUSDT", "positionAmt": "-0.5", "entryPrice": "2600", "markPrice": "2590", "unRealizedProfit": "5.0"}
                ]
                
            def get_user_positions(self, telegram_id):
                # Retourne des positions simulées pour un utilisateur spécifique
                return [
                    {"symbol": "BTCUSDT", "positionAmt": "0.005", "entryPrice": "50100", "markPrice": "50500", "unRealizedProfit": "2.0"},
                    {"symbol": "ETHUSDT", "positionAmt": "-0.2", "entryPrice": "2580", "markPrice": "2590", "unRealizedProfit": "-2.0"}
                ]
                
            def add_user(self, telegram_id, api_key, api_secret, risk_factor=1.0, max_position_size=0.0):
                # Simule l'ajout d'un nouvel utilisateur
                logger.info(f"Mode test: ajout simulé de l'utilisateur {telegram_id}")
                self.active_users[telegram_id] = {
                    'telegram_id': telegram_id,
                    'risk_factor': risk_factor,
                    'max_position_size': max_position_size,
                    'client': None  # Pas de vrai client en mode test
                }
                return True
                
            def remove_user(self, telegram_id):
                # Simule la suppression d'un utilisateur
                if telegram_id in self.active_users:
                    del self.active_users[telegram_id]
                    logger.info(f"Mode test: utilisateur {telegram_id} supprimé")
                    return True
                return False
        
        copy_trader = MockCopyTrader()
        copy_trader.start()
        logger.info("Copy trader simulé démarré avec succès")
        return
        
    # Récupérer les clés API du compte maître
    master_api_key = os.getenv("MASTER_BINANCE_API_KEY")
    master_api_secret = os.getenv("MASTER_BINANCE_API_SECRET")
    
    if not master_api_key or not master_api_secret:
        logger.error("Clés API du compte maître non configurées dans .env")
        return
    
    # Testnet ou production
    testnet = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
    
    try:
        from copy_trader import CopyTrader
        
        # Initialiser et démarrer le copy trader
        copy_trader = CopyTrader(
            master_api_key=master_api_key,
            master_api_secret=master_api_secret,
            database_path=DATABASE_PATH,
            testnet=testnet
        )
        
        copy_trader.start()
        logger.info("Copy trader démarré avec succès")
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du copy trader: {e}")

# Fonction pour arrêter le copy trader
async def stop_copy_trader():
    """Arrêter le système de copy trading"""
    global copy_trader
    
    if copy_trader and copy_trader.running:
        copy_trader.stop()
        logger.info("Copy trader arrêté")

# Handlers de commandes
async def handle_start_command(chat_id, user):
    """Gestion de la commande /start"""
    # Vérifier si l'utilisateur est nouveau ou s'il se reconnecte
    if not user:
        # Nouvel utilisateur : initialiser dans la base de données
        username = f"user_{chat_id}"  # Remplacer par le vrai username si disponible
        await add_user(chat_id, username, "", "")
        
        welcome_text = """<b>ud83dudc4b Bienvenue sur le Bot de Copy Trading Binance!</b>

Ce bot vous permet de copier automatiquement les trades d'un compte maître sur votre compte Binance Futures.

Pour commencer, suivez ces étapes:
1. Utilisez /subscribe pour vous abonner au service
2. Configurez vos clés API Binance avec /api
3. Personnalisez vos paramètres de risque avec /risk

Utilisez /help pour voir toutes les commandes disponibles."""

    else:
        # Utilisateur existant : réactiver son compte
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users SET 
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE telegram_id = ?
        """, (chat_id,))
        
        conn.commit()
        conn.close()
        
        welcome_text = """<b>u2705 Copy Trading réactivé!</b>

Votre compte a été réactivé et le copy trading est maintenant actif.
Vous recevrez désormais les trades du compte maître selon vos paramètres de risque.

Utilisez /status pour voir l'état de votre compte.
Utilisez /risk pour configurer vos paramètres de risque."""

    # Essayer de démarrer le copy trader si ce n'est pas déjà fait
    await start_copy_trader()
        
    # Envoyer le message de bienvenue
    send_telegram_message(chat_id, welcome_text)

async def handle_help_command(chat_id, user):
    """Gestion de la commande /help"""
    help_text = """<b>ud83eudd16 Bot de Copy Trading Binance - Aide</b>

Voici les commandes disponibles:

/start - Démarrer ou réactiver le bot
/subscribe - S'abonner au service de copy trading
/api - Configurer vos clés API Binance
/risk - Configurer vos paramètres de risque
/status - Voir l'état de vos positions
/history - Voir l'historique de vos trades
/stop - Désactiver le copy trading
/unregister - Supprimer vos clés API
/help - Afficher cette aide

Pour plus d'informations, contactez l'administrateur."""
    
    send_telegram_message(chat_id, help_text)

async def handle_subscribe_command(chat_id, user):
    """Gestion de la commande /subscribe pour activer le copy trading"""
    # Vérifier si l'utilisateur existe et a des clés API configurées
    api_key, api_secret = await get_binance_keys(user["id"])
    
    if not api_key or not api_secret:
        # L'utilisateur n'a pas encore configuré ses clés API
        subscribe_text = """<b>u26a0ufe0f Configuration incomplète</b>

Vous devez d'abord configurer vos clés API Binance pour pouvoir vous abonner au copy trading.

Utilisez la commande /api pour configurer vos clés."""
        send_telegram_message(chat_id, subscribe_text)
        return
    
    # Vérifier si l'utilisateur a déjà configuré ses paramètres de risque
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT is_active, risk_factor, max_position_size FROM users WHERE telegram_id = ?', (user["id"],))
    user_settings = cursor.fetchone()
    
    if user_settings and user_settings[0]:
        # L'utilisateur est déjà actif
        subscribe_text = """<b>ud83dude80 Déjà abonné!</b>

Vous êtes déjà abonné au service de copy trading.

Vos paramètres actuels:
<b>Facteur de risque:</b> {risk_factor}x
<b>Taille max de position:</b> {max_position} USDT

Utilisez /status pour voir l'état de vos positions.
Utilisez /risk pour modifier vos paramètres de risque.
Utilisez /stop pour désactiver le copy trading.""".format(
            risk_factor=user_settings[1],
            max_position=user_settings[2]
        )
        send_telegram_message(chat_id, subscribe_text)
        return
    
    # Activer le copy trading pour cet utilisateur
    cursor.execute('UPDATE users SET is_active = 1 WHERE telegram_id = ?', (user["id"],))
    conn.commit()
    
    # Vérifier si l'utilisateur a des paramètres de risque
    if not user_settings or not user_settings[1]:
        # Configurer des paramètres par défaut
        await update_risk_settings(user["id"])
        cursor.execute('SELECT risk_factor, max_position_size FROM users WHERE telegram_id = ?', (user["id"],))
        default_settings = cursor.fetchone()
        risk_factor = default_settings[0]
        max_position = default_settings[1]
    else:
        risk_factor = user_settings[1]
        max_position = user_settings[2]
    
    conn.close()
    
    # Informer l'utilisateur
    subscribe_text = """<b>ud83dude80 Abonnement activé!</b>

Votre compte est maintenant configuré pour recevoir les copy trades.

Vos paramètres:
<b>Facteur de risque:</b> {risk_factor}x
<b>Taille max de position:</b> {max_position} USDT

Vous recevrez automatiquement les trades du compte principal selon vos paramètres de risque.

Utilisez /status pour voir l'état de vos positions.
Utilisez /risk pour modifier vos paramètres de risque.
Utilisez /stop pour désactiver le copy trading à tout moment.""".format(
        risk_factor=risk_factor,
        max_position=max_position
    )
    
    send_telegram_message(chat_id, subscribe_text)
    
    # Mettre à jour le copy trader
    copy_trader.reload_users()
    
    logger.info(f"Utilisateur {user['id']} abonné au copy trading")

async def handle_risk_command(chat_id, user, args=None):
    """Gestion de la commande /risk pour configurer les paramètres de risque"""
    # Vérifier si l'utilisateur est configuré
    api_key, api_secret = await get_binance_keys(user["id"])
    
    if not api_key or not api_secret:
        send_telegram_message(chat_id, "<b>u26a0ufe0f Vous devez d'abord configurer vos clés API</b>\n\nUtilisez /api pour configurer vos clés API Binance.")
        return
    
    # Si des arguments sont fournis, mettre à jour les paramètres
    if args and len(args) > 0:
        try:
            # Extraire les paramètres de risque
            risk_factor = float(args[0]) if len(args) > 0 else None
            max_position = float(args[1]) if len(args) > 1 else None
            take_profit = float(args[2]) if len(args) > 2 else None
            stop_loss = float(args[3]) if len(args) > 3 else None
            
            # Valider les valeurs
            if risk_factor is not None and (risk_factor <= 0 or risk_factor > 10):
                send_telegram_message(chat_id, "<b>u26a0ufe0f Erreur:</b> Le facteur de risque doit être compris entre 0 et 10.")
                return
            
            if max_position is not None and (max_position <= 0 or max_position > 1000):
                send_telegram_message(chat_id, "<b>u26a0ufe0f Erreur:</b> La taille maximum de position doit être comprise entre 0 et 1000 USDT.")
                return
            
            # Mettre à jour les paramètres
            await update_risk_settings(user["id"], risk_factor, max_position, take_profit, stop_loss)
            
            # Récupérer les paramètres de risque mis à jour pour les afficher
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            cursor.execute("SELECT risk_factor, max_position_size, take_profit, stop_loss FROM users WHERE telegram_id = ?", (user["id"],))
            settings = cursor.fetchone()
            
            conn.close()
            
            if settings:
                risk_text = f"""<b>u2705 Paramètres de risque mis à jour!</b>

Vos nouveaux paramètres sont:
- <b>Facteur de risque:</b> {settings[0]}x
- <b>Taille max de position:</b> {settings[1]} USDT
- <b>Take Profit:</b> {settings[2]}%
- <b>Stop Loss:</b> {settings[3]}%

Ces paramètres seront appliqués à tous vos futurs trades."""
                
                send_telegram_message(chat_id, risk_text)
            else:
                send_telegram_message(chat_id, "<b>u26a0ufe0f Erreur:</b> Impossible de récupérer vos paramètres de risque. Veuillez réessayer.")
                
        except ValueError:
            send_telegram_message(chat_id, "<b>u26a0ufe0f Format invalide!</b>\n\nUtilisez /risk FACTEUR_RISQUE TAILLE_MAX_POSITION [TAKE_PROFIT] [STOP_LOSS]\n\nExemple: /risk 1.5 100 3 2")
    else:
        # Afficher les paramètres actuels
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT risk_factor, max_position_size, take_profit, stop_loss FROM users WHERE telegram_id = ?", (user["id"],))
        settings = cursor.fetchone()
        
        conn.close()
        
        if settings:
            risk_text = f"""<b>ud83dudccf Paramètres de risque actuels</b>

- <b>Facteur de risque:</b> {settings[0]}x
- <b>Taille max de position:</b> {settings[1]} USDT
- <b>Take Profit:</b> {settings[2]}%
- <b>Stop Loss:</b> {settings[3]}%

Pour modifier ces paramètres, utilisez la commande:
/risk FACTEUR_RISQUE TAILLE_MAX_POSITION [TAKE_PROFIT] [STOP_LOSS]

Exemple: /risk 1.5 100 3 2

Le facteur de risque multiplie la taille des positions du compte maître.
Une valeur de 1.0 signifie que vous copiez exactement les positions du maître."""
        else:
            # Créer des paramètres par défaut
            await update_risk_settings(user["id"])
            
            risk_text = """<b>ud83dudccf Paramètres de risque par défaut</b>

- <b>Facteur de risque:</b> 1.0x
- <b>Taille max de position:</b> 100 USDT
- <b>Take Profit:</b> 0% (suit le maître)
- <b>Stop Loss:</b> 0% (suit le maître)

Pour modifier ces paramètres, utilisez la commande:
/risk FACTEUR_RISQUE TAILLE_MAX_POSITION [TAKE_PROFIT] [STOP_LOSS]

Exemple: /risk 1.5 100 3 2

Le facteur de risque multiplie la taille des positions du compte maître.
Une valeur de 1.0 signifie que vous copiez exactement les positions du maître."""
        
        send_telegram_message(chat_id, risk_text)

async def get_market_data(symbol, force_refresh=False):
    """Récupère les données de marché avec mise en cache"""
    global market_data_cache, market_data_timestamp
    
    now = time.time()
    
    # Vérifier si les données sont en cache et valides
    if not force_refresh and symbol in market_data_cache and now - market_data_timestamp.get(symbol, 0) < CACHE_DURATION:
        logger.debug(f"Utilisation des données en cache pour {symbol}")
        return market_data_cache[symbol]
    
    try:
        # Récupérer les données fraîches
        logger.info(f"Récupération des données de marché pour {symbol}")
        
        # Mode test - génération de données fictives
        if os.getenv("TEST_MODE", "False").lower() == "true":
            data = {
                "symbol": symbol,
                "price": 50000 if "BTC" in symbol else (2500 if "ETH" in symbol else 1.0),
                "volume": 1000000,
                "change_24h": 2.5,
                "high_24h": 51000 if "BTC" in symbol else (2600 if "ETH" in symbol else 1.1),
                "low_24h": 49000 if "BTC" in symbol else (2400 if "ETH" in symbol else 0.9),
                "timestamp": now
            }
        else:
            # Appel Binance API
            binance_client = await get_binance_client()
            ticker = await binance_client.futures_ticker(symbol=symbol)
            klines = await binance_client.futures_klines(symbol=symbol, interval="1d", limit=1)
            
            data = {
                "symbol": symbol,
                "price": float(ticker["lastPrice"]),
                "volume": float(ticker["volume"]),
                "change_24h": float(ticker["priceChangePercent"]),
                "high_24h": float(ticker["highPrice"]),
                "low_24h": float(ticker["lowPrice"]),
                "timestamp": now
            }
        
        # Mettre en cache
        market_data_cache[symbol] = data
        market_data_timestamp[symbol] = now
        
        return data
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des données de marché pour {symbol}: {e}")
        
        # Retourner les données en cache si disponibles, même si expirées
        if symbol in market_data_cache:
            logger.warning(f"Utilisation des données en cache expirées pour {symbol}")
            return market_data_cache[symbol]
        
        # Sinon, retourner des données par défaut
        return {
            "symbol": symbol,
            "price": 0,
            "volume": 0,
            "change_24h": 0,
            "high_24h": 0,
            "low_24h": 0,
            "timestamp": now
        }

async def handle_status_command(chat_id, user):
    """Gestion de la commande /status pour vérifier l'état du compte et des trades en cours"""
    # Vérifier si l'utilisateur est configuré
    try:
        # Vérifier d'abord si le mode test est activé - PRIORITÉ ABSOLUE
        is_test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
        
        # En mode test, on ne tente jamais de se connecter à Binance
        if is_test_mode:
            logger.info("handle_status_command: Mode test activé, utilisation de données simulées")
            
            # Vérifier si l'utilisateur a des clés API
            api_key, api_secret = await get_binance_keys(user["id"])
            if not api_key or not api_secret:
                send_telegram_message(chat_id, "<b>u26a0ufe0f Compte non configuré</b>\n\nVous n'avez pas configuré vos clés API Binance. Utilisez la commande /api pour les configurer.")
                return
                
            # Générer des données fictives en mode test
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT is_active, risk_factor, max_position_size, take_profit, stop_loss FROM users WHERE telegram_id = ?", (user["id"],))
            user_data = cursor.fetchone()
            conn.close()
            
            # Texte du statut
            status_text = f"<b>ud83dudd0e Statut de votre compte (MODE TEST)</b>\n\n"
            
            if user_data and user_data[0] == 1:  # is_active
                status_text += "u2705 <b>Copy Trading:</b> Activé\n"
            else:
                status_text += "u274c <b>Copy Trading:</b> Désactivé\n"
            
            status_text += f"ud83dudcb0 <b>Solde:</b> 10,000 USDT\n"
            status_text += f"ud83dudcb8 <b>PnL journalier:</b> +250 USDT (+2.5%)\n\n"
            
            # Paramètres de risque
            if user_data:
                risk_factor = user_data[1] if user_data[1] is not None else 1.0
                max_position = user_data[2] if user_data[2] is not None else 0.0
                take_profit = user_data[3] if user_data[3] is not None else 0.0
                stop_loss = user_data[4] if user_data[4] is not None else 0.0
                
                status_text += f"<b>ud83dudccf Paramètres de risque:</b>\n"
                status_text += f"u2022 Facteur de risque: {risk_factor}x\n"
                status_text += f"u2022 Taille max: {max_position} USDT\n"
                status_text += f"u2022 Take Profit: {take_profit}%\n"
                status_text += f"u2022 Stop Loss: {stop_loss}%\n\n"
            
            # Positions fictives
            status_text += "<b>ud83dudcca Positions ouvertes:</b>\n"
            status_text += "BTC/USDT: Long 0.01 BTC à 50,000 USDT (+1.2%)\n"
            status_text += "ETH/USDT: Short 0.2 ETH à 2,500 USDT (-0.5%)\n\n"
            
            status_text += "<i>ud83dudca1 Note: Ces données sont des simulations pour le mode test</i>"
            
            # Ajouter des boutons pour les actions communes
            keyboard = [
                [{"text": "ud83dudcca Historique", "callback_data": "history"}],
                [{"text": "u2699ufe0f Risque", "callback_data": "risk"}, {"text": "ud83dude80 Activer", "callback_data": "subscribe"}],
                [{"text": "ud83dude45 Désactiver", "callback_data": "stop"}, {"text": "u2753 Aide", "callback_data": "help"}]
            ]
            
            # Envoyer le message avec les boutons
            send_telegram_message(chat_id, status_text, reply_markup={"inline_keyboard": keyboard})
            return
            
        # Si nous sommes ici, c'est que le mode test est désactivé (TEST_MODE=False)
        # Vérifier si l'utilisateur a des clés API
        api_key, api_secret = await get_binance_keys(user["id"])
        if not api_key or not api_secret:
            send_telegram_message(chat_id, "<b>u26a0ufe0f Compte non configuré</b>\n\nVous n'avez pas configuré vos clés API Binance. Utilisez la commande /api pour les configurer.")
            return
        
        # Mode normal - connecter à Binance
        try:
            # Essayer de se connecter à Binance
            client = await get_binance_client(api_key, api_secret)
            
            # Récupérer les informations du compte
            account = await client.futures_account()
            positions = await client.futures_position_information()
            
            # Récupérer les infos utilisateur de la base de données
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT is_active, risk_factor, max_position_size, take_profit, stop_loss FROM users WHERE telegram_id = ?", (user["id"],))
            user_data = cursor.fetchone()
            conn.close()
            
            # Construire le message
            total_balance = float(account["totalWalletBalance"])
            total_upnl = float(account["totalUnrealizedProfit"])
            
            # Texte du statut
            status_text = f"<b>ud83dudd0e Statut de votre compte</b>\n\n"
            
            if user_data and user_data[0] == 1:  # is_active
                status_text += "u2705 <b>Copy Trading:</b> Activé\n"
            else:
                status_text += "u274c <b>Copy Trading:</b> Désactivé\n"
            
            status_text += f"ud83dudcb0 <b>Solde:</b> {total_balance:.2f} USDT\n"
            status_text += f"ud83dudcb8 <b>PnL non réalisé:</b> {total_upnl:.2f} USDT\n\n"
            
            # Paramètres de risque
            if user_data:
                risk_factor = user_data[1] if user_data[1] is not None else 1.0
                max_position = user_data[2] if user_data[2] is not None else 0.0
                take_profit = user_data[3] if user_data[3] is not None else 0.0
                stop_loss = user_data[4] if user_data[4] is not None else 0.0
                
                status_text += f"<b>ud83dudccf Paramètres de risque:</b>\n"
                status_text += f"u2022 Facteur de risque: {risk_factor}x\n"
                status_text += f"u2022 Taille max: {max_position} USDT\n"
                status_text += f"u2022 Take Profit: {take_profit}%\n"
                status_text += f"u2022 Stop Loss: {stop_loss}%\n\n"
            
            # Positions ouvertes
            active_positions = [p for p in positions if float(p["positionAmt"]) != 0]
            status_text += f"<b>ud83dudcca Positions ouvertes:</b> {len(active_positions)}\n"
            
            if active_positions:
                for pos in active_positions[:5]:  # Limiter à 5 positions pour éviter un message trop long
                    symbol = pos["symbol"]
                    side = "Long" if float(pos["positionAmt"]) > 0 else "Short"
                    amount = abs(float(pos["positionAmt"]))
                    entry_price = float(pos["entryPrice"])
                    mark_price = float(pos["markPrice"])
                    pnl = float(pos["unRealizedProfit"])
                    pnl_percent = (mark_price / entry_price - 1) * 100 if side == "Long" else (1 - mark_price / entry_price) * 100
                    
                    status_text += f"{symbol}: {side} {amount} à {entry_price} ({pnl:.2f} USDT, {pnl_percent:.2f}%)\n"
                
                if len(active_positions) > 5:
                    status_text += f"... et {len(active_positions) - 5} autres positions\n"
            else:
                status_text += "Aucune position ouverte\n"
            
            # Ajouter des boutons pour les actions communes
            keyboard = [
                [{"text": "ud83dudcca Historique", "callback_data": "history"}],
                [{"text": "u2699ufe0f Risque", "callback_data": "risk"}, {"text": "ud83dude80 Activer", "callback_data": "subscribe"}],
                [{"text": "ud83dude45 Désactiver", "callback_data": "stop"}, {"text": "u2753 Aide", "callback_data": "help"}]
            ]
            
            # Envoyer le message avec les boutons
            send_telegram_message(chat_id, status_text, reply_markup={"inline_keyboard": keyboard})
        
        except Exception as e:
            # En cas d'erreur de connexion, afficher un message d'erreur explicite
            logger.error(f"Erreur lors de la connexion à Binance: {e}")
            
            error_text = f"<b>u26a0ufe0f Erreur de connexion à Binance</b>\n\n"
            error_text += "Impossible de se connecter à Binance. Veuillez vérifier vos clés API et votre connexion internet.\n\n"
            error_text += "<i>Astuce: Vous pouvez activer le mode test dans le fichier .env pour utiliser le bot sans connexion à Binance.</i>"
            
            # Ajouter des boutons pour les actions alternatives
            keyboard = [
                [{"text": "ud83dude80 Activer mode test", "callback_data": "help"}],
                [{"text": "ud83dude4b Re-configurer API", "callback_data": "api"}]
            ]
            
            send_telegram_message(chat_id, error_text, reply_markup={"inline_keyboard": keyboard})
    
    except Exception as e:
        logger.error(f"Erreur dans handle_status_command: {e}")
        error_msg = f"<b>u26a0ufe0f Erreur</b>\n\nUne erreur s'est produite lors de la récupération de votre statut: {e}"
        send_telegram_message(chat_id, error_msg)

async def handle_history_command(chat_id, user, args=None):
    """Gestion de la commande /history pour voir l'historique des trades"""
    # Vérifier si l'utilisateur est configuré
    api_key, api_secret = await get_binance_keys(user["id"])
    
    if not api_key or not api_secret:
        send_telegram_message(chat_id, "<b>u26a0ufe0f Vous devez d'abord configurer vos clés API</b>\n\nUtilisez /api pour configurer vos clés API Binance.")
        return
    
    # Mode test
    test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
    
    # En mode test, afficher des données simulées
    if test_mode:
        history_text = """<b>ud83dudcc3 Historique des Trades (MODE TEST)</b>

<b>Trades récents:</b>
1. BTC/USDT: Long à $42,500 - Fermé à $43,200 (+3.5%)
2. ETH/USDT: Short à $2,950 - Fermé à $2,850 (+3.4%)
3. SOL/USDT: Long à $85.50 - Fermé à $88.20 (+3.2%)

<b>Performance totale:</b> +9.5%

Ces données sont simulées pour le mode test."""
        
        # Ajouter des boutons pour les actions communes
        keyboard = [
            [{"text": "ud83dudd0e Statut", "callback_data": "status"}],
            [{"text": "u2699ufe0f Risque", "callback_data": "risk"}, {"text": "ud83dude80 Activer", "callback_data": "subscribe"}],
            [{"text": "ud83dude45 Désactiver", "callback_data": "stop"}, {"text": "u2753 Aide", "callback_data": "help"}]
        ]
        
        send_telegram_message(chat_id, history_text, reply_markup={"inline_keyboard": keyboard})
        return
    
    # Mode normal - obtenir l'historique des trades réels
    try:
        # Récupérer l'ID de l'utilisateur dans la base de données
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user["id"],))
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            send_telegram_message(chat_id, "<b>u26a0ufe0f Utilisateur non trouvé</b>\n\nVous n'êtes pas enregistré dans la base de données.")
            return
        
        user_db_id = result[0]
        
        # Récupérer les trades de l'utilisateur
        cursor.execute("SELECT symbol, side, position_side, entry_price, exit_price, quantity, pnl, status, created_at FROM trades WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (user_db_id,))
        trades = cursor.fetchall()
        conn.close()
        
        if not trades:
            history_text = "<b>ud83dudcc3 Historique des Trades</b>\n\nVous n'avez pas encore de trades dans l'historique."
        else:
            # Calculer la performance totale
            total_pnl = sum(float(trade[6]) for trade in trades if trade[6] is not None)
            
            history_text = "<b>ud83dudcc3 Historique des Trades</b>\n\n<b>10 derniers trades:</b>\n"
            
            for i, trade in enumerate(trades, 1):
                symbol = trade[0]
                side = trade[1]
                entry_price = float(trade[3]) if trade[3] is not None else 0
                exit_price = float(trade[4]) if trade[4] is not None else 0
                quantity = float(trade[5]) if trade[5] is not None else 0
                pnl = float(trade[6]) if trade[6] is not None else 0
                status = trade[7]
                date = trade[8][:10] if trade[8] else ""
                
                pnl_percent = 0
                if entry_price > 0 and exit_price > 0:
                    if side.upper() == "BUY":
                        pnl_percent = ((exit_price / entry_price) - 1) * 100
                    else:
                        pnl_percent = ((1 - (exit_price / entry_price))) * 100
                
                history_text += f"{i}. {symbol}: {side.capitalize()} à {entry_price} - "
                
                if status.upper() == "CLOSED":
                    history_text += f"Fermé à {exit_price} ({pnl:.2f} USDT, {pnl_percent:.2f}%)\n"
                else:
                    history_text += f"Ouvert ({status})\n"
            
            history_text += f"\n<b>Performance totale:</b> {total_pnl:.2f} USDT"
        
        # Ajouter des boutons pour les actions communes
        keyboard = [
            [{"text": "ud83dudd0e Statut", "callback_data": "status"}],
            [{"text": "u2699ufe0f Risque", "callback_data": "risk"}, {"text": "ud83dude80 Activer", "callback_data": "subscribe"}],
            [{"text": "ud83dude45 Désactiver", "callback_data": "stop"}, {"text": "u2753 Aide", "callback_data": "help"}]
        ]
        
        send_telegram_message(chat_id, history_text, reply_markup={"inline_keyboard": keyboard})
    except Exception as e:
        logger.error(f"Erreur dans handle_history_command: {e}")
        send_telegram_message(
            chat_id,
            f"<b>u26a0ufe0f Erreur</b>\n\nUne erreur s'est produite lors de la récupération de votre historique: {e}"
        )
    
    finally:
        conn.close()

async def handle_stop_command(chat_id, user):
    """Gestion de la commande /stop pour désactiver le copy trading"""
    # Vérifier si l'utilisateur existe
    if not user:
        send_telegram_message(chat_id, "<b>u26a0ufe0f Erreur:</b> Votre compte n'est pas encore enregistré. Utilisez /start pour commencer.")
        return
    
    # Désactiver l'utilisateur dans la base de données
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE users SET 
            is_active = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE telegram_id = ?
    """, (user["id"],))
    
    conn.commit()
    conn.close()
    
    stop_text = """<b>u26d4 Copy Trading désactivé</b>

Le copy trading a été désactivé pour votre compte.
Vous ne recevrez plus les trades du compte maître.

Notez que cela n'affecte pas vos positions ouvertes existantes.
Utilisez /start pour réactiver le copy trading à tout moment."""
    
    send_telegram_message(chat_id, stop_text)

async def handle_unregister_command(chat_id, user):
    """Gestion de la commande /unregister pour supprimer les clés API d'un utilisateur"""
    try:
        # Vérifier si l'utilisateur a des clés enregistrées
        api_key, api_secret = await get_binance_keys(user["id"])
        
        if not api_key or not api_secret:
            send_telegram_message(chat_id, "<b>u26a0ufe0f Vous n'êtes pas enregistré</b>\n\nVous n'avez pas de clés API enregistrées dans le système.")
            return
        
        # Supprimer les clés API de l'utilisateur de la base de données
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Désactiver d'abord le copy trading pour cet utilisateur
        cursor.execute('UPDATE users SET is_active = 0, risk_factor = 0 WHERE telegram_id = ?', (user["id"],))
        
        # Supprimer les clés API
        cursor.execute('UPDATE users SET binance_api_key = NULL, binance_api_secret = NULL WHERE telegram_id = ?', (user["id"],))
        
        conn.commit()
        conn.close()
        
        # Informer l'utilisateur
        send_telegram_message(
            chat_id,
            "<b>ud83dudd12 Clés API supprimées avec succès</b>\n\nVos clés API ont été supprimées de notre système. Vous ne recevrez plus de copies de trades.\n\nVous pouvez vous ré-enregistrer à tout moment avec la commande /api."
        )
        
        # Mettre à jour le copy trader
        global copy_trader
        if copy_trader and hasattr(copy_trader, 'reload_users'):
            copy_trader.reload_users()
        
        logger.info(f"Clés API supprimées pour l'utilisateur {user['id']}")
    except Exception as e:
        logger.error(f"Erreur lors de la suppression des clés API: {e}")
        send_telegram_message(
            chat_id,
            f"<b>u26a0ufe0f Erreur</b>\n\nUne erreur s'est produite lors de la suppression de vos clés API: {e}"
        )

# Fonction principale pour le traitement des commandes
async def process_update(update):
    """Traite une mise à jour de l'API Telegram"""
    # Gérer les callback_query (boutons inline)
    if "callback_query" in update:
        callback_query = update["callback_query"]
        chat_id = callback_query["message"]["chat"]["id"]
        telegram_id = callback_query["from"]["id"]
        callback_data = callback_query["data"]
        
        # Récupérer l'utilisateur
        user = await get_user(telegram_id)
        
        # Traiter les différents callbacks
        if callback_data == "status":
            await handle_status_command(chat_id, user)
        elif callback_data == "history":
            await handle_history_command(chat_id, user, None)
        elif callback_data == "risk":
            await handle_risk_command(chat_id, user, None) 
        elif callback_data == "subscribe":
            await handle_subscribe_command(chat_id, user)
        elif callback_data == "stop":
            await handle_stop_command(chat_id, user)
        elif callback_data == "help":
            await handle_help_command(chat_id, user)
        elif callback_data == "api":
            await handle_api_command(chat_id, user, None)
        
        # Répondre à la callback pour éviter le "chargement" sur le bouton
        respond_to_callback_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
        response = requests.post(respond_to_callback_url, json={"callback_query_id": callback_query["id"]})
        return
        
    # Suite du code existant...
    if "message" not in update:
        return
    """Traite une mise à jour de l'API Telegram"""
    if "message" not in update:
        return
    
    message = update["message"]
    if "text" not in message:
        return
    
    chat_id = message["chat"]["id"]
    text = message["text"]
    
    # Extraire les informations de l'utilisateur
    telegram_user = message.get("from", {})
    telegram_id = telegram_user.get("id")
    first_name = telegram_user.get("first_name")
    last_name = telegram_user.get("last_name")
    username = telegram_user.get("username")
    
    # Récupérer ou créer l'utilisateur dans la base de données
    user = await get_user(telegram_id)
    if not user:
        # L'utilisateur n'existe pas encore, le créer
        is_admin = telegram_id == ADMIN_ID
        await add_user(telegram_id, username, first_name, last_name, is_admin)
        user = await get_user(telegram_id)
        
        logger.info(f"Nouvel utilisateur créé : {telegram_id} (@{username})")
    
    # Traiter la commande
    if text.startswith("/"):
        parts = text.split()
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else None
        
        logger.info(f"Message du chat {chat_id}: {text}")
        
        # Traiter les commandes
        if command == "/start":
            await handle_start_command(chat_id, user)
        elif command == "/help":
            await handle_help_command(chat_id, user)
        elif command == "/subscribe":
            await handle_subscribe_command(chat_id, user)
        elif command == "/api":
            await handle_api_command(chat_id, user, args)
        elif command == "/risk":
            await handle_risk_command(chat_id, user, args)
        elif command == "/status":
            await handle_status_command(chat_id, user)
        elif command == "/history":
            await handle_history_command(chat_id, user, args)
        elif command == "/stop":
            await handle_stop_command(chat_id, user)
        elif command == "/unregister":
            await handle_unregister_command(chat_id, user)
        elif user_states.get(chat_id, {}).get("state") == "waiting_for_api_secret":
            # Si l'utilisateur est en train d'envoyer sa clé secrète
            await handle_api_command(chat_id, user, [text])
        else:
            # Commande inconnue
            send_telegram_message(chat_id, f"Commande non reconnue: {command}\n\nUtilisez /help pour voir la liste des commandes disponibles.")

# Boucle principale pour les mises à jour
async def main():
    """Fonction principale du bot"""
    # Initialiser la base de données
    await init_db()
    
    # Ligne pour tester le token Telegram
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN non configuré dans .env")
        return
    
    # Ligne pour l'admin
    if not ADMIN_ID:
        logger.warning("ADMIN_ID non configuré dans .env - Certaines fonctionnalités d'administration seront désactivées")
    
    # Démarrer le copy trader
    await start_copy_trader()
    
    # Informer l'admin du démarrage
    if ADMIN_ID:
        welcome_message = """<b>u2705 Bot de Copy Trading démarré!</b>

Le bot est maintenant opérationnel et prêt à traiter les commandes.

<b>ud83dudd27 Commandes disponibles:</b>

<b>Configuration:</b>
/start - Démarrer le bot et afficher l'aide
/api - Configurer vos clés API Binance
/unregister - Supprimer vos clés API

<b>Trading:</b>
/subscribe - Activer le copy trading
/stop - Désactiver le copy trading
/risk - Configurer vos paramètres de risque

<b>Suivi:</b>
/status - Voir l'état de vos positions
/history - Consulter l'historique des trades

<b>Aide:</b>
/help - Afficher ce message d'aide

u2139ufe0f Mode de test: {test_mode_status}
u2139ufe0f Binance Testnet: {testnet_status}"""

        test_mode = os.getenv("TEST_MODE", "False").lower() == "true"
        testnet = os.getenv("BINANCE_TESTNET", "False").lower() == "true"
        
        test_mode_status = "Activé (pas de connexion réelle à Binance)" if test_mode else "Désactivé"
        testnet_status = "Activé (environnement de test Binance)" if testnet else "Désactivé (environnement de production Binance)"

        send_telegram_message(ADMIN_ID, welcome_message.format(test_mode_status=test_mode_status, testnet_status=testnet_status))
    
    logger.info("Bot démarré, en attente des messages...")
    
    # Dernier update ID traité
    last_update_id = None
    
    # Boucle principale
    while True:
        try:
            # Récupérer les mises à jour
            updates = await get_telegram_updates(offset=last_update_id)
            
            if updates["ok"]:
                for update in updates["result"]:
                    # Mettre à jour le dernier ID traité
                    last_update_id = update["update_id"] + 1
                    
                    # Traiter la mise à jour
                    await process_update(update)
            
            # Pause pour éviter de surcharger l'API
            await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
            await asyncio.sleep(5)

# Point d'entrée du programme
if __name__ == "__main__":
    # Configurer le logging
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))
    logger.add("logs/copy_trader_{time}.log", rotation="10 MB")
    
    logger.info("Démarrage du bot de copy trading...")
    
    # Exécuter la boucle principale
    asyncio.run(main())
