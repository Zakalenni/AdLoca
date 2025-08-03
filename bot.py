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
ADDING_WORK_TYPES, SETTING_WORK_AMOUNT, CONFIRM_TASK = range(3)
REPORTING_WORK_TYPE, REPORTING_AMOUNT = range(2)
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    registered_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT NOW(),
                    created_by BIGINT REFERENCES users(user_id),
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_works (
                    work_id SERIAL PRIMARY KEY,
                    task_id INTEGER REFERENCES tasks(task_id),
                    work_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    report_id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    task_id INTEGER,
                    work_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    report_date DATE NOT NULL,
                    reported_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
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
        update.callback_query.answer()
    else:
        update.message.reply_text(
            "Главное меню. Выберите действие:",
            reply_markup=reply_markup
        )

# Отмена действий
def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена текущего действия и возврат в главное меню"""
    try:
        if update.message:
            update.message.reply_text(
                "Действие отменено",
                reply_markup=ReplyKeyboardRemove()
            )
        elif update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(
                text="Действие отменено",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]]
                )
            )
        show_main_menu(update, context)
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel function: {e}")
        return ConversationHandler.END

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

# Постановка задачи - начало
def set_task(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    # Очищаем предыдущие данные
    context.user_data.clear()
    context.user_data['task_works'] = []
    
    logger.info("Starting task creation process")
    
    # Сразу переходим к добавлению работ
    return add_work_type(update, context)

def add_work_type(update: Update, context: CallbackContext) -> int:
    # Создаем клавиатуру для выбора вида работы
    keyboard = []
    for i in range(0, len(WORK_TYPES), 2):
        row = []
        if i < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i], callback_data=f'add_work_{i}'))
        if i+1 < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i+1], callback_data=f'add_work_{i+1}'))
        keyboard.append(row)
    
    # Кнопки для завершения добавления работ или отмены
    keyboard.append([
        InlineKeyboardButton("✅ Завершить добавление работ", callback_data='finish_adding_works')
    ])
    keyboard.append([
        InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')
    ])
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text="Выберите вид работы для добавления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        update.callback_query.answer()
    else:
        update.message.reply_text(
            "Выберите вид работы для добавления:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return ADDING_WORK_TYPES

def select_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[2])
    context.user_data['current_work_type'] = WORK_TYPES[work_type_idx]
    logger.info(f"Selected work type: {WORK_TYPES[work_type_idx]}")
    
    query.edit_message_text(
        text=f"Введите количество для работы '{WORK_TYPES[work_type_idx]}':",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
    )
    return SETTING_WORK_AMOUNT

def set_work_amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
            
        work_type = context.user_data['current_work_type']
        context.user_data['task_works'].append({
            'work_type': work_type,
            'amount': amount
        })
        logger.info(f"Added work: {work_type} - {amount}")
        
        update.message.reply_text(
            f"✅ Работа '{work_type}' в количестве {amount} добавлена к задаче.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить еще работу", callback_data='add_work_type')]])
        )
        
        return add_work_type(update, context)
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое положительное число:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return SETTING_WORK_AMOUNT
    except Exception as e:
        logger.error(f"Error in set_work_amount: {e}")
        update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return SETTING_WORK_AMOUNT

def finish_adding_works(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    if not context.user_data.get('task_works'):
        query.edit_message_text(
            text="❌ Не добавлено ни одной работы. Добавьте хотя бы одну работу.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return ADDING_WORK_TYPES
    
    # Формируем сообщение с подтверждением
    message = "📝 Подтвердите создание задачи:\n\n"
    message += "🔧 Добавленные работы:\n"
    
    for work in context.user_data['task_works']:
        message += f"- {work['work_type']}: {work['amount']}\n"
    
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data='confirm_task')],
        [InlineKeyboardButton("✏️ Редактировать", callback_data='add_work_type')],
        [InlineKeyboardButton("❌ Отменить", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(
        text=message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_TASK

def confirm_task(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    try:
        # Создаем задачу в базе данных
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Создаем основную задачу (без описания)
                cursor.execute(
                    "INSERT INTO tasks (created_by) VALUES (%s) RETURNING task_id",
                    (query.from_user.id,)
                )
                task_id = cursor.fetchone()[0]
                logger.info(f"Created task with ID: {task_id}")
                
                # Добавляем все работы
                for work in context.user_data['task_works']:
                    cursor.execute(
                        "INSERT INTO task_works (task_id, work_type, amount) VALUES (%s, %s, %s)",
                        (task_id, work['work_type'], work['amount'])
                    )
                    logger.info(f"Added work to task: {work['work_type']} - {work['amount']}")
                
                conn.commit()
        
        query.edit_message_text(
            text="✅ Задача успешно создана!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        
        # Очищаем временные данные
        context.user_data.clear()
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        query.edit_message_text(
            text="❌ Ошибка при создании задачи. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        return ConversationHandler.END

# Просмотр задач
def view_tasks(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Получаем список задач с работами
                cursor.execute("""
                    SELECT t.task_id, t.created_at, u.full_name,
                           tw.work_type, tw.amount
                    FROM tasks t
                    JOIN task_works tw ON t.task_id = tw.task_id
                    JOIN users u ON t.created_by = u.user_id
                    WHERE t.is_active = TRUE
                    ORDER BY t.created_at DESC, tw.created_at
                """)
                tasks = cursor.fetchall()
        
        if not tasks:
            query.edit_message_text(
                text="ℹ️ Нет активных задач.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
            )
            return
        
        # Группируем работы по задачам
        tasks_dict = {}
        for task in tasks:
            task_id = task[0]
            if task_id not in tasks_dict:
                tasks_dict[task_id] = {
                    'created_at': task[1],
                    'created_by': task[2],
                    'works': []
                }
            tasks_dict[task_id]['works'].append((task[3], task[4]))
        
        message = "📋 Список активных задач:\n\n"
        for task_id, task_data in tasks_dict.items():
            message += (
                f"🔹 ID задачи: {task_id}\n"
                f"📅 Дата создания: {task_data['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
                f"👤 Создал: {task_data['created_by']}\n"
                f"🔧 Работы:\n"
            )
            
            for work in task_data['works']:
                message += f"  - {work[0]}: {work[1]}\n"
            
            message += "\n"
        
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
                    SELECT r.report_id, u.full_name, 
                           COALESCE(t.task_id::text, 'Без задачи') as task_id,
                           r.work_type, r.amount, r.report_date
                    FROM reports r
                    JOIN users u ON r.user_id = u.user_id
                    LEFT JOIN tasks t ON r.task_id = t.task_id
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
                f"📌 ID задачи: {report[2]}\n"
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
        # Создаем клавиатуру с выбором работы
        keyboard = []
        for i in range(0, len(WORK_TYPES), 2):
            row = []
            if i < len(WORK_TYPES):
                row.append(InlineKeyboardButton(WORK_TYPES[i], callback_data=f'report_work_{i}'))
            if i+1 < len(WORK_TYPES):
                row.append(InlineKeyboardButton(WORK_TYPES[i+1], callback_data=f'report_work_{i+1}'))
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
        
        query.edit_message_text(
            text="Выберите вид работы:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REPORTING_WORK_TYPE
    except Exception as e:
        logger.error(f"Error starting report: {e}")
        query.edit_message_text(
            text="❌ Ошибка при начале отчета.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
        return ConversationHandler.END

def report_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[2])
    work_type = WORK_TYPES[work_type_idx]
    context.user_data['report_work_type'] = work_type
    
    # Проверяем, есть ли активные задачи для привязки отчета
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT task_id FROM tasks WHERE is_active = TRUE ORDER BY created_at DESC
            """)
            tasks = cursor.fetchall()
    
    if tasks:
        keyboard = []
        for task in tasks:
            keyboard.append([InlineKeyboardButton(f"Задача {task[0]}", callback_data=f'report_task_{task[0]}')])
        
        keyboard.append([InlineKeyboardButton("📌 Без задачи", callback_data='report_without_task')])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='send_report')])
        
        query.edit_message_text(
            text=f"Выберите задачу для работы '{work_type}' или отправьте без задачи:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        context.user_data['report_task_id'] = None
        query.edit_message_text(
            text=f"Введите количество выполненной работы '{work_type}':",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='send_report')]])
        )
        return REPORTING_AMOUNT

def select_task_for_report(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    if query.data == 'report_without_task':
        context.user_data['report_task_id'] = None
    else:
        task_id = int(query.data.split('_')[2])
        context.user_data['report_task_id'] = task_id
    
    query.edit_message_text(
        text=f"Введите количество выполненной работы '{context.user_data['report_work_type']}':",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='send_report')]])
    )
    return REPORTING_AMOUNT

def save_report(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text.strip())
        if amount <= 0:
            raise ValueError
        
        work_type = context.user_data['report_work_type']
        task_id = context.user_data.get('report_task_id')
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
            [InlineKeyboardButton("➕ Добавить еще работу", callback_data='send_report')],
            [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
        ]
        
        task_info = f" к задаче {task_id}" if task_id else " (без задачи)"
        update.message.reply_text(
            f"✅ Отчет по работе '{work_type}'{task_info} в количестве {amount} успешно сохранен!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое число больше 0.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='send_report')]])
        )
        return REPORTING_AMOUNT
    except Exception as e:
        logger.error(f"Error saving report: {e}")
        update.message.reply_text(
            "❌ Ошибка при сохранении отчета.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]])
        )
        return ConversationHandler.END

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
        update.callback_query.answer()
        update.callback_query.edit_message_text(
            text="⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
    else:
        update.message.reply_text(
            "⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )

def unknown_message(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Я не понимаю эту команду. Используйте кнопки меню.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Главное меню", callback_data='main_menu')]])
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
    dispatcher.add_handler(CommandHandler("cancel", cancel))
    
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
    dispatcher.add_handler(CallbackQueryHandler(select_task_for_report, pattern='^report_task_|^report_without_task$'))
    dispatcher.add_handler(CallbackQueryHandler(select_work_type, pattern='^add_work_[0-9]+$'))
    dispatcher.add_handler(CallbackQueryHandler(finish_adding_works, pattern='^finish_adding_works$'))
    dispatcher.add_handler(CallbackQueryHandler(confirm_task, pattern='^confirm_task$'))
    
    # ConversationHandler для админских функций
    admin_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_task, pattern='^set_task$')],
        states={
            ADDING_WORK_TYPES: [
                CallbackQueryHandler(
                    select_work_type, 
                    pattern='^add_work_[0-9]+$'
                ),
                CallbackQueryHandler(
                    finish_adding_works,
                    pattern='^finish_adding_works$'
                )
            ],
            SETTING_WORK_AMOUNT: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    set_work_amount
                )
            ],
            CONFIRM_TASK: [
                CallbackQueryHandler(
                    confirm_task,
                    pattern='^confirm_task$'
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(admin_panel, pattern='^admin_panel$')
        ],
        per_message=True,
        allow_reentry=True
    )
    dispatcher.add_handler(admin_conv_handler)
    
    # ConversationHandler для управления пользователями
    user_management_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_user, pattern='^add_user$'),
            CallbackQueryHandler(remove_user, pattern='^remove_user$')
        ],
        states={
            ADMIN_ADD_USER: [MessageHandler(Filters.text & ~Filters.command, add_user_handler)],
            ADMIN_REMOVE_USER: [MessageHandler(Filters.text & ~Filters.command, remove_user_handler)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(manage_users, pattern='^manage_users$')
        ],
        per_message=True
    )
    dispatcher.add_handler(user_management_conv_handler)
    
    # ConversationHandler для отправки отчетов
    report_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_report, pattern='^send_report$')],
        states={
            REPORTING_WORK_TYPE: [CallbackQueryHandler(report_work_type, pattern='^report_work_[0-9]+$')],
            REPORTING_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, save_report)]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(show_main_menu, pattern='^main_menu$')
        ],
        per_message=True
    )
    dispatcher.add_handler(report_conv_handler)
    
    # Обработчик неизвестных сообщений
    dispatcher.add_handler(MessageHandler(Filters.all, unknown_message))
    
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
