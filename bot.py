import os
import logging
import asyncio
import socket
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

async def create_db_connection():
    max_retries = 10  # Увеличиваем количество попыток
    retry_delay = 3   # Уменьшаем задержку между попытками
    
    for attempt in range(max_retries):
        try:
            host = os.getenv('PGHOST')
            port = int(os.getenv('PGPORT'))
            user = os.getenv('PGUSER')
            password = os.getenv('PGPASSWORD')
            database = os.getenv('PGDATABASE')
            
            # Преобразуем домен в IP
            try:
                host_ip = socket.gethostbyname(host)
                logger.info(f"Resolved {host} to {host_ip}")
            except socket.gaierror:
                host_ip = host
                logger.warning(f"Could not resolve hostname, using as-is: {host}")
            
            # Параметры подключения
            conn = await asyncpg.connect(
                host=host_ip,
                port=port,
                user=user,
                password=password,
                database=database,
                ssl='require',
                timeout=30,
                command_timeout=30
            )
            
            logger.info("Successfully connected to PostgreSQL")
            return conn
            
        except Exception as e:
            logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            raise

async def create_db_pool():
    try:
        pool = await asyncpg.create_pool(
            host=os.getenv('PGHOST'),
            port=int(os.getenv('PGPORT')),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            database=os.getenv('PGDATABASE'),
            ssl='require',
            min_size=1,
            max_size=3,
            timeout=30,
            command_timeout=30
        )
        
        # Проверка подключения
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
        
        return pool
    except Exception as e:
        logger.error(f"Failed to create connection pool: {str(e)}")
        # Fallback к одиночному подключению если пул не работает
        logger.info("Trying single connection instead of pool")
        conn = await create_db_connection()
        return conn

async def init_db():
    try:
        pool = await create_db_pool()
        
        if isinstance(pool, asyncpg.Connection):
            # Если у нас одиночное подключение вместо пула
            async with pool.transaction():
                await create_tables(pool)
            return pool
        else:
            # Если работает пул соединений
            async with pool.acquire() as conn:
                await create_tables(conn)
            return pool
            
    except Exception as e:
        logger.critical(f"Failed to initialize database: {str(e)}")
        raise

async def create_tables(conn):
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
    # [Остальные CREATE TABLE...]

async def on_startup(bot: Bot):
    try:
        logger.info("Starting bot initialization...")
        
        me = await bot.get_me()
        logger.info(f"Bot ready as @{me.username}")
        
        # Инициализация БД с повторными попытками
        max_db_attempts = 3
        for attempt in range(max_db_attempts):
            try:
                pool = await init_db()
                bot["pool"] = pool
                logger.info("Database initialized successfully")
                break
            except Exception as e:
                if attempt == max_db_attempts - 1:
                    raise
                logger.warning(f"DB init attempt {attempt + 1} failed, retrying...")
                await asyncio.sleep(5)
        
        logger.info("Bot started successfully")
    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}", exc_info=True)
        raise

async def on_shutdown(bot: Bot):
    try:
        logger.info("Shutting down...")
        if "pool" in bot.data:
            if isinstance(bot["pool"], asyncpg.pool.Pool):
                await bot["pool"].close()
            elif isinstance(bot["pool"], asyncpg.Connection):
                await bot["pool"].close()
            logger.info("Database connection closed")
        await (await bot.get_session()).close()
    except Exception as e:
        logger.error(f"Shutdown error: {str(e)}")
    finally:
        logger.info("Bot stopped")

async def main():
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot, 
                             handle_signals=False,
                             close_bot_session=True)
    except asyncio.CancelledError:
        logger.info("Polling cancelled")
    except Exception as e:
        logger.critical(f"Polling error: {str(e)}", exc_info=True)
    finally:
        logger.info("Process finished")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
