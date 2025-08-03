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

async def create_db_pool():
    max_retries = 5
    retry_delay = 5
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Параметры подключения
            params = {
                'host': os.getenv('PGHOST'),
                'port': int(os.getenv('PGPORT')),
                'user': os.getenv('PGUSER'),
                'password': os.getenv('PGPASSWORD'),
                'database': os.getenv('PGDATABASE'),
                'ssl': 'require',
                'min_size': 1,
                'max_size': 3,
                'timeout': 60,
                'command_timeout': 60
            }

            logger.info(f"Connection attempt {attempt + 1}/{max_retries} to {params['host']}:{params['port']}")

            # Пробуем преобразовать хост в IP
            try:
                params['host'] = socket.gethostbyname(params['host'])
                logger.info(f"Resolved host to IP: {params['host']}")
            except socket.gaierror:
                logger.warning("Could not resolve hostname, using as-is")

            pool = await asyncpg.create_pool(**params)
            
            # Проверка подключения
            async with pool.acquire() as conn:
                db_time = await conn.fetchval("SELECT NOW()")
                logger.info(f"Database connection successful. Server time: {db_time}")
            
            return pool
            
        except (asyncio.TimeoutError, asyncpg.CannotConnectNowError) as e:
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
            
            # Индексы для производительности
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_work_user_id ON user_work(user_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_user_work_plan_id ON user_work(plan_id)
            ''')
            
        logger.info("Database tables initialized")
        return pool
        
    except Exception as e:
        logger.critical(f"Database initialization failed: {str(e)}")
        raise

# [Все остальные функции (хелперы, клавиатуры, обработчики) остаются без изменений]

async def on_startup(bot: Bot):
    try:
        logger.info("Starting bot initialization...")
        
        me = await bot.get_me()
        logger.info(f"Bot authorized as @{me.username} (ID: {me.id})")
        
        pool = await init_db()
        bot["pool"] = pool
        logger.info("Database pool initialized successfully")
        
        # Дополнительная проверка соединения
        async with pool.acquire() as conn:
            db_time = await conn.fetchval("SELECT NOW()")
            logger.info(f"Database connection verified. Server time: {db_time}")
        
        logger.info("Bot startup completed")
        
    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}", exc_info=True)
        raise

async def on_shutdown(bot: Bot):
    try:
        logger.info("Starting shutdown process...")
        
        if "pool" in bot.data:
            await bot["pool"].close()
            logger.info("Database pool closed")
            
        await bot.session.close()
        logger.info("Bot session closed")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")
    finally:
        logger.info("Shutdown completed")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        logger.info("Starting polling...")
        await dp.start_polling(
            bot,
            handle_signals=False,
            close_bot_session=True
        )
    except asyncio.CancelledError:
        logger.info("Polling cancelled by signal")
    except Exception as e:
        logger.critical(f"Polling error: {str(e)}", exc_info=True)
    finally:
        logger.info("Polling stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
