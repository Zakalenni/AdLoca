import os
import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Tuple

import psycopg2
from psycopg2 import sql
from psycopg2.extras import DictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы для состояний ConversationHandler
SETTING_TASK, SETTING_WORK_TYPE, SETTING_AMOUNT = range(3)
REPORTING_WORK_TYPE, REPORTING_AMOUNT, REPORTING_ADDITIONAL = range(3)
ADMIN_ADD_USER, ADMIN_REMOVE_USER = range(2)

# Виды работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка",
    "Фрезеровка пазов ручек", "Распил на ручки"
]

# Подключение к PostgreSQL
def get_db_connection():
    db_url = os.getenv('DATABASE_URL')
    if db_url:
        return psycopg2.connect(db_url, sslmode='require')
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        dbname=os.getenv('DB_NAME'),
        sslmode='require'
    )

# Инициализация базы данных
def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Таблица пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    registered_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица задач
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id SERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    total_amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    created_by BIGINT REFERENCES users(user_id),
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            # Таблица распределения работ
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_assignments (
                    assignment_id SERIAL PRIMARY KEY,
                    task_id INTEGER REFERENCES tasks(task_id),
                    work_type TEXT NOT NULL,
                    day_of_week INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    assigned_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица отчетов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    report_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    task_id INTEGER REFERENCES tasks(task_id),
                    work_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    report_date DATE NOT NULL,
                    reported_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Таблица разрешенных пользователей
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS allowed_users (
                    user_id BIGINT PRIMARY KEY
                )
            """)
            
            conn.commit()

# Проверка прав администратора
def is_admin(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT is_admin FROM users WHERE user_id = %s", 
                    (user_id,)
                )
                result = cursor.fetchone()
                return result and result[0]
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# Регистрация пользователя
def register_user(user_id: int, username: str, first_name: str, last_name: str):
    full_name = f"{first_name} {last_name}".strip()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO users (user_id, username, full_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        full_name = EXCLUDED.full_name
                """, (user_id, username, full_name))
                conn.commit()
    except Exception as e:
        logger.error(f"Error registering user: {e}")

# Команда /start
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    
    if not is_user_allowed(user.id):
        update.message.reply_text("⛔ Доступ запрещен. Обратитесь к администратору.")
        return
    
    show_main_menu(update, context)

def show_main_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    keyboard = [
        [InlineKeyboardButton("📊 Отправить отчет", callback_data='send_report')],
        [InlineKeyboardButton("📋 Посмотреть задачи", callback_data='view_tasks')]
    ]
    
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("👨‍💻 Админ-панель", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text="Главное меню. Выберите действие:",
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            "Главное меню. Выберите действие:",
            reply_markup=reply_markup
        )

# Админ-панель
def admin_panel(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📝 Поставить задачу", callback_data='set_task')],
        [InlineKeyboardButton("📊 Посмотреть отчеты", callback_data='view_reports')],
        [InlineKeyboardButton("👥 Управление пользователями", callback_data='manage_users')],
        [InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]
    ]
    
    query.edit_message_text(
        text="Админ-панель. Выберите действие:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Управление пользователями
def manage_users(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data='add_user')],
        [InlineKeyboardButton("➖ Удалить пользователя", callback_data='remove_user')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(
        text="Управление пользователями:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Добавление пользователя
def add_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите ID пользователя, которого хотите добавить:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ADMIN_ADD_USER

def add_user_handler(update: Update, context: CallbackContext) -> int:
    try:
        user_id = int(update.message.text.strip())
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO allowed_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", 
                    (user_id,)
                )
                conn.commit()
        
        update.message.reply_text(
            f"✅ Пользователь {user_id} добавлен в список разрешенных.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ADMIN_ADD_USER

# Удаление пользователя
def remove_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите ID пользователя, которого хотите удалить:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ADMIN_REMOVE_USER

def remove_user_handler(update: Update, context: CallbackContext) -> int:
    try:
        user_id = int(update.message.text.strip())
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM allowed_users WHERE user_id = %s", 
                    (user_id,)
                )
                conn.commit()
        
        update.message.reply_text(
            f"✅ Пользователь {user_id} удален из списка разрешенных.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ADMIN_REMOVE_USER

# Постановка задачи
def set_task(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите описание задачи и общее количество в формате: 'Описание задачи - 100'",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
    )
    return SETTING_TASK

def set_task_description(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    try:
        description, amount = text.rsplit('-', 1)
        description = description.strip()
        amount = int(amount.strip())
        
        context.user_data['task_description'] = description
        context.user_data['total_amount'] = amount
        
        # Создаем задачу в базе данных
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (description, total_amount, created_by) VALUES (%s, %s, %s) RETURNING task_id",
                    (description, amount, update.message.from_user.id)
                )
                task_id = cursor.fetchone()[0]
                conn.commit()
        
        context.user_data['task_id'] = task_id
        
        # Кнопки для выбора дня недели
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        keyboard = [
            [InlineKeyboardButton(day, callback_data=f'day_{i}')] for i, day in enumerate(days)
        ]
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')])
        
        update.message.reply_text(
            "Выберите день недели для распределения работ:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SETTING_WORK_TYPE
    except Exception as e:
        logger.error(f"Error setting task: {e}")
        update.message.reply_text(
            "❌ Неверный формат. Введите в формате: 'Описание задачи - 100'",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
        return SETTING_TASK

def set_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    day_of_week = int(query.data.split('_')[1])
    context.user_data['day_of_week'] = day_of_week
    
    # Кнопки для выбора вида работы
    keyboard = []
    for i in range(0, len(WORK_TYPES), 2):
        row = []
        if i < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i], callback_data=f'work_{i}'))
        if i+1 < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i+1], callback_data=f'work_{i+1}'))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')])
    
    query.edit_message_text(
        text="Выберите вид работы:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SETTING_AMOUNT

def set_work_amount(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[1])
    work_type = WORK_TYPES[work_type_idx]
    context.user_data['work_type'] = work_type
    
    query.edit_message_text(
        text=f"Введите количество для работы '{work_type}':",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'day_{context.user_data["day_of_week"]}')]])
    )
    return SETTING_AMOUNT

def save_work_assignment(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text)
        task_id = context.user_data['task_id']
        day_of_week = context.user_data['day_of_week']
        work_type = context.user_data['work_type']
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO task_assignments (task_id, work_type, day_of_week, amount) VALUES (%s, %s, %s, %s)",
                    (task_id, work_type, day_of_week, amount)
                )
                conn.commit()
        
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        update.message.reply_text(
            f"✅ Работа '{work_type}' на {days[day_of_week]} в количестве {amount} успешно добавлена!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое число.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'day_{context.user_data["day_of_week"]}')]])
        )
        return SETTING_AMOUNT

# Просмотр задач
def view_tasks(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT t.task_id, t.description, t.total_amount, 
                           COALESCE(SUM(r.amount), 0) AS completed
                    FROM tasks t
                    LEFT JOIN reports r ON t.task_id = r.task_id
                    WHERE t.is_active = TRUE
                    GROUP BY t.task_id
                    ORDER BY t.created_at DESC
                """)
                tasks = cursor.fetchall()
        
        if not tasks:
            query.edit_message_text(
                text="ℹ️ Нет активных задач.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
            )
            return
        
        message = "📋 Список активных задач:\n\n"
        for task in tasks:
            progress = (task[3] / task[2]) * 100 if task[2] > 0 else 0
            message += (
                f"🔹 {task[1]}\n"
                f"📌 Всего: {task[2]}\n"
                f"✅ Выполнено: {task[3]}\n"
                f"📊 Прогресс: {progress:.1f}%\n\n"
            )
        
        query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
    except Exception as e:
        logger.error(f"Error viewing tasks: {e}")
        query.edit_message_text(
            text="❌ Ошибка при получении списка задач.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )

# Просмотр отчетов
def view_reports(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT r.report_id, u.full_name, t.description, 
                           r.work_type, r.amount, r.report_date
                    FROM reports r
                    JOIN users u ON r.user_id = u.user_id
                    JOIN tasks t ON r.task_id = t.task_id
                    ORDER BY r.report_date DESC, r.reported_at DESC
                    LIMIT 20
                """)
                reports = cursor.fetchall()
        
        if not reports:
            query.edit_message_text(
                text="ℹ️ Нет отчетов для отображения.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
            )
            return
        
        message = "📊 Последние отчеты:\n\n"
        for report in reports:
            message += (
                f"👤 {report[1]}\n"
                f"📅 {report[5].strftime('%d.%m.%Y')}\n"
                f"📌 Задача: {report[2]}\n"
                f"🔧 Работа: {report[3]}\n"
                f"🔢 Количество: {report[4]}\n\n"
            )
        
        query.edit_message_text(
            text=message,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
    except Exception as e:
        logger.error(f"Error viewing reports: {e}")
        query.edit_message_text(
            text="❌ Ошибка при получении отчетов.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )

# Отправка отчета
def send_report(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT task_id, description 
                    FROM tasks 
                    WHERE is_active = TRUE 
                    ORDER BY created_at DESC
                """)
                tasks = cursor.fetchall()
        
        if not tasks:
            query.edit_message_text(
                text="ℹ️ Нет активных задач для отчета.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
            )
            return ConversationHandler.END
        
        keyboard = []
        for task in tasks:
            keyboard.append([InlineKeyboardButton(task[1], callback_data=f'task_{task[0]}')])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
        
        query.edit_message_text(
            text="Выберите задачу для отчета:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REPORTING_WORK_TYPE
    except Exception as e:
        logger.error(f"Error starting report: {e}")
        query.edit_message_text(
            text="❌ Ошибка при получении списка задач.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
        return ConversationHandler.END

def report_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    task_id = int(query.data.split('_')[1])
    context.user_data['report_task_id'] = task_id
    
    # Кнопки для выбора вида работы
    keyboard = []
    for i in range(0, len(WORK_TYPES), 2):
        row = []
        if i < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i], callback_data=f'report_work_{i}'))
        if i+1 < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i+1], callback_data=f'report_work_{i+1}'))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='send_report')])
    
    query.edit_message_text(
        text="Выберите вид работы:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REPORTING_AMOUNT

def report_amount(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[2])
    work_type = WORK_TYPES[work_type_idx]
    context.user_data['report_work_type'] = work_type
    
    query.edit_message_text(
        text=f"Введите количество выполненной работы '{work_type}':",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'task_{context.user_data["report_task_id"]}')]])
    )
    return REPORTING_ADDITIONAL

def save_report(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text)
        task_id = context.user_data['report_task_id']
        work_type = context.user_data['report_work_type']
        user_id = update.message.from_user.id
        report_date = datetime.now().date()
        
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO reports (user_id, task_id, work_type, amount, report_date) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, task_id, work_type, amount, report_date)
                )
                conn.commit()
        
        keyboard = [
            [InlineKeyboardButton("➕ Добавить еще работу", callback_data=f'task_{task_id}')],
            [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
        ]
        
        update.message.reply_text(
            f"✅ Отчет по работе '{work_type}' в количестве {amount} успешно сохранен!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое число.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'task_{context.user_data["report_task_id"]}')]])
        )
        return REPORTING_AMOUNT

# Проверка разрешенного пользователя
def is_user_allowed(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM allowed_users WHERE user_id = %s", 
                    (user_id,)
                )
                return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Error checking allowed user: {e}")
        return False

# Удаление старых сообщений
def delete_old_messages(context: CallbackContext):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM reports WHERE reported_at < NOW() - INTERVAL '7 days'"
                )
                conn.commit()
        logger.info("Old messages deleted successfully")
    except Exception as e:
        logger.error(f"Error deleting old messages: {e}")

# Обработчик ошибок
def error_handler(update: Update, context: CallbackContext):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text="⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
    else:
        update.message.reply_text(
            "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )

def main() -> None:
    # Инициализация базы данных
    init_db()
    
    # Создание Updater
    token = os.getenv('TELEGRAM_TOKEN')
    updater = Updater(token, use_context=True)
    
    # Получаем диспетчер
    dispatcher = updater.dispatcher
    
    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    
    # Обработчики callback-запросов
    dispatcher.add_handler(CallbackQueryHandler(show_main_menu, pattern='^main_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_panel, pattern='^admin_panel$'))
    dispatcher.add_handler(CallbackQueryHandler(manage_users, pattern='^manage_users$'))
    dispatcher.add_handler(CallbackQueryHandler(view_tasks, pattern='^view_tasks$'))
    dispatcher.add_handler(CallbackQueryHandler(view_reports, pattern='^view_reports$'))
    dispatcher.add_handler(CallbackQueryHandler(send_report, pattern='^send_report$'))
    dispatcher.add_handler(CallbackQueryHandler(set_task, pattern='^set_task$'))
    dispatcher.add_handler(CallbackQueryHandler(add_user, pattern='^add_user$'))
    dispatcher.add_handler(CallbackQueryHandler(remove_user, pattern='^remove_user$'))
    
    # ConversationHandler для админских функций
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(set_task, pattern='^set_task$'),
            CallbackQueryHandler(add_user, pattern='^add_user$'),
            CallbackQueryHandler(remove_user, pattern='^remove_user$')
        ],
        states={
            SETTING_TASK: [MessageHandler(Filters.text & ~Filters.command, set_task_description)],
            SETTING_WORK_TYPE: [CallbackQueryHandler(set_work_type, pattern='^day_[0-6]$')],
            SETTING_AMOUNT: [
                CallbackQueryHandler(set_work_amount, pattern='^work_[0-9]+$'),
                MessageHandler(Filters.text & ~Filters.command, save_work_assignment)
            ],
            ADMIN_ADD_USER: [MessageHandler(Filters.text & ~Filters.command, add_user_handler)],
            ADMIN_REMOVE_USER: [MessageHandler(Filters.text & ~Filters.command, remove_user_handler)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
            CallbackQueryHandler(manage_users, pattern='^manage_users$')
        ],
        per_message=True
    )
    dispatcher.add_handler(admin_conv_handler)
    
    # ConversationHandler для отправки отчетов
    report_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_report, pattern='^send_report$')],
        states={
            REPORTING_WORK_TYPE: [CallbackQueryHandler(report_work_type, pattern='^task_[0-9]+$')],
            REPORTING_AMOUNT: [CallbackQueryHandler(report_amount, pattern='^report_work_[0-9]+$')],
            REPORTING_ADDITIONAL: [MessageHandler(Filters.text & ~Filters.command, save_report)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(show_main_menu, pattern='^main_menu$')
        ],
        per_message=True
    )
    dispatcher.add_handler(report_conv_handler)
    
    # Обработчик ошибок
    dispatcher.add_error_handler(error_handler)
    
    # Планировщик для удаления старых сообщений
    job_queue = updater.job_queue
    job_queue.run_daily(delete_old_messages, time=time(hour=3, minute=0))
    
    # Запуск бота
    updater.start_polling(drop_pending_updates=True)
    updater.idle()

if __name__ == '__main__':
    main()
