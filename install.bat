@echo off
echo ===================================
echo Telegram Tattoo Bot - Установка
echo ===================================
echo.

echo [1/3] Установка зависимостей...
pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo Ошибка при установке зависимостей!
    pause
    exit /b 1
)

echo.
echo [2/3] Создание файла .env...
if not exist .env (
    copy .env.example .env
    echo Файл .env создан!
    echo Важно: Отредактируйте .env и добавьте ваш BOT_TOKEN и ADMIN_ID
) else (
    echo Файл .env уже существует
)

echo.
echo [3/3] Инициализация базы данных...
python -c "from database import init_db, add_sample_data; init_db(); add_sample_data()"

if %errorlevel% neq 0 (
    echo.
    echo Ошибка при запуске! Убедитесь что:
    echo 1. Вы установили Python
    echo 2. Вы редактировали файл .env
    echo 3. Добавили правильный BOT_TOKEN
)

echo.
echo ===================================
echo Установка завершена!
echo ===================================
echo.
echo Следующие шаги:
echo 1. Откройте .env и добавьте ваш токен бота
echo 2. Запустите бота: python main.py
echo.
pause