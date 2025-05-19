import os
import time

# Chemin vers la base de donnu00e9es
db_path = "copy_trader.db"

# Vu00e9rifier si le fichier existe
if os.path.exists(db_path):
    # Renommer l'ancien fichier avec timestamp
    timestamp = int(time.time())
    backup_name = f"copy_trader_{timestamp}.db.bak"
    os.rename(db_path, backup_name)
    print(f"Base de donnu00e9es renommu00e9e en {backup_name}")
else:
    print("Aucune base de donnu00e9es existante trouvu00e9e.")

print("\nExu00e9cutez maintenant 'python telegram_copy_bot.py' pour cru00e9er une nouvelle base de donnu00e9es.")
