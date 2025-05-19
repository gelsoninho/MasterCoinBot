'''
Script simple pour vérifier si le mode test fonctionne correctement
'''
import os
import sys

# Forcer l'activation du mode test
os.environ["TEST_MODE"] = "True"

# Importer le bot après avoir défini TEST_MODE
import telegram_copy_bot

print("\n============ TEST MODE ACTIVÉ ============\n")
print("Ce script vérifie si le bot fonctionne correctement en mode test.")
print("Aucune connexion à Binance ne devrait être tentée.")

# Exécuter le bot
telegram_copy_bot.asyncio.run(telegram_copy_bot.main())
