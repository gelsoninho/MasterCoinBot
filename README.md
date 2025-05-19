# Binance Futures Copy Trading Bot with Telegram Integration

Un bot Python avancé qui permet aux utilisateurs de copier automatiquement vos trades Binance Futures, avec une gestion complète et un suivi en temps réel via Telegram.

## Fonctionnalités

- Système de copy trading pour Binance Futures avec mode test intégré
- Interface Telegram intuitive avec boutons interactifs pour une navigation simplifiée
- Copie de trades en temps réel avec paramètres de risque personnalisables par utilisateur
- Système de cache pour les données de marché réduisant les appels API
- Suivi des performances et statistiques détaillées
- Gestion sécurisée des clés API avec chiffrement
- Dashboard complet pour le suivi de l'historique des trades
- Mode test fonctionnel sans connexion à Binance pour le développement

## Prérequis

- Python 3.8+
- Compte Binance avec accès Futures activé
- Compte Telegram
- Bibliothèques nécessaires : python-binance, python-telegram-bot, sqlite3, cryptography, dotenv, loguru, requests

## Installation

1. Clonez ce dépôt:
   ```bash
   git clone https://github.com/votre-username/binance-futures-copy-trader.git
   cd binance-futures-copy-trader
   ```
2. Installez les dépendances:
   ```bash
   pip install -r requirements.txt
   ```
3. Créez un fichier `.env` basé sur le modèle fourni et remplissez les informations nécessaires

## Configuration

1. Créez un bot Telegram en utilisant [BotFather](https://t.me/botfather) et obtenez votre token
2. Créez des clés API Binance avec les permissions appropriées (lecture et trading, sans permission de retrait)
3. Remplissez les détails requis dans le fichier `.env`:
   ```
   # Clés API Binance pour le compte principal
   MASTER_BINANCE_API_KEY=votre_clé_api
   MASTER_BINANCE_API_SECRET=votre_secret_api
   BINANCE_TESTNET=True  # True pour testnet, False pour production
   
   # Configuration du bot Telegram
   TELEGRAM_BOT_TOKEN=votre_token_telegram
   ADMIN_TELEGRAM_ID=votre_id_telegram
   
   # Configuration de la base de données (SQLite par défaut)
   DATABASE_URL=sqlite:///copy_trader.db
   
   # Configuration générale
   LOG_LEVEL=INFO
   TEST_MODE=True  # True pour le mode test, False pour production
   HTTP_TIMEOUT=60
   ```

## Utilisation

### Mode Production
Lancez le bot en mode production (nécessite une connexion à Binance) :
```bash
python telegram_copy_bot.py
```

### Mode Test
Lancez le bot en mode test (fonctionne sans connexion à Binance) :
```bash
python test_mode.py
```

## Commandes Telegram

| Commande | Description |
|---------|-------------|
| /start | Démarrer le bot et afficher l'aide |
| /setup | Configurer les clés API Binance de l'utilisateur |
| /subscribe | S'abonner au copy trading |
| /unsubscribe | Se désabonner du copy trading |
| /status | Afficher le solde, les positions ouvertes et statistiques |
| /history | Consulter l'historique des trades avec pagination |
| /risk | Modifier les paramètres de gestion des risques : 
|  | - risk_factor : facteur de risque pour le sizing des positions
|  | - max_position_size : taille maximale d'une position en USDT
|  | - take_profit : pourcentage de prise de profit
|  | - stop_loss : pourcentage de stop loss
| /stop | Arrêter immédiatement le copy trading |

## Structure du Projet

```
.
├── telegram_copy_bot.py   # Script principal du bot Telegram
├── binance_ws_client.py   # Client WebSocket pour Binance
├── copy_trader.py        # Logique de copy trading
├── test_mode.py         # Script pour le mode test
├── database.py          # Gestion de la base de données
├── .env                 # Variables d'environnement
├── requirements.txt     # Dépendances
├── logs/                # Dossier des logs
└── README.md            # Documentation
```

## Fonctionnalités Avancées

### Système de Cache
Le bot implémente un système de cache pour les données de marché qui réduit considérablement les appels API et améliore la réactivité.

### Boutons Inline Telegram
Les commandes `/status` et `/history` intègrent des boutons interactifs qui améliorent l'expérience utilisateur, particulièrement sur mobile.

### Mode Test
Le mode test permet de développer et tester le bot sans avoir besoin d'une connexion active à Binance, évitant ainsi les erreurs d'API et les problèmes de connectivité.

## Notes de Sécurité

- Ne partagez jamais vos clés API Binance avec d'autres personnes
- Créez toujours des clés API avec des permissions limitées (sans accès au retrait)
- Les clés API sont chiffrées avant d'être stockées dans la base de données
- Stockez votre fichier `.env` en sécurité et ne le committez jamais dans le contrôle de version

## Licence

MIT

## Contributions

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.
