import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN не найден в .env!")

ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
if not ADMIN_ID:
    print("[WARN] ADMIN_ID не указан в .env")