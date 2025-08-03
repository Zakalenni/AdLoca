import os
import logging
import ssl
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv
import asyncpg
from typing import Dict, List, Optional

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
dp = Dispatcher()

# Состояния для FSM
class AdminStates(StatesGroup):
    WAITING_TASK_DESCRIPTION = State()
    WAITING_WORK_TYPE = State()
    WAITING_QUANTITY = State()
    WAITING_USER_MANAGEMENT = State()

class UserStates(StatesGroup):
    WAITING_WORK_SELECTION = State()
    WAITING_QUANTITY_DONE = State()

# Типы работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка", "Фрезеровка пазов ручек",
    "Распил на ручки"
]

# Подключение к PostgreSQL с SSL
async def create_db_connection():
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    return await asyncpg.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        ssl=ssl_ctx
    )

# Инициализация базы данных
async def init_db():
    conn = await create_db_connection()
    try:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                is_admin BOOLEAN DEFAULT FALSE
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS weekly_tasks (
                task_id SERIAL PRIMARY KEY,
                admin_id BIGINT,
                description TEXT,
                total_quantity INTEGER,
                created_at TIMESTAMP DEFAULT NOW(),
                week_number INTEGER,
                year INTEGER
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS work_types (
                work_type_id SERIAL PRIMARY KEY,
                name TEXT UNIQUE
            )
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_reports (
                report_id SERIAL PRIMARY KEY,
                user_id BIGINT,
                task_id INTEGER REFERENCES weekly_tasks(task_id),
                work_type_id INTEGER REFERENCES work_types(work_type_id),
                quantity_done INTEGER,
                report_date DATE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')

        # Добавляем типы работ, если их нет
        for work_type in WORK_TYPES:
            await conn.execute('''
                INSERT INTO work_types (name)
                VALUES ($1)
                ON CONFLICT (name) DO NOTHING
            ''', work_type)

    finally:
        await conn.close()

# --- Вспомогательные функции ---
async def get_current_week() -> tuple:
    today = datetime.now()
    year, week_num, _ = today.isocalendar()
    return week_num, year

async def get_week_dates(week_num: int, year: int) -> str:
    first_day = datetime.fromisocalendar(year, week_num, 1)
    last_day = datetime.fromisocalendar(year, week_num, 7)
    return f"{first_day.strftime('%d.%m')}-{last_day.strftime('%d.%m.%Y')}"

async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Ошибка удаления сообщения: {e}")

async def get_user_name(user_id: int) -> str:
    conn = await create_db_connection()
    try:
        user = await conn.fetchrow('SELECT full_name FROM users WHERE user_id = $1', user_id)
        return user['full_name'] if user else f"ID{user_id}"
    finally:
        await conn.close()

# --- Клавиатуры ---
def get_main_menu_kb(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📊 Отправить отчет"))
    builder.add(types.KeyboardButton(text="📋 Мои отчеты"))
    if is_admin:
        builder.add(types.KeyboardButton(text="👨‍💻 Администрирование"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📝 Поставить задачу"))
    builder.add(types.KeyboardButton(text="📈 Сводный отчет"))
    builder.add(types.KeyboardButton(text="👥 Управление пользователями"))
    builder.add(types.KeyboardButton(text="🔙 Главное меню"))
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    builder = ReplyKeyboardBuilder()
    for work_type in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work_type))
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_back_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    return builder.as_markup(resize_keyboard=True)

def get_user_management_kb():
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="Добавить пользователя",
        callback_data="admin_add_user"
    ))
    builder.add(types.InlineKeyboardButton(
        text="Удалить пользователя",
        callback_data="admin_remove_user"
    ))
    builder.add(types.InlineKeyboardButton(
        text="Назначить админа",
        callback_data="admin_promote"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="admin_back"
    ))
    builder.adjust(1)
    return builder.as_markup()

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = await create_db_connection()
    try:
        # Проверяем, есть ли пользователь в базе
        user = await conn.fetchrow(
            'SELECT * FROM users WHERE user_id = $1', 
            message.from_user.id
        )
        
        if not user:
            # Добавляем нового пользователя (неактивного по умолчанию)
            await conn.execute(
                '''
                INSERT INTO users (user_id, username, full_name, is_active)
                VALUES ($1, $2, $3, FALSE)
                ''',
                message.from_user.id,
                message.from_user.username,
                message.from_user.full_name
            )
            await message.answer(
                "👋 Добро пожаловать! Ваш аккаунт отправлен на активацию администратору."
            )
            # Уведомляем администратора
            admin_id = os.getenv('ADMIN_ID')
            if admin_id:
                await bot.send_message(
                    admin_id,
                    f"🆕 Новый пользователь:\n"
                    f"ID: {message.from_user.id}\n"
                    f"Имя: {message.from_user.full_name}\n"
                    f"Username: @{message.from_user.username}\n\n"
                    f"Используйте панель администрирования для активации."
                )
            return
        
        if not user['is_active']:
            await message.answer("⏳ Ваш аккаунт еще не активирован. Ожидайте подтверждения администратора.")
            return
        
        is_admin = user['is_admin']
        await message.answer(
            "📋 <b>Главное меню</b>\n\n"
            "Выберите действие:",
            reply_markup=get_main_menu_kb(is_admin),
            parse_mode="HTML"
        )
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
