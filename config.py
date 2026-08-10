import os
from dotenv import load_dotenv

load_dotenv()

# Путь к базе данных (можно переопределить через .env)
DB_PATH = os.getenv('DB_PATH', 'tattoo_bot.db')

BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("[ERROR] BOT_TOKEN не найден в .env!")

# Админы: один ID или несколько через запятую: ADMIN_ID=111,222
ADMIN_IDS = [int(x) for x in str(os.getenv('ADMIN_ID', '0')).split(',') if x.strip().isdigit()]
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0  # первый — для уведомлений (совместимость)
if not ADMIN_ID:
    print("[WARN] ADMIN_ID не указан в .env")

# ==== MAX (мессенджер VK) ====
# Токен бота MAX: платформа business.max.ru -> Чат-боты -> Расширенные настройки
MAX_TOKEN = os.getenv('MAX_TOKEN')
if not MAX_TOKEN:
    print("[WARN] MAX_TOKEN не указан в .env — MAX-бот недоступен")

# Админы MAX (свои ID, НЕ путать с Telegram): MAX_ADMIN_ID=111,222
MAX_ADMIN_IDS = [int(x) for x in str(os.getenv('MAX_ADMIN_ID', '0')).split(',') if x.strip().isdigit()]
MAX_ADMIN_ID = MAX_ADMIN_IDS[0] if MAX_ADMIN_IDS else 0
if not MAX_ADMIN_ID:
    print("[WARN] MAX_ADMIN_ID не указан в .env — админ-панель MAX будет скрыта")