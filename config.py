import os
from dotenv import load_dotenv

load_dotenv()

# Путь к базе данных (можно переопределить через .env)
DB_PATH = os.getenv('DB_PATH', 'tattoo_bot.db')

# ==== Бренд / отображение ====
BOT_NAME = os.getenv('BOT_NAME', 'PRIZMA')          # отображаемое имя в оверлее
BOT_MASTER = os.getenv('BOT_MASTER', 'Максим Андреевич')  # мастер
BOT_HANDLE = os.getenv('BOT_HANDLE', 'tatoo_asbest_best_bot')  # username бота (без @)
BOT_CITY = os.getenv('BOT_CITY', 'Асбест, ул. Заводская, 4')

# Контактная информация мастера (используется в «О мастере» и уведомлениях)
BOT_ADDRESS = os.getenv('BOT_ADDRESS', 'г. Асбест, ул. Заводская, 4')
BOT_PHONE = os.getenv('BOT_PHONE', '+7 932 112-01-06')
BOT_VK_URL = os.getenv('BOT_VK_URL', 'https://vk.ru/id880400434')
BOT_VK_LABEL = os.getenv('BOT_VK_LABEL', 'ВКонтакте')

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