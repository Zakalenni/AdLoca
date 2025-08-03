import os
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv
import asyncpg
import ssl

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# SSL контекст для PostgreSQL
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

# Состояния
class AdminStates(StatesGroup):
    WAITING_TASK_NAME = State()
    WAITING_WORK_TYPE = State()
    WAITING_QUANTITY = State()
    WAITING_USER_SELECTION = State()
    
class UserStates(StatesGroup):
    WAITING_WORK_SELECTION = State()
    WAITING_QUANTITY_DONE = State()
    WAITING_REPORT_CONFIRMATION = State()

# Виды работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка", "Фрезеровка пазов ручек",
    "Распил на ручки"
]

# --- Подключение к PostgreSQL ---
async def create_db_connection():
    return await asyncpg.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        ssl=ssl_ctx
    )

async def init_db():
    conn = await create_db_connection()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS weekly_tasks (
                task_id SERIAL PRIMARY KEY,
                task_name TEXT NOT NULL,
                work_type TEXT NOT NULL,
                total_quantity INTEGER NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS user_tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                task_id INTEGER REFERENCES weekly_tasks(task_id),
                quantity_done INTEGER DEFAULT 0,
                report_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Добавляем администратора, если его нет
        admin_id = os.getenv('ADMIN_ID')
        if admin_id:
            await conn.execute('''
                INSERT INTO users (user_id, is_admin, is_active)
                VALUES ($1, TRUE, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET is_admin = TRUE
            ''', int(admin_id))
            
    finally:
        await conn.close()

# --- Вспомогательные функции ---
async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

def get_current_week_dates():
    today = datetime.now()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start.date(), end.date()

async def get_user_name(user_id: int) -> str:
    conn = await create_db_connection()
    try:
        user = await conn.fetchrow('SELECT full_name FROM users WHERE user_id = $1', user_id)
        return user['full_name'] if user else f"ID: {user_id}"
    finally:
        await conn.close()

# --- Клавиатуры ---
def get_main_menu_kb(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Отправить отчет"))
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    if is_admin:
        builder.add(types.KeyboardButton(text="👨‍💻 Администрирование"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    builder = ReplyKeyboardBuilder()
    for work in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work))
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📌 Поставить задачу"))
    builder.add(types.KeyboardButton(text="📋 Сводный отчет"))
    builder.add(types.KeyboardButton(text="👥 Управление пользователями"))
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_back_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    return builder.as_markup(resize_keyboard=True)

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = await create_db_connection()
    try:
        # Проверяем, зарегистрирован ли пользователь
        user = await conn.fetchrow(
            'SELECT is_active, is_admin FROM users WHERE user_id = $1', 
            message.from_user.id
        )
        
        if not user or not user['is_active']:
            await message.answer("⛔ Доступ запрещен. Обратитесь к администратору.")
            return
            
        is_admin = user['is_admin']
        
        # Обновляем информацию о пользователе
        await conn.execute('''
            INSERT INTO users (user_id, username, full_name, is_active)
            VALUES ($1, $2, $3, TRUE)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                full_name = EXCLUDED.full_name,
                is_active = TRUE
        ''', message.from_user.id, message.from_user.username, message.from_user.full_name)
        
        await message.answer(
            f"👋 Добро пожаловать, {message.from_user.full_name}!\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_kb(is_admin)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при старте: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")
    finally:
        await conn.close()

# ... [остальные обработчики]

# Запуск бота
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
