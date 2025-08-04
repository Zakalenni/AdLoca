import os
import logging
import time
from datetime import datetime, timedelta
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
(
    MAIN_MENU,
    ADMIN_PANEL,
    SET_TASK_AMOUNT,
    ADD_WORK_TYPE,
    SET_WORK_AMOUNT,
    CONFIRM_TASK,
    REPORT_WORK_TYPE,
    REPORT_AMOUNT,
    MANAGE_USERS,
    ADD_USER,
    REMOVE_USER
) = range(11)

# Виды работ
WORK_TYPES = [
    "Распил доски", "Фугование", "Рейсмусование", "Распил на детали",
    "Отверстия в пласть", "Присадка отверстий", "Фрезеровка пазов",
    "Фрезеровка углов", "Шлифовка", "Подрез", "Сборка", "Дошлифовка",
    "Покраска каркасов", "Покраска ножек", "Покраска ручек",
    "Рез на коробки", "Сборка коробок", "Упаковка",
    "Фрезеровка пазов ручек", "Распил на ручки"
]

def get_db_connection():
    max_retries = 3
    retry_delay = 5
    
    for attempt in range(max_retries):
        try:
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
        except psycopg2.OperationalError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"Connection failed, retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
            time.sleep(retry_delay)

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # (остальные CREATE TABLE остаются без изменений)
                pass
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

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

def start(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)
    
    if not is_user_allowed(user.id):
        update.message.reply_text("⛔ Доступ запрещен. Обратитесь к администратору.")
        return MAIN_MENU
    
    return show_main_menu(update, context)

def show_main_menu(update: Update, context: CallbackContext) -> int:
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
    return MAIN_MENU

def cancel(update: Update, context: CallbackContext) -> int:
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
        return show_main_menu(update, context)
    except Exception as e:
        logger.error(f"Error in cancel function: {e}")
        return MAIN_MENU

def admin_panel(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return MAIN_MENU
    
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
    return ADMIN_PANEL

def set_task(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    context.user_data.clear()
    context.user_data['task_works'] = []
    context.user_data['task_description'] = f"Задача от {datetime.now().strftime('%d.%m.%Y')}"
    
    query.edit_message_text(
        text=f"Название задачи: {context.user_data['task_description']}\n\nВведите общее количество для задачи (целое число):",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
    )
    return SET_TASK_AMOUNT

def set_task_amount(update: Update, context: CallbackContext) -> int:
    try:
        if update.message:
            total_amount = int(update.message.text.strip())
            if total_amount <= 0:
                raise ValueError
                
            context.user_data['total_amount'] = total_amount
            
            return add_work_type(update, context)
        else:
            update.callback_query.answer()
            return SET_TASK_AMOUNT
            
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое положительное число:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
        return SET_TASK_AMOUNT
    except Exception as e:
        logger.error(f"Error in set_task_amount: {e}")
        update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]])
        )
        return SET_TASK_AMOUNT

def add_work_type(update: Update, context: CallbackContext) -> int:
    keyboard = []
    for i in range(0, len(WORK_TYPES), 2):
        row = []
        if i < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i], callback_data=f'add_work_{i}'))
        if i+1 < len(WORK_TYPES):
            row.append(InlineKeyboardButton(WORK_TYPES[i+1], callback_data=f'add_work_{i+1}'))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✅ Завершить добавление работ", callback_data='finish_adding_works')])
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')])
    
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
    
    return ADD_WORK_TYPE

def select_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[2])
    context.user_data['current_work_type'] = WORK_TYPES[work_type_idx]
    
    query.edit_message_text(
        text=f"Введите количество для работы '{WORK_TYPES[work_type_idx]}':",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
    )
    return SET_WORK_AMOUNT

def set_work_amount(update: Update, context: CallbackContext) -> int:
    try:
        if update.message:
            amount = int(update.message.text.strip())
            if amount <= 0:
                raise ValueError
                
            work_type = context.user_data['current_work_type']
            context.user_data['task_works'].append({
                'work_type': work_type,
                'amount': amount
            })
            
            update.message.reply_text(
                f"✅ Работа '{work_type}' в количестве {amount} добавлена к задаче.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Добавить еще работу", callback_data='add_work_type')]])
            )
            
            return add_work_type(update, context)
        else:
            update.callback_query.answer()
            return SET_WORK_AMOUNT
            
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое положительное число:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return SET_WORK_AMOUNT
    except Exception as e:
        logger.error(f"Error in set_work_amount: {e}")
        update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return SET_WORK_AMOUNT

def finish_adding_works(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    if not context.user_data.get('task_works'):
        query.edit_message_text(
            text="❌ Не добавлено ни одной работы. Добавьте хотя бы одну работу.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='add_work_type')]])
        )
        return ADD_WORK_TYPE
    
    message = "📝 Подтвердите создание задачи:\n\n"
    message += f"🔹 Название: {context.user_data['task_description']}\n"
    message += f"🔹 Общее количество: {context.user_data['total_amount']}\n\n"
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
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO tasks (description, total_amount, created_by) VALUES (%s, %s, %s) RETURNING task_id",
                    (context.user_data['task_description'], 
                     context.user_data['total_amount'], 
                     query.from_user.id)
                )
                task_id = cursor.fetchone()[0]
                
                for work in context.user_data['task_works']:
                    cursor.execute(
                        "INSERT INTO task_works (task_id, work_type, amount) VALUES (%s, %s, %s)",
                        (task_id, work['work_type'], work['amount'])
                    )
                
                conn.commit()
        
        query.edit_message_text(
            text=f"✅ Задача '{context.user_data['task_description']}' успешно создана!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        
        context.user_data.clear()
        return ADMIN_PANEL
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        query.edit_message_text(
            text="❌ Ошибка при создании задачи. Попробуйте еще раз.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В админ-панель", callback_data='admin_panel')]])
        )
        return ADMIN_PANEL

def send_report(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
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
    return REPORT_WORK_TYPE

def report_work_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    work_type_idx = int(query.data.split('_')[2])
    work_type = WORK_TYPES[work_type_idx]
    context.user_data['report_work_type'] = work_type
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT task_id, description FROM tasks WHERE is_active = TRUE ORDER BY created_at DESC
            """)
            tasks = cursor.fetchall()
    
    if tasks:
        keyboard = []
        for task in tasks:
            keyboard.append([InlineKeyboardButton(task[1], callback_data=f'report_task_{task[0]}')])
        
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
        return REPORT_AMOUNT
    
    return REPORT_WORK_TYPE

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
    return REPORT_AMOUNT

def save_report(update: Update, context: CallbackContext) -> int:
    try:
        if update.message:
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
            return MAIN_MENU
        else:
            update.callback_query.answer()
            return REPORT_AMOUNT
            
    except ValueError:
        update.message.reply_text(
            "❌ Неверный формат количества. Введите целое число больше 0.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data='send_report')]])
        )
        return REPORT_AMOUNT
    except Exception as e:
        logger.error(f"Error saving report: {e}")
        update.message.reply_text(
            "❌ Ошибка при сохранении отчета.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data='main_menu')]])
        )
        return MAIN_MENU

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


def manage_users(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    
    if not is_admin(query.from_user.id):
        query.edit_message_text(text="⛔ У вас нет прав администратора.")
        return MAIN_MENU
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data='add_user')],
        [InlineKeyboardButton("➖ Удалить пользователя", callback_data='remove_user')],
        [InlineKeyboardButton("🔙 Назад", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(
        text="Управление пользователями:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MANAGE_USERS


def main() -> None:
    # Инициализация базы данных
    try:
        init_db()
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
        return

    # Создание Updater
    token = os.getenv('TELEGRAM_TOKEN')
    if not token:
        logger.error("Не задан TELEGRAM_TOKEN")
        return
        
    updater = Updater(token, use_context=True)
    dispatcher = updater.dispatcher

    # Определение состояний ConversationHandler
    (
        SETTING_TASK_DESCRIPTION, SETTING_TASK_AMOUNT,
        ADDING_WORK_TYPES, SETTING_WORK_AMOUNT, CONFIRM_TASK,
        REPORTING_WORK_TYPE, REPORTING_AMOUNT,
        ADMIN_ADD_USER, ADMIN_REMOVE_USER
    ) = range(9)

    # Обработчики команд
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("cancel", cancel))

    # Основные обработчики callback-запросов
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

    # ConversationHandler для создания задач
    task_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_task, pattern='^set_task$')],
        states={
            SETTING_TASK_DESCRIPTION: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    lambda update, context: set_task_description(update, context, SETTING_TASK_AMOUNT)
                )
            ],
            SETTING_TASK_AMOUNT: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    lambda update, context: set_task_amount(update, context, ADDING_WORK_TYPES)
                )
            ],
            ADDING_WORK_TYPES: [
                CallbackQueryHandler(
                    lambda update, context: select_work_type(update, context, SETTING_WORK_AMOUNT),
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
                    lambda update, context: set_work_amount(update, context, ADDING_WORK_TYPES)
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
        per_message=True
    )
    dispatcher.add_handler(task_conv_handler)

    # ConversationHandler для отправки отчетов
    report_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_report, pattern='^send_report$')],
        states={
            REPORTING_WORK_TYPE: [
                CallbackQueryHandler(
                    report_work_type,
                    pattern='^report_work_[0-9]+$'
                )
            ],
            REPORTING_AMOUNT: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    save_report
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(show_main_menu, pattern='^main_menu$')
        ],
        per_message=True
    )
    dispatcher.add_handler(report_conv_handler)

    # ConversationHandler для управления пользователями
    user_management_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_user, pattern='^add_user$'),
            CallbackQueryHandler(remove_user, pattern='^remove_user$')
        ],
        states={
            ADMIN_ADD_USER: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    add_user_handler
                )
            ],
            ADMIN_REMOVE_USER: [
                MessageHandler(
                    Filters.text & ~Filters.command,
                    remove_user_handler
                )
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(manage_users, pattern='^manage_users$')
        ],
        per_message=True
    )
    dispatcher.add_handler(user_management_conv_handler)

    # Обработчик неизвестных сообщений
    dispatcher.add_handler(MessageHandler(
        Filters.text & ~Filters.command,
        unknown_message
    ))

    # Обработчик ошибок
    dispatcher.add_error_handler(error_handler)

    # Планировщик для удаления старых сообщений
    job_queue = updater.job_queue
    job_queue.run_daily(delete_old_messages, time=time(hour=3, minute=0))

    # Запуск бота
    try:
        updater.start_polling(drop_pending_updates=True)
        logger.info("Бот успешно запущен")
        updater.idle()
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
