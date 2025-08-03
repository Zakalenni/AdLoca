import os
import logging
from datetime import datetime, timedelta, time  # Добавлен time
from typing import Dict, List

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы для состояний ConversationHandler
SETTING_TASK, SETTING_WORK_TYPE, SETTING_AMOUNT = range(3)
REPORTING_WORK_TYPE, REPORTING_AMOUNT, REPORTING_ADDITIONAL = range(3)
ADMIN_ADD_USER, ADMIN_REMOVE_USER = range(2)

# Виды работ
WORK_TYPES = [
    "Распил доски",
    "Фугование",
    "Рейсмусование",
    "Распил на детали",
    "Отверстия в пласть",
    "Присадка отверстий",
    "Фрезеровка пазов",
    "Фрезеровка углов",
    "Шлифовка",
    "Подрез",
    "Сборка",
    "Дошлифовка",
    "Покраска каркасов",
    "Покраска ножек",
    "Покраска ручек",
    "Рез на коробки",
    "Сборка коробок",
    "Упаковка",
    "Фрезеровка пазов ручек",
    "Распил на ручки"
]

# Подключение к PostgreSQL
def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        sslmode='require'
    )

# Инициализация базы данных
def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Удаляем старую таблицу (если нужно)
            cursor.execute("DROP TABLE IF EXISTS users CASCADE")
            
            # Создаем новую таблицу с правильными столбцами (без комментариев в SQL)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    is_admin BOOLEAN DEFAULT FALSE,
                    registered_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Создаем остальные таблицы (также без комментариев в SQL)
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
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS allowed_users (
                    user_id BIGINT PRIMARY KEY
                )
            """)
            
            conn.commit()
# Проверка, является ли пользователь администратором
def is_admin(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT is_admin FROM users WHERE user_id = %s", (user_id,))
            user = cursor.fetchone()
            return user and user['is_admin']

# Проверка, разрешен ли пользователь
def is_user_allowed(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM allowed_users WHERE user_id = %s", (user_id,))
            return cursor.fetchone() is not None

# Регистрация пользователя
def register_user(user_id: int, username: str, first_name: str, last_name: str):
    try:
        full_name = f"{first_name} {last_name}".strip()
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
    except psycopg2.Error as e:
        logger.error(f"Database error in register_user: {e}")
        # Можно добавить автоматическое восстановление структуры БД
        init_db()
        register_user(user_id, username, first_name, last_name)  # Повторная попытка

# Команда /start
def start(update: Update, context: CallbackContext) -> None:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    
    if not is_user_allowed(user.id):
        update.message.reply_text("⛔ Доступ запрещен. Обратитесь к администратору.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Отправить отчет", callback_data='send_report')],
        [InlineKeyboardButton("📋 Посмотреть задачи", callback_data='view_tasks')]
    ]
    
    if is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👨‍💻 Админ-панель", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        f"Привет, {user.first_name}! Я бот для учета выполнения работ.\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

# Главное меню
def main_menu(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Отправить отчет", callback_data='send_report')],
        [InlineKeyboardButton("📋 Посмотреть задачи", callback_data='view_tasks')]
    ]
    
    if is_admin(query.from_user.id):
        keyboard.append([InlineKeyboardButton("👨‍💻 Админ-панель", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text="Главное меню. Выберите действие:",
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
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text="Админ-панель. Выберите действие:",
        reply_markup=reply_markup
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
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text="Управление пользователями:",
        reply_markup=reply_markup
    )

# Добавление пользователя - запрос ID
def add_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите ID пользователя, которого хотите добавить:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ADMIN_ADD_USER

# Обработка добавления пользователя
def add_user_handler(update: Update, context: CallbackContext) -> int:
    user_id = update.message.text.strip()
    
    try:
        user_id_int = int(user_id)
    except ValueError:
        update.message.reply_text(
            "Неверный формат ID. ID должен быть числом.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ADMIN_ADD_USER
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO allowed_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id_int,))
            conn.commit()
    
    update.message.reply_text(
        f"Пользователь с ID {user_id_int} добавлен в список разрешенных.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ConversationHandler.END

# Удаление пользователя - запрос ID
def remove_user(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите ID пользователя, которого хотите удалить:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ADMIN_REMOVE_USER

# Обработка удаления пользователя
def remove_user_handler(update: Update, context: CallbackContext) -> int:
    user_id = update.message.text.strip()
    
    try:
        user_id_int = int(user_id)
    except ValueError:
        update.message.reply_text(
            "Неверный формат ID. ID должен быть числом.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
        )
        return ADMIN_REMOVE_USER
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM allowed_users WHERE user_id = %s", (user_id_int,))
            conn.commit()
    
    update.message.reply_text(
        f"Пользователь с ID {user_id_int} удален из списка разрешенных.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='manage_users')]])
    )
    return ConversationHandler.END

# Постановка задачи - начало
def set_task(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    query.edit_message_text(
        text="Введите описание задачи и общее количество (например: 'Изготовление столов - 100'):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
    )
    return SETTING_TASK

# Обработка описания задачи
def set_task_description(update: Update, context: CallbackContext) -> int:
    try:
        text = update.message.text
        parts = text.rsplit('-', 1)
        
        if len(parts) != 2:
            update.message.reply_text(
                "❌ Неверный формат. Введите: 'Описание задачи - Общее количество'",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_panel')]])
            )
            return SETTING_TASK
            
        description = parts[0].strip()
        try:
            total_amount = int(parts[1].strip())
        except ValueError:
            update.message.reply_text(
                "❌ Количество должно быть числом",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Отмена", callback_data='admin_panel')]])
            )
            return SETTING_TASK
        
        # Сохраняем данные в context.user_data
        context.user_data['task_description'] = description
        context.user_data['total_amount'] = total_amount
        
        # Создаем задачу в БД
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (description, total_amount, created_by) VALUES (%s, %s, %s) RETURNING task_id",
                    (description, total_amount, update.message.from_user.id)
                )
                task_id = cursor.fetchone()[0]
                conn.commit()
        
        context.user_data['task_id'] = task_id
        logger.info(f"New task created: {task_id} - {description}")
        
        # Кнопки для выбора дня недели
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        buttons = [[InlineKeyboardButton(day, callback_data=f'day_{i}')] for i, day in enumerate(days)]
        buttons.append([InlineKeyboardButton("🔙 Отмена", callback_data='admin_panel')])
        
        update.message.reply_text(
            "📅 Выберите день недели для распределения работ:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return SETTING_WORK_TYPE
        
    except Exception as e:
        logger.error(f"Error in set_task_description: {e}")
        update.message.reply_text(
            "⚠️ Произошла ошибка при создании задачи",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        return ConversationHandler.END

# Выбор вида работы для задачи
def set_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    day_of_week = int(query.data.split('_')[1])
    context.user_data['day_of_week'] = day_of_week
    
    # Создаем кнопки для выбора вида работы
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

# Установка количества для выбранной работы
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
    return ConversationHandler.END

# Сохранение распределения работы
def save_work_assignment(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text)
    except ValueError:
        update.message.reply_text(
            "Неверный формат количества. Введите целое число.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'day_{context.user_data["day_of_week"]}')]])
        )
        return SETTING_AMOUNT
    
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
    
    update.message.reply_text(
        f"Работа '{work_type}' на {['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'][day_of_week]} "
        f"в количестве {amount} успешно добавлена к задаче.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
    )
    return ConversationHandler.END

# Просмотр задач
def view_tasks(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT t.task_id, t.description, t.total_amount, 
                       COALESCE(SUM(r.amount), 0) AS completed,
                       (COALESCE(SUM(r.amount), 0) * 100 / t.total_amount) AS progress
                FROM tasks t
                LEFT JOIN reports r ON t.task_id = r.task_id
                WHERE t.is_active = TRUE
                GROUP BY t.task_id
                ORDER BY t.created_at DESC
            """)
            tasks = cursor.fetchall()
    
    if not tasks:
        query.edit_message_text(
            text="Нет активных задач.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
        return
    
    message = "📋 Список активных задач:\n\n"
    for task in tasks:
        message += (
            f"🔹 {task['description']}\n"
            f"📌 Всего: {task['total_amount']}\n"
            f"✅ Выполнено: {task['completed']}\n"
            f"📊 Прогресс: {task['progress']}%\n\n"
        )
    
    query.edit_message_text(
        text=message,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
    )

# Просмотр отчетов (для админа)
def view_reports(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return
    
    # Получаем последние отчеты
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("""
                SELECT r.report_id, u.first_name, u.last_name, t.description, 
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
            text="Нет отчетов для отображения.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
        return
    
    message = "📊 Последние отчеты:\n\n"
    for report in reports:
        message += (
            f"👤 {report['first_name']} {report['last_name']}\n"
            f"📅 {report['report_date'].strftime('%d.%m.%Y')}\n"
            f"📌 Задача: {report['description']}\n"
            f"🔧 Работа: {report['work_type']}\n"
            f"🔢 Количество: {report['amount']}\n\n"
        )
    
    query.edit_message_text(
        text=message,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
    )

# Отправка отчета - выбор задачи
def send_report(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute("SELECT task_id, description FROM tasks WHERE is_active = TRUE ORDER BY created_at DESC")
            tasks = cursor.fetchall()
    
    if not tasks:
        query.edit_message_text(
            text="Нет активных задач для отчета.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='main_menu')]])
        )
        return ConversationHandler.END
    
    keyboard = []
    for task in tasks:
        keyboard.append([InlineKeyboardButton(task['description'], callback_data=f'task_{task["task_id"]}')])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='main_menu')])
    
    query.edit_message_text(
        text="Выберите задачу для отчета:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REPORTING_WORK_TYPE

# Отправка отчета - выбор вида работы
def report_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    task_id = int(query.data.split('_')[1])
    context.user_data['report_task_id'] = task_id
    
    # Создаем кнопки для выбора вида работы
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

# Отправка отчета - ввод количества
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

# Сохранение отчета
def save_report(update: Update, context: CallbackContext) -> int:
    try:
        amount = int(update.message.text)
    except ValueError:
        update.message.reply_text(
            "Неверный формат количества. Введите целое число.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f'task_{context.user_data["report_task_id"]}')]])
        )
        return REPORTING_AMOUNT
    
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
    
    # Предложение добавить еще работу
    keyboard = [
        [InlineKeyboardButton("➕ Добавить еще работу", callback_data=f'task_{task_id}')],
        [InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]
    ]
    
    update.message.reply_text(
        f"Отчет по работе '{work_type}' в количестве {amount} успешно сохранен.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

# Отмена действий
def cancel(update: Update, context: CallbackContext) -> int:
    update.message.reply_text(
        "Действие отменено.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

# Удаление старых сообщений
def delete_old_messages(context: CallbackContext):
    # Удаляем сообщения старше 7 дней
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM reports WHERE reported_at < NOW() - INTERVAL '7 days'")
            conn.commit()

# Обработка ошибок
def error_handler(update: Update, context: CallbackContext) -> None:
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
    
    # Создание Updater и передача токена бота
    token = os.getenv('TELEGRAM_TOKEN')
    updater = Updater(token)
    
    # Получаем диспетчер для регистрации обработчиков
    dispatcher = updater.dispatcher
    
    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    
    # ... остальной код обработчиков ...
    dispatcher.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(admin_panel, pattern='^admin_panel$'))
    dispatcher.add_handler(CallbackQueryHandler(send_report, pattern='^send_report$'))
    dispatcher.add_handler(CallbackQueryHandler(view_tasks, pattern='^view_tasks$'))
    dispatcher.add_handler(CallbackQueryHandler(manage_users, pattern='^manage_users$'))
    dispatcher.add_handler(CallbackQueryHandler(set_task, pattern='^set_task$'))
    dispatcher.add_handler(CallbackQueryHandler(view_reports, pattern='^view_reports$'))
    

    # Планировщик для удаления старых сообщений (раз в день)
    job_queue = updater.job_queue
    job_queue.run_daily(delete_old_messages, time=time(hour=3, minute=0))  # Исправленная строка

    # Регистрация ConversationHandler для админских задач
    admin_task_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_task, pattern='^set_task$')],
        states={
            SETTING_TASK: [MessageHandler(Filters.text & ~Filters.command, set_task_description)],
            SETTING_WORK_TYPE: [
                CallbackQueryHandler(set_work_type, pattern='^day_[0-6]$'),
                CallbackQueryHandler(cancel, pattern='^cancel$')
            ],
            SETTING_AMOUNT: [
                CallbackQueryHandler(set_work_amount, pattern='^work_[0-9]+$'),
                MessageHandler(Filters.text & ~Filters.command, save_work_assignment)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
            CommandHandler('cancel', cancel)
        ],
        allow_reentry=True
    )
    dispatcher.add_handler(admin_task_handler)
    
    # Запуск бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()






