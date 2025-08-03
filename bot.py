import os
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from dotenv import load_dotenv

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

# Состояния для опроса
class SurveyStates(StatesGroup):
    WAITING_TASK = State()
    WAITING_WORK_TYPE = State()
    WAITING_PROGRESS = State()

# База данных для хранения отчетов
reports_db = {}
# Хранилище ID сообщений для удаления
user_message_history = {}

# --- Вспомогательные функции ---
async def safe_delete_messages(chat_id: int, message_ids: list):
    """Безопасное удаление сообщений"""
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения {msg_id}: {e}")

async def update_message_history(user_id: int, new_msg: types.Message):
    """Обновляем историю сообщений пользователя"""
    if user_id not in user_message_history:
        user_message_history[user_id] = []
    
    # Удаляем старые сообщения
    if len(user_message_history[user_id]) > 3:  # Храним последние 3 сообщения
        old_msg_id = user_message_history[user_id].pop(0)
        try:
            await bot.delete_message(chat_id=new_msg.chat.id, message_id=old_msg_id)
        except:
            pass
    
    user_message_history[user_id].append(new_msg.message_id)

def get_current_weekday():
    """Возвращает текущий день недели"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[datetime.now().weekday()]

def generate_report(user_id: int) -> str:
    """Генерирует отчет по пользователю"""
    if user_id not in reports_db or not reports_db[user_id]:
        return "📭 У вас пока нет сохраненных отчетов"
    
    report = ["📊 <b>Ваши отчеты</b>\n"]
    for date, records in reports_db[user_id].items():
        report.append(f"\n📅 <b>{date}</b>")
        for record in records:
            report.append(
                f"  • {record['work_type']}: {record['progress']}%"
                f"\n  📝 Задача: {record['task']}\n"
            )
    
    return "\n".join(report)

def generate_admin_report():
    """Генерирует сводный отчет для администратора"""
    if not reports_db:
        return "📭 Нет данных по выполнению работ"
    
    report = ["📈 <b>Сводный отчет по команде</b>\n"]
    for user_id, user_data in reports_db.items():
        report.append(f"\n👤 <b>Пользователь ID: {user_id}</b>")
        for date, records in user_data.items():
            report.append(f"\n  📅 {date}")
            for record in records:
                report.append(f"    • {record['work_type']}: {record['progress']}%")
    
    return "\n".join(report)

# --- Клавиатуры ---
def get_main_menu_kb():
    """Главное меню с действиями"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="📝 Новый отчет",
        callback_data="new_report"
    ))
    builder.add(types.InlineKeyboardButton(
        text="📊 Мои отчеты",
        callback_data="my_reports"
    ))
    builder.add(types.InlineKeyboardButton(
        text="🆘 Помощь",
        callback_data="help"
    ))
    builder.adjust(1)
    return builder.as_markup()

def get_work_types_kb():
    """Клавиатура с типами работ"""
    builder = ReplyKeyboardBuilder()
    builder.add(types.KeyboardButton(text="Разработка"))
    builder.add(types.KeyboardButton(text="Тестирование"))
    builder.add(types.KeyboardButton(text="Дизайн"))
    builder.add(types.KeyboardButton(text="Документация"))
    builder.add(types.KeyboardButton(text="Другое"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_progress_kb():
    """Клавиатура с процентами выполнения"""
    builder = ReplyKeyboardBuilder()
    for i in range(0, 101, 10):
        builder.add(types.KeyboardButton(text=f"{i}%"))
    builder.adjust(5)
    return builder.as_markup(resize_keyboard=True)

def get_back_to_menu_kb():
    """Кнопка возврата в меню"""
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="🔙 В главное меню",
        callback_data="main_menu"
    ))
    return builder.as_markup()

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    msg = await message.answer(
        "📋 <b>Система учета выполнения работ</b>\n\n"
        "Используйте кнопки ниже для управления отчетами:",
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    await update_message_history(message.from_user.id, msg)

@dp.callback_query(F.data == "main_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 <b>Главное меню</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "new_report")
async def start_new_report(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SurveyStates.WAITING_TASK)
    msg = await callback.message.edit_text(
        "📝 <b>Новый отчет</b>\n\n"
        "Опишите общую задачу, над которой вы работаете:",
        parse_mode="HTML",
        reply_markup=get_back_to_menu_kb()
    )
    await update_message_history(callback.from_user.id, msg)
    await callback.answer()

@dp.callback_query(F.data == "my_reports")
async def show_my_reports(callback: types.CallbackQuery):
    report = generate_report(callback.from_user.id)
    msg = await callback.message.edit_text(
        report,
        parse_mode="HTML",
        reply_markup=get_back_to_menu_kb()
    )
    await update_message_history(callback.from_user.id, msg)
    await callback.answer()

@dp.callback_query(F.data == "help")
async def show_help(callback: types.CallbackQuery):
    help_text = (
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "<b>Как работать с ботом:</b>\n"
        "1. Нажмите <b>Новый отчет</b> для создания отчета\n"
        "2. Укажите задачу, вид работы и процент выполнения\n"
        "3. Просматривайте свои отчеты в любое время\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Главное меню\n"
        "/cancel - Отменить текущее действие"
    )
    msg = await callback.message.edit_text(
        help_text,
        parse_mode="HTML",
        reply_markup=get_back_to_menu_kb()
    )
    await update_message_history(callback.from_user.id, msg)
    await callback.answer()

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    msg = await message.answer(
        "Действие отменено. Возврат в главное меню.",
        reply_markup=get_main_menu_kb()
    )
    await update_message_history(message.from_user.id, msg)

# --- Обработчики состояний ---
@dp.message(SurveyStates.WAITING_TASK)
async def process_task(message: types.Message, state: FSMContext):
    await state.update_data(task=message.text)
    await state.set_state(SurveyStates.WAITING_WORK_TYPE)
    msg = await message.answer(
        "Выберите вид работы:",
        reply_markup=get_work_types_kb()
    )
    await update_message_history(message.from_user.id, msg)

@dp.message(SurveyStates.WAITING_WORK_TYPE)
async def process_work_type(message: types.Message, state: FSMContext):
    await state.update_data(work_type=message.text)
    await state.set_state(SurveyStates.WAITING_PROGRESS)
    msg = await message.answer(
        "Укажите процент выполнения:",
        reply_markup=get_progress_kb()
    )
    await update_message_history(message.from_user.id, msg)

@dp.message(SurveyStates.WAITING_PROGRESS)
async def process_progress(message: types.Message, state: FSMContext):
    try:
        progress = int(message.text.replace("%", ""))
        if not 0 <= progress <= 100:
            raise ValueError
    except ValueError:
        msg = await message.answer(
            "Пожалуйста, укажите процент от 0 до 100",
            reply_markup=get_progress_kb()
        )
        await update_message_history(message.from_user.id, msg)
        return
    
    data = await state.get_data()
    current_date = datetime.now().strftime("%d.%m.%Y")
    weekday = get_current_weekday()
    
    # Сохраняем отчет
    user_id = message.from_user.id
    if user_id not in reports_db:
        reports_db[user_id] = {}
    
    if current_date not in reports_db[user_id]:
        reports_db[user_id][current_date] = []
    
    reports_db[user_id][current_date].append({
        "task": data["task"],
        "work_type": data["work_type"],
        "progress": progress,
        "weekday": weekday
    })
    
    await state.clear()
    report_msg = (
        "✅ <b>Отчет сохранен</b>\n\n"
        f"📅 День: {weekday}, {current_date}\n"
        f"📌 Задача: {data['task']}\n"
        f"🔧 Вид работы: {data['work_type']}\n"
        f"📊 Выполнено: {progress}%"
    )
    
    msg = await message.answer(
        report_msg,
        parse_mode="HTML",
        reply_markup=get_main_menu_kb()
    )
    await update_message_history(message.from_user.id, msg)
    
    # Отправляем уведомление администратору
    admin_id = os.getenv('ADMIN_ID')
    if admin_id:
        try:
            await bot.send_message(
                chat_id=int(admin_id),
                text=f"📌 Новый отчет от @{message.from_user.username}\n\n{report_msg}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки админу: {e}")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
