import os
import logging
import socket
import asyncio
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

# Увеличим уровень логирования для дебага
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.DEBUG)

# Загружаем переменные окружения
load_dotenv()

# Проверка обязательных переменных
REQUIRED_ENV_VARS = ['BOT_TOKEN', 'PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD', 'PGDATABASE']
for var in REQUIRED_ENV_VARS:
    if not os.getenv(var):
        logger.critical(f"Missing required environment variable: {var}")
        raise ValueError(f"Missing required environment variable: {var}")

# Инициализация бота
bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher()

# Состояния для FSM
class AdminStates(StatesGroup):
    WAITING_TASK_DESCRIPTION = State()
    WAITING_WORK_TYPE = State()
    WAITING_WORK_AMOUNT = State()
    WAITING_USER_SELECTION = State()

class UserStates(StatesGroup):
    WAITING_WORK_SELECTION = State()
    WAITING_COMPLETED_AMOUNT = State()

# Типы работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка", "Фрезеровка пазов ручек",
    "Распил на ручки"
]

# --- Database Functions with Retry Logic ---
async def create_db_pool():
    max_retries = 5
    retry_delay = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Получаем параметры подключения
            host = os.getenv('PGHOST')
            port = int(os.getenv('PGPORT'))
            user = os.getenv('PGUSER')
            password = os.getenv('PGPASSWORD')
            database = os.getenv('PGDATABASE')
            
            logger.info(f"Attempting DB connection (attempt {attempt + 1}/{max_retries})")
            
            # Увеличиваем таймауты для Railway
            pool = await asyncpg.create_pool(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                ssl='require',
                min_size=1,
                max_size=5,
                timeout=120,  # Увеличенный таймаут
                command_timeout=120,
                connection_timeout=60,
                server_settings={
                    'application_name': 'production_bot',
                    'statement_timeout': '30000'  # 30 секунд на запрос
                }
            )
            
            # Проверка подключения
            async with pool.acquire() as conn:
                await conn.execute("SELECT 1")
                logger.info("Database connection test successful")
            
            return pool
            
        except (asyncio.TimeoutError, asyncpg.CannotConnectNowError, ConnectionRefusedError) as e:
            last_error = e
            logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            raise
        except Exception as e:
            last_error = e
            logger.error(f"Unexpected DB connection error: {str(e)}")
            raise
    
    raise ConnectionError(f"Failed to connect after {max_retries} attempts. Last error: {str(last_error)}")

async def init_db():
    try:
        pool = await create_db_pool()
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS weekly_tasks (
                    task_id SERIAL PRIMARY KEY,
                    description TEXT,
                    week_start DATE,
                    week_end DATE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    created_by BIGINT REFERENCES users(user_id),
                    is_active BOOLEAN DEFAULT TRUE
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS work_plans (
                    plan_id SERIAL PRIMARY KEY,
                    task_id INTEGER REFERENCES weekly_tasks(task_id),
                    work_type TEXT,
                    total_amount INTEGER,
                    assigned_amount INTEGER DEFAULT 0,
                    completed_amount INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_work (
                    record_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    plan_id INTEGER REFERENCES work_plans(plan_id),
                    date DATE,
                    amount INTEGER,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            
            # Создаем индексы для улучшения производительности
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_work_user_id ON user_work(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_work_plan_id ON user_work(plan_id)
            ''')
            
        logger.info("Database initialized successfully")
        return pool
        
    except Exception as e:
        logger.critical(f"Failed to initialize database: {str(e)}")
        raise

# --- Helper Functions ---
def get_current_week_dates():
    today = datetime.now().date()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end

def format_week_range(start_date):
    return f"{start_date.strftime('%d.%m')}-{(start_date + timedelta(days=6)).strftime('%d.%m.%Y')}"

async def delete_previous_message(message: types.Message):
    try:
        await message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

# --- Keyboards ---
def get_main_menu_kb(is_admin: bool = False):
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📊 Мои отчеты"))
    builder.add(types.KeyboardButton(text="📝 Отправить отчет"))
    if is_admin:
        builder.add(types.KeyboardButton(text="👨‍💻 Администрирование"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_work_types_kb():
    builder = ReplyKeyboardBuilder()
    for work_type in WORK_TYPES:
        builder.add(types.KeyboardButton(text=work_type))
    builder.add(types.KeyboardButton(text="🔙 Назад"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def get_admin_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="📌 Поставить задачу"))
    builder.add(types.KeyboardButton(text="📊 Сводный отчет"))
    builder.add(types.KeyboardButton(text="👥 Управление пользователями"))
    builder.add(types.KeyboardButton(text="🔙 Главное меню"))
    builder.adjust(2)
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
    builder.adjust(2)
    return builder.as_markup()

# --- Command Handlers ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                message.from_user.id
            )
            
            if not user:
                await conn.execute(
                    "INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3)",
                    message.from_user.id,
                    message.from_user.username,
                    message.from_user.full_name
                )
                await message.answer(
                    "👋 Добро пожаловать! Ожидайте подтверждения регистрации администратором."
                )
                return
            
            if not user['is_active']:
                await message.answer("⛔ Ваш аккаунт деактивирован. Обратитесь к администратору.")
                return
        
        await message.answer(
            "🏠 Главное меню",
            reply_markup=get_main_menu_kb(user['is_admin'])
        )
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")
        await message.answer("⚠️ Произошла ошибка при подключении к базе данных. Попробуйте позже.")

@dp.message(F.text == "🔙 Главное меню")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT is_admin FROM users WHERE user_id = $1 AND is_active = TRUE",
                message.from_user.id
            )
            
            if not user:
                return
                
        await message.answer(
            "🏠 Главное меню",
            reply_markup=get_main_menu_kb(user['is_admin'])
        )
    except Exception as e:
        logger.error(f"Error in back_to_main: {e}")
        await message.answer("⚠️ Произошла ошибка при подключении к базе данных.")

# --- Admin Handlers ---
@dp.message(F.text == "👨‍💻 Администрирование")
async def admin_menu(message: types.Message, state: FSMContext):
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            is_admin = await conn.fetchval(
                "SELECT is_admin FROM users WHERE user_id = $1",
                message.from_user.id
            )
            
            if not is_admin:
                return
                
        await message.answer(
            "👨‍💻 Меню администратора",
            reply_markup=get_admin_menu_kb()
        )
    except Exception as e:
        logger.error(f"Error in admin_menu: {e}")
        await message.answer("⚠️ Произошла ошибка при подключении к базе данных.")

@dp.message(F.text == "📌 Поставить задачу")
async def set_task_start(message: types.Message, state: FSMContext):
    await state.set_state(AdminStates.WAITING_TASK_DESCRIPTION)
    await message.answer(
        "📝 Введите описание задачи на неделю:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(AdminStates.WAITING_TASK_DESCRIPTION)
async def set_task_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AdminStates.WAITING_WORK_TYPE)
    await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )

@dp.message(AdminStates.WAITING_WORK_TYPE, F.text.in_(WORK_TYPES))
async def set_work_type(message: types.Message, state: FSMContext):
    await state.update_data(work_type=message.text)
    await state.set_state(AdminStates.WAITING_WORK_AMOUNT)
    await message.answer(
        "Введите общее количество для этой работы:",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(AdminStates.WAITING_WORK_AMOUNT)
async def set_work_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите положительное целое число")
        return
    
    data = await state.get_data()
    week_start, week_end = get_current_week_dates()
    
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            # Создаем или получаем задачу на неделю
            task_id = await conn.fetchval(
                "INSERT INTO weekly_tasks (description, week_start, week_end, created_by) "
                "VALUES ($1, $2, $3, $4) RETURNING task_id",
                data['description'], week_start, week_end, message.from_user.id
            )
            
            # Добавляем план работы
            await conn.execute(
                "INSERT INTO work_plans (task_id, work_type, total_amount) "
                "VALUES ($1, $2, $3)",
                task_id, data['work_type'], amount
            )
        
        await state.clear()
        await message.answer(
            f"✅ Задача добавлена!\n\n"
            f"📅 Неделя: {format_week_range(week_start)}\n"
            f"📝 Описание: {data['description']}\n"
            f"🔧 Вид работы: {data['work_type']}\n"
            f"📊 Количество: {amount}",
            reply_markup=get_admin_menu_kb()
        )
    except Exception as e:
        logger.error(f"Error in set_work_amount: {e}")
        await message.answer("⚠️ Произошла ошибка при сохранении задачи в базу данных.")

# --- User Work Reporting ---
@dp.message(F.text == "📝 Отправить отчет")
async def start_report(message: types.Message, state: FSMContext):
    week_start, week_end = get_current_week_dates()
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            works = await conn.fetch(
                "SELECT wp.plan_id, wp.work_type, wp.total_amount, wp.assigned_amount, wp.completed_amount "
                "FROM work_plans wp "
                "JOIN weekly_tasks wt ON wp.task_id = wt.task_id "
                "WHERE wt.week_start = $1 AND wt.week_end = $2 AND wt.is_active = TRUE",
                week_start, week_end
            )
            
            if not works:
                await message.answer("Нет активных задач на текущую неделю")
                return
                
        builder = InlineKeyboardBuilder()
        for work in works:
            builder.add(types.InlineKeyboardButton(
                text=f"{work['work_type']} ({work['completed_amount']}/{work['total_amount']})",
                callback_data=f"select_work_{work['plan_id']}"
            ))
        builder.adjust(1)
        
        await state.set_state(UserStates.WAITING_WORK_SELECTION)
        await message.answer(
            "Выберите вид работы для отчета:",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        logger.error(f"Error in start_report: {e}")
        await message.answer("⚠️ Произошла ошибка при получении списка задач.")

@dp.callback_query(F.data.startswith("select_work_"), UserStates.WAITING_WORK_SELECTION)
async def select_work_for_report(callback: types.CallbackQuery, state: FSMContext):
    plan_id = int(callback.data.split("_")[2])
    await state.update_data(plan_id=plan_id)
    await state.set_state(UserStates.WAITING_COMPLETED_AMOUNT)
    await callback.message.answer(
        "Введите количество выполненной работы:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    await callback.answer()

@dp.message(UserStates.WAITING_COMPLETED_AMOUNT)
async def save_work_report(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите положительное целое число")
        return
    
    data = await state.get_data()
    
    try:
        pool = message.bot.get("pool")
        
        async with pool.acquire() as conn:
            # Проверяем, не превышает ли выполненное количество общее
            work = await conn.fetchrow(
                "SELECT total_amount, completed_amount FROM work_plans WHERE plan_id = $1",
                data['plan_id']
            )
            
            if work['completed_amount'] + amount > work['total_amount']:
                await message.answer(
                    f"Ошибка: общее выполнение превысит плановое количество ({work['total_amount']})"
                )
                return
            
            # Сохраняем отчет
            await conn.execute(
                "INSERT INTO user_work (user_id, plan_id, date, amount) "
                "VALUES ($1, $2, $3, $4)",
                message.from_user.id, data['plan_id'], datetime.now().date(), amount
            )
            
            # Обновляем счетчики
            await conn.execute(
                "UPDATE work_plans SET "
                "completed_amount = completed_amount + $1, "
                "assigned_amount = assigned_amount + $1 "
                "WHERE plan_id = $2",
                amount, data['plan_id']
            )
            
            # Получаем информацию для отчета
            work_info = await conn.fetchrow(
                "SELECT wp.work_type, wt.description FROM work_plans wp "
                "JOIN weekly_tasks wt ON wp.task_id = wt.task_id "
                "WHERE wp.plan_id = $1",
                data['plan_id']
            )
        
        await state.clear()
        await message.answer(
            f"✅ Отчет сохранен!\n\n"
            f"📝 Задача: {work_info['description']}\n"
            f"🔧 Вид работы: {work_info['work_type']}\n"
            f"📊 Выполнено: {amount}",
            reply_markup=get_main_menu_kb()
        )
    except Exception as e:
        logger.error(f"Error in save_work_report: {e}")
        await message.answer("⚠️ Произошла ошибка при сохранении отчета.")

# --- Admin Reports ---
@dp.message(F.text == "📊 Сводный отчет")
async def generate_admin_report(message: types.Message):
    week_start, week_end = get_current_week_dates()
    
    try:
        pool = message.bot.get("pool")
        
        async with pool.acquire() as conn:
            # Проверяем права администратора
            is_admin = await conn.fetchval(
                "SELECT is_admin FROM users WHERE user_id = $1",
                message.from_user.id
            )
            if not is_admin:
                return
            
            # Получаем сводный отчет
            report = await conn.fetch(
                "SELECT u.full_name, wp.work_type, SUM(uw.amount) as completed, wp.total_amount "
                "FROM user_work uw "
                "JOIN users u ON uw.user_id = u.user_id "
                "JOIN work_plans wp ON uw.plan_id = wp.plan_id "
                "JOIN weekly_tasks wt ON wp.task_id = wt.task_id "
                "WHERE wt.week_start = $1 AND wt.week_end = $2 "
                "GROUP BY u.full_name, wp.work_type, wp.total_amount "
                "ORDER BY u.full_name, wp.work_type",
                week_start, week_end
            )
            
            if not report:
                await message.answer("Нет данных за текущую неделю")
                return
            
            # Формируем сообщение
            current_user = None
            message_text = f"📊 Сводный отчет за неделю {format_week_range(week_start)}\n\n"
            
            for row in report:
                if row['full_name'] != current_user:
                    message_text += f"\n👤 <b>{row['full_name']}</b>\n"
                    current_user = row['full_name']
                
                percentage = (row['completed'] / row['total_amount']) * 100
                message_text += (
                    f"  🔧 {row['work_type']}: {row['completed']}/{row['total_amount']} "
                    f"({percentage:.1f}%)\n"
                )
        
        await message.answer(message_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in generate_admin_report: {e}")
        await message.answer("⚠️ Произошла ошибка при формировании отчета.")

# --- User Management ---
@dp.message(F.text == "👥 Управление пользователями")
async def user_management(message: types.Message):
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            is_admin = await conn.fetchval(
                "SELECT is_admin FROM users WHERE user_id = $1",
                message.from_user.id
            )
            
            if not is_admin:
                return
        
        await message.answer(
            "👥 Управление пользователями",
            reply_markup=get_user_management_kb()
        )
    except Exception as e:
        logger.error(f"Error in user_management: {e}")
        await message.answer("⚠️ Произошла ошибка при подключении к базе данных.")

# --- Bot Setup with Health Checks ---
async def on_startup(bot: Bot):
    try:
        logger.info("Starting bot initialization...")
        
        # Проверка токена бота
        me = await bot.get_me()
        logger.info(f"Bot authorized as @{me.username} (ID: {me.id})")
        
        # Инициализация базы данных с повторными попытками
        pool = await init_db()
        bot["pool"] = pool
        logger.info("Database pool initialized successfully")
        
        # Дополнительная проверка соединения
        async with pool.acquire() as conn:
            db_time = await conn.fetchval("SELECT NOW()")
            logger.info(f"Database time check: {db_time}")
        
        logger.info("Bot started successfully")
        
    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}", exc_info=True)
        raise

async def on_shutdown(bot: Bot):
    try:
        logger.info("Shutting down bot...")
        
        # Корректное закрытие соединений
        if "pool" in bot.data:
            pool = bot["pool"]
            await pool.close()
            logger.info("Database pool closed")
            
        await bot.session.close()
        logger.info("HTTP session closed")
        
    except Exception as e:
        logger.error(f"Shutdown error: {str(e)}")
    finally:
        logger.info("Bot stopped")

# --- Health Check Command ---
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    try:
        pool = message.bot.get("pool")
        async with pool.acquire() as conn:
            db_time = await conn.fetchval("SELECT NOW()")
            await message.answer(f"✅ Bot is alive\nDatabase time: {db_time}")
    except Exception as e:
        await message.answer(f"❌ Database error: {str(e)}")

# --- Main Polling with Error Handling ---
async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot, 
                             handle_signals=False,
                             close_bot_session=True,
                             allowed_updates=types.Update.ALL_TYPES)
    except asyncio.CancelledError:
        logger.info("Polling cancelled gracefully")
    except Exception as e:
        logger.critical(f"Polling error: {str(e)}", exc_info=True)
    finally:
        logger.info("Bot process finished")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
